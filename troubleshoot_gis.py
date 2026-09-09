import requests
import json

# Endpoints
GEOCODER_URL = "https://gisservices.its.ny.gov/arcgis/rest/services/Locators/Street_and_Address_Composite/GeocodeServer/findAddressCandidates"
MAPSERVER_URL = "https://gis.dot.ny.gov/hostingny/rest/services/Ref_Marker/MapServer"
IDENTIFY_URL = f"{MAPSERVER_URL}/identify"

def get_geocoded_point(address):
    params = {
        "SingleLine": address,
        "f": "json",
        "outSR": "" # Let's see what it returns by default
    }
    response = requests.get(GEOCODER_URL, params=params)
    data = response.json()
    if not data.get("candidates"):
        print(f"No candidates found for: {address}")
        return None
    
    # Take first candidate
    candidate = data["candidates"][0]
    sr = data.get("spatialReference", {}).get("wkid")
    return candidate["location"], sr

def get_mapserver_sr():
    params = {"f": "json"}
    response = requests.get(MAPSERVER_URL, params=params)
    data = response.json()
    return data.get("spatialReference", {}).get("wkid")

def construct_identify_url(point, sr_point, sr_map):
    print(f"Point SR: {sr_point}, MapServer SR: {sr_map}")
    
    # Basic parameter setup
    # Note: Using a dummy mapExtent around the point for now
    buffer = 1000 
    map_extent = f"{point['x']-buffer},{point['y']-buffer},{point['x']+buffer},{point['y']+buffer}"
    
    params = {
        "f": "json",
        "geometryType": "esriGeometryPoint",
        "geometry": f"{point['x']},{point['y']}",
        "sr": sr_point,
        "tolerance": 10,
        "mapExtent": map_extent,
        "imageDisplay": "800,600,96",
        "returnGeometry": "true",
        "layers": "all"
    }
    
    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
    return f"{IDENTIFY_URL}?{query_string}"

if __name__ == "__main__":
    address = "5700 Route 44 55, Kerhonkson, NY, 12446"
    
    # 1. Get Point
    point, sr_point = get_geocoded_point(address)
    if not point: exit()
    print(f"Geocoded Point: {point}")
    
    # 2. Get MapServer SR
    sr_map = get_mapserver_sr()
    print(f"MapServer SR: {sr_map}")
    
    # 3. Construct URL
    url = construct_identify_url(point, sr_point, sr_map)
    print(f"\nGenerated Identify URL:\n{url}")
    
    # 4. Test URL
    print("\nTesting URL...")
    resp = requests.get(url)
    print(json.dumps(resp.json(), indent=2))
