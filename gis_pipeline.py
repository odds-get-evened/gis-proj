import requests
import re
from typing import List, Dict, Optional, Tuple

class ArcGISClient:
    """Base client for interacting with ArcGIS REST services."""
    def _make_request(self, url: str, params: Dict) -> Dict:
        params["f"] = "json"
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()

class GeocoderService(ArcGISClient):
    """Handles location suggestions and geocoding."""
    SUGGEST_URL = "https://nysgeohub.ny.gov/arcgis/rest/services/Geocoder/NYS_Geocoder/GeocodeServer/suggest"
    FIND_URL = "https://nysgeohub.ny.gov/arcgis/rest/services/Geocoder/NYS_Geocoder/GeocodeServer/findAddressCandidates"

    def suggest(self, text: str, max_suggestions: int = 50) -> List[Dict]:
        """Gets location suggestions for a given text."""
        params = {"text": text, "maxSuggestions": max_suggestions}
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
    """Handles reference marker identification."""
    IDENTIFY_URL = "https://gis.dot.ny.gov/hostingny/rest/services/Ref_Marker/MapServer/identify"

    def identify(self, point: Dict, sr: int, radius_miles: float = 0.5, out_sr: int = 3857) -> Dict:
        """Identifies reference markers near a given point within a radius in miles."""
        # Convert miles to meters (approx) for buffer
        buffer = radius_miles * 1609.34
        map_extent = f"{point['x']-buffer},{point['y']-buffer},{point['x']+buffer},{point['y']+buffer}"
        
        params = {
            "geometryType": "esriGeometryPoint",
            "geometry": f"{point['x']},{point['y']}",
            "sr": sr,
            "outSR": out_sr, # Request geometries in Web Mercator
            "tolerance": buffer, # Use buffer as tolerance as well
            "mapExtent": map_extent,
            "imageDisplay": "800,600,96",
            "returnGeometry": "true",
            "layers": "all"
        }
        return self._make_request(self.IDENTIFY_URL, params)

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

    def run(self, query: str, choice_index: Optional[int] = None) -> Optional[Dict]:
        """
        Runs the full GIS pipeline for a given query (address or coordinates).
        """
        # 1. Check if coordinate
        coord_point_sr = self.parse_coordinate_query(query)
        if coord_point_sr:
            point, sr = coord_point_sr
            print(f"Detected coordinates: {point}, SR: {sr}")
            # Identify
            return self.marker_service.identify(point, sr, radius_miles=0.5)

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

        # 4. Identify
        return self.marker_service.identify(point, sr, radius_miles=0.5)
