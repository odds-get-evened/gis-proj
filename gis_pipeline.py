import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import requests

from utm_projection import UTM_ZONE_18N

logger = logging.getLogger(__name__)


class ArcGISError(Exception):
    """Base class for failures talking to an ArcGIS REST service.

    Each subclass carries the HTTP status the backend API should answer with and
    a message that is safe to show to the person using the app.
    """
    status_code = 502

    def __init__(self, service_name: str, detail: str):
        super().__init__(f"{service_name}: {detail}")
        self.service_name = service_name
        self.detail = detail

    @property
    def user_message(self) -> str:
        return f"The {self.service_name} reported a problem. Please try again."


class ArcGISServiceError(ArcGISError):
    """The service answered, but with an error (an HTTP error or an ArcGIS error payload)."""


class ArcGISTimeoutError(ArcGISError):
    """The service did not answer within the timeout, even after retrying."""
    status_code = 504

    @property
    def user_message(self) -> str:
        return f"The {self.service_name} is taking too long to respond. Please try again in a moment."


class ArcGISConnectionError(ArcGISError):
    """The service could not be reached at all (no network, DNS failure, refused connection)."""
    status_code = 503

    @property
    def user_message(self) -> str:
        return f"Could not reach the {self.service_name}. Check your internet connection and try again."


class ArcGISClient:
    """Base client for ArcGIS REST services, with timeouts and a bounded retry.

    Worst case for one request: MAX_ATTEMPTS x (CONNECT + READ) seconds plus backoff,
    about 31 seconds with the values below. The frontend's own request timeout is
    set above this so the backend always gets to report what went wrong.
    """
    SERVICE_NAME = "ArcGIS service"
    CONNECT_TIMEOUT_SECONDS = 5
    READ_TIMEOUT_SECONDS = 10
    MAX_ATTEMPTS = 2
    RETRY_BACKOFF_SECONDS = 1.0
    # Gateway/overload statuses that usually clear up on their own
    RETRYABLE_STATUS_CODES = {502, 503, 504}

    def __init__(self):
        # One session per service reuses connections across requests
        self._session = requests.Session()

    def _make_request(self, url: str, params: Dict) -> Dict:
        params = {**params, "f": "json"}
        logger.info(f"Outgoing Request URL: {url} | Params: {params}")
        response = self._get_with_retry(url, params)
        data = response.json()
        # ArcGIS reports most failures as HTTP 200 with an "error" object in the body
        if "error" in data:
            error = data["error"]
            raise ArcGISServiceError(self.SERVICE_NAME, f"error {error.get('code')}: {error.get('message')}")
        return data

    def _get_with_retry(self, url: str, params: Dict) -> requests.Response:
        """GETs url, retrying timeouts, connection failures and gateway errors once."""
        timeout = (self.CONNECT_TIMEOUT_SECONDS, self.READ_TIMEOUT_SECONDS)
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            is_last_attempt = attempt == self.MAX_ATTEMPTS
            try:
                response = self._session.get(url, params=params, timeout=timeout)
            except requests.Timeout as error:  # checked first: ConnectTimeout is also a ConnectionError
                if is_last_attempt:
                    raise ArcGISTimeoutError(self.SERVICE_NAME, f"no response from {url}") from error
                logger.warning(f"Timed out calling {url} (attempt {attempt}); retrying")
            except requests.ConnectionError as error:
                if is_last_attempt:
                    raise ArcGISConnectionError(self.SERVICE_NAME, f"could not connect to {url}") from error
                logger.warning(f"Could not connect to {url} (attempt {attempt}); retrying")
            else:
                if response.status_code in self.RETRYABLE_STATUS_CODES and not is_last_attempt:
                    logger.warning(f"{url} returned HTTP {response.status_code} (attempt {attempt}); retrying")
                elif not response.ok:
                    raise ArcGISServiceError(self.SERVICE_NAME, f"HTTP {response.status_code} from {url}")
                else:
                    return response
            time.sleep(self.RETRY_BACKOFF_SECONDS * attempt)
        raise AssertionError("unreachable: the last attempt always returns or raises")


class GeocoderService(ArcGISClient):
    """Handles location suggestions and geocoding."""
    SERVICE_NAME = "NYS address lookup service"
    SUGGEST_URL = "https://nysgeohub.ny.gov/arcgis/rest/services/Geocoder/NYS_Geocoder/GeocodeServer/suggest"
    FIND_URL = "https://nysgeohub.ny.gov/arcgis/rest/services/Geocoder/NYS_Geocoder/GeocodeServer/findAddressCandidates"

    def suggest(self, text: str, max_suggestions: int = 50) -> List[Dict]:
        """Gets location suggestions for a given text, filtered to streets, intersections, cities, and counties."""
        params = {
            "text": text,
            "maxSuggestions": max_suggestions,
            "category": "Street Name,Intersection,City,Subregion"
        }
        data = self._make_request(self.SUGGEST_URL, params)
        return data.get("suggestions", [])

    def geocode(self, magic_key: str, out_sr: int = 3857) -> Dict:
        """Geocodes a specific suggestion using its magicKey."""
        params = {"magicKey": magic_key, "outSR": out_sr}
        data = self._make_request(self.FIND_URL, params)
        candidates = data.get("candidates", [])
        if candidates:
            candidate = candidates[0]
            # Inject top-level spatialReference into the candidate object
            candidate["spatialReference"] = data.get("spatialReference")
            return candidate
        return {}

