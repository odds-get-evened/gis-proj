import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


class ArcGISError(Exception):
    """Raised when an ArcGIS REST service reports an error in its response body."""


class ArcGISClient:
    """Base client for interacting with ArcGIS REST services."""
    TIMEOUT_SECONDS = 15

    def _make_request(self, url: str, params: Dict) -> Dict:
        params = {**params, "f": "json"}
        logger.info(f"Outgoing Request URL: {url} | Params: {params}")
        response = requests.get(url, params=params, timeout=self.TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
        # ArcGIS reports most failures as HTTP 200 with an "error" object in the body
        if "error" in data:
            error = data["error"]
            raise ArcGISError(f"{url} returned error {error.get('code')}: {error.get('message')}")
        return data

class GeocoderService(ArcGISClient):
    """Handles location suggestions and geocoding."""
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

class ReferenceMarkerService(ArcGISClient):
    """Finds NYSDOT reference markers within a true ground distance of a point."""
    MAPSERVER_URL = "https://gis.dot.ny.gov/hostingny/rest/services/Ref_Marker/MapServer"

    # The service draws the same marker feature class in nine sub-layers, one per map
    # scale (1:60,000 down to 1:4,000). All are queried so no marker is missed, and
    # duplicates are removed by OBJECTID.
    LAYER_IDS = (1, 2, 3, 4, 5, 6, 7, 8, 9)

    def find_nearby(self, point: Dict, sr: int, radius_miles: float = 0.5, out_sr: int = 3857) -> List[Dict]:
        """
        Returns the unique reference markers within radius_miles of point.

        The server buffers the point by a real distance in miles in the layer's own
        projected coordinate system (UTM 18N, meters), so the search area is a true
        circle whatever spatial reference the input point uses (lat/lon, UTM or Web Mercator).

        Each result is {"attributes": {...}, "geometry": {..., "spatialReference": {...}}},
        with attributes keyed by their display names (e.g. "Reference Marker Number").
        """
        with ThreadPoolExecutor(max_workers=len(self.LAYER_IDS)) as pool:
            layer_results = pool.map(
                lambda layer_id: self._query_layer(layer_id, point, sr, radius_miles, out_sr),
                self.LAYER_IDS,
            )

        unique_markers: Dict[int, Dict] = {}
        for markers in layer_results:
            for marker in markers:
                unique_markers.setdefault(marker["attributes"].get("OBJECTID"), marker)
        return list(unique_markers.values())

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

class PipelineOrchestrator:
    """Orchestrates the GIS pipeline workflow."""
    def __init__(self):
        """Initializes services."""
        self.geocoder = GeocoderService()
        self.marker_service = ReferenceMarkerService()

    def parse_coordinate_query(self, query: str) -> Optional[Tuple[Dict[str, float], int]]:
        """
        Parses a query string into a point (x, y) and SR.
        Supports:
        - "x, y" (assumed SR: 26918 - UTM 18N)
        - "lat, lon" (assumed SR: 4326 - WGS84)
        """
        # Improved regex to only match if the string *is* primarily coordinates
        match = re.fullmatch(r"(-?\d+\.?\d*)\s*[, ]\s*(-?\d+\.?\d*)", query.strip())
        if not match:
            return None
        
        v1 = float(match.group(1))
        v2 = float(match.group(2))
        
        # Very simple heuristic:
        # Lat/Lon are small (roughly -90 to 90 for lat, -180 to 180 for lon)
        # UTM/State Plane are large (hundreds of thousands)
        
        if abs(v1) <= 180 and abs(v2) <= 180:
            # Assume Lat/Lon (4326)
            # ArcGIS uses lon, lat
            return {"x": v2, "y": v1}, 4326 
        else:
            # Assume Projected (26918)
            return {"x": v1, "y": v2}, 26918

    def run(self, query: str, choice_index: Optional[int] = None) -> Optional[List[Dict]]:
        """
        Runs the full GIS pipeline for a given query (address or coordinates).
        """
        # 1. Check if coordinate
        coord_point_sr = self.parse_coordinate_query(query)
        if coord_point_sr:
            point, sr = coord_point_sr
            print(f"Detected coordinates: {point}, SR: {sr}")
            return self.marker_service.find_nearby(point, sr, radius_miles=0.5)

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
        return self.marker_service.find_nearby(point, sr, radius_miles=0.5)