@dataclass
class NearbyMarkers:
    """Result of a nearby-marker search.

    is_partial is True when some sub-layers failed but others answered, so the
    list may be missing markers.
    """
    markers: List[Dict] = field(default_factory=list)
    is_partial: bool = False


class ReferenceMarkerService(ArcGISClient):
    """Finds NYSDOT reference markers within a true ground distance of a point."""
    SERVICE_NAME = "NYSDOT reference marker service"
    MAPSERVER_URL = "https://gis.dot.ny.gov/hostingny/rest/services/Ref_Marker/MapServer"

    # The service draws the same marker feature class in nine sub-layers, one per map
    # scale (1:60,000 down to 1:4,000). All are queried so no marker is missed, and
    # duplicates are removed by OBJECTID.
    LAYER_IDS = (1, 2, 3, 4, 5, 6, 7, 8, 9)

    def find_nearby(self, point: Dict, sr: int, radius_miles: float = 0.5, out_sr: int = 3857) -> NearbyMarkers:
        """
        Returns the unique reference markers within radius_miles of point.

        The server buffers the point by a real distance in miles in the layer's own
        projected coordinate system (UTM 18N, meters), so the search area is a true
        circle whatever spatial reference the input point uses (lat/lon, UTM or Web Mercator).

        Each marker is {"attributes": {...}, "geometry": {..., "spatialReference": {...}}},
        with attributes keyed by their display names (e.g. "Reference Marker Number").

        If some sub-layers fail, the markers from the others are returned with
        is_partial=True. If every sub-layer fails, the first failure is raised,
        preferring a timeout so the message reflects the most likely cause.
        """
        def query(layer_id):
            try:
                return self._query_layer(layer_id, point, sr, radius_miles, out_sr), None
            except ArcGISError as error:
                logger.warning(f"Layer {layer_id} failed: {error}")
                return None, error

        with ThreadPoolExecutor(max_workers=len(self.LAYER_IDS)) as pool:
            outcomes = list(pool.map(query, self.LAYER_IDS))

        errors = [error for _, error in outcomes if error is not None]
        if len(errors) == len(outcomes):
            timeouts = [e for e in errors if isinstance(e, ArcGISTimeoutError)]
            raise (timeouts or errors)[0]

        unique_markers: Dict[int, Dict] = {}
        for markers, _ in outcomes:
            for marker in markers or []:
                unique_markers.setdefault(marker["attributes"].get("OBJECTID"), marker)
        return NearbyMarkers(markers=list(unique_markers.values()), is_partial=bool(errors))

    def _query_layer(self, layer_id: int, point: Dict, sr: int, radius_miles: float, out_sr: int) -> List[Dict]:
        """Runs a distance query against one sub-layer and normalizes its features."""
        params = {
            "geometry": f"{point['x']},{point['y']}",
            "geometryType": "esriGeometryPoint",
            "inSR": sr,
            "spatialRel": "esriSpatialRelIntersects",
            "distance": radius_miles,
            "units": "esriSRUnit_StatuteMile",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": out_sr,
        }
        data = self._make_request(f"{self.MAPSERVER_URL}/{layer_id}/query", params)
        if data.get("exceededTransferLimit"):
            logger.warning(f"Layer {layer_id} returned more markers than the server limit; results are truncated")

        aliases = data.get("fieldAliases", {})
        spatial_reference = data.get("spatialReference", {"wkid": out_sr})
        markers = []
        for feature in data.get("features", []):
            attributes = {aliases.get(name, name): value for name, value in feature.get("attributes", {}).items()}
            geometry = feature.get("geometry")
            if geometry is not None:
                # Query results carry the spatial reference once for the whole response;
                # attach it to each geometry so the map can place the marker on its own.
                geometry = {**geometry, "spatialReference": spatial_reference}
            markers.append({"attributes": attributes, "geometry": geometry})
        return markers

class CoordinateError(ValueError):
    """Raised when text is clearly coordinates but can't be used (e.g. outside New York)."""

    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


@dataclass
class ParsedCoordinates:
    """A location typed as coordinates, ready for a marker search."""
    point: Dict[str, float]  # {"x": ..., "y": ...} in the spatial reference below
    sr: int                  # 4326 (lat/lon) or 26918 (UTM zone 18N)
    description: str         # how the input was read, e.g. "41.7, -74.3 (latitude, longitude)"
    display_point: Dict[str, float]  # the same location as {"x": longitude, "y": latitude}, for drawing on the map


class CoordinateParser:
    """Recognizes coordinates typed into the search box.

    Accepts two numbers separated by a comma, semicolon or spaces:
      - Latitude/longitude in decimal degrees, in either order ("41.7, -74.3" or "-74.3, 41.7").
        A longitude typed without its minus sign is read as west, since all of New York is.
      - UTM zone 18N meters (the NYSDOT system), easting/northing in either order
        ("560638, 4621699").

    Because every marker is in New York, the state's bounds decide which order and
    system the numbers are in. Anything that isn't two numbers (or mixes a small and a
    large number, like "5700 44") is not treated as coordinates, so it falls through to
    the address search.
    """
    LAT_RANGE = (40.0, 45.5)
    LON_RANGE = (-80.0, -71.5)
    UTM_EASTING_RANGE = (100_000, 770_000)
    UTM_NORTHING_RANGE = (4_480_000, 4_990_000)
    MAX_DEGREES = 180
    MIN_UTM_METERS = 1_000

    _NUMBER = r"([+-]?(?:\d+\.?\d*|\.\d+))\s*°?"
    _PATTERN = re.compile(rf"^\s*{_NUMBER}\s*(?:[,;]\s*|\s+){_NUMBER}\s*$")

    def parse(self, text: str) -> Optional[ParsedCoordinates]:
        """Returns the coordinates in text, None if text isn't coordinates.

        Raises CoordinateError if text is coordinates but lies outside New York.
        """
        match = self._PATTERN.match(text)
        if not match:
            return None
        first, second = float(match.group(1)), float(match.group(2))

        if abs(first) <= self.MAX_DEGREES and abs(second) <= self.MAX_DEGREES:
            return self._parse_degrees(first, second)
        if abs(first) >= self.MIN_UTM_METERS and abs(second) >= self.MIN_UTM_METERS:
            return self._parse_utm(first, second)
        return None  # e.g. a house number and a route number

    def _parse_degrees(self, first: float, second: float) -> ParsedCoordinates:
        readings = [
            (first, second, "latitude, longitude"),
            (first, -second, "latitude, longitude; read as west longitude"),
            (second, first, "longitude, latitude"),
            (second, -first, "longitude, latitude; read as west longitude"),
        ]
        for lat, lon, how in readings:
            if self._within(lat, self.LAT_RANGE) and self._within(lon, self.LON_RANGE):
                point = {"x": lon, "y": lat}
                return ParsedCoordinates(point, 4326, f"{self._format(lat)}, {self._format(lon)} ({how})", point)
        raise CoordinateError(
            f"{self._format(first)}, {self._format(second)} is outside New York State. "
            "Enter latitude and longitude in New York, for example 41.7, -74.3."
        )

    def _parse_utm(self, first: float, second: float) -> ParsedCoordinates:
        for easting, northing, how in [(first, second, "easting, northing"), (second, first, "northing, easting")]:
            if self._within(easting, self.UTM_EASTING_RANGE) and self._within(northing, self.UTM_NORTHING_RANGE):
                lat, lon = UTM_ZONE_18N.to_lat_lon(easting, northing)
                return ParsedCoordinates(
                    {"x": easting, "y": northing},
                    26918,
                    f"{self._format(easting)}, {self._format(northing)} (UTM zone 18N, {how})",
                    {"x": lon, "y": lat},
                )
        raise CoordinateError(
            f"{self._format(first)}, {self._format(second)} is outside New York State in UTM zone 18N. "
            "Enter an easting and northing in meters, for example 560638, 4621699."
        )

    @staticmethod
    def _format(value: float) -> str:
        """Plain decimal with up to 6 places, never scientific notation (4621699, not 4.6217e+06)."""
        return f"{value:.6f}".rstrip("0").rstrip(".")

    @staticmethod
    def _within(value: float, bounds: Tuple[float, float]) -> bool:
        return bounds[0] <= value <= bounds[1]


class PipelineOrchestrator:
    """Orchestrates the GIS pipeline workflow."""
    def __init__(self):
        """Initializes services."""
        self.geocoder = GeocoderService()
        self.marker_service = ReferenceMarkerService()
        self.coordinate_parser = CoordinateParser()

    def run(self, query: str, choice_index: Optional[int] = None) -> Optional[List[Dict]]:
        """
        Runs the full GIS pipeline for a given query (address or coordinates).
        """
        # 1. Check if coordinate
        coordinates = self.coordinate_parser.parse(query)
        if coordinates:
            print(f"Detected coordinates: {coordinates.description}")
            return self.marker_service.find_nearby(coordinates.point, coordinates.sr, radius_miles=0.5).markers

        # 2. Suggest
        suggestions = self.geocoder.suggest(query)
        if not suggestions:
            print("No suggestions found.")
            return None

        if choice_index is None:
            print("Select a location:")
            for i, s in enumerate(suggestions):
                print(f"{i}: {s['text']}")
            
            choice_index = int(input("Enter index: "))
        
        selected = suggestions[choice_index]

        # 3. Geocode
        candidate = self.geocoder.geocode(selected['magicKey'])
        if not candidate:
            print("Could not geocode selected location.")
            return None
        
        point = candidate['location']
        sr = candidate.get('spatialReference', {}).get('wkid')
        print(f"Geocoded: {point}")

        # 4. Find nearby reference markers
        return self.marker_service.find_nearby(point, sr, radius_miles=0.5).markers
