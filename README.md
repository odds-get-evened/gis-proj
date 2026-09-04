# NYS GIS Reference Marker Lookup Tool

This tool provides a user-friendly interface for querying NYSDOT reference markers based on location.

## Features
- **Search by Address:** Enter a free-form address to get location suggestions, then select a candidate to view nearby reference markers.
- **Search by Coordinates:** Directly enter coordinates (Northing/Easting or Latitude/Longitude) to bypass geocoding and immediately view nearby reference markers.

## GIS Pipeline Flow
The tool processes search queries through one of two workflows:

1.  **Address Flow:** 
    - Input (Address) -> Suggest (Geocoder) -> Geocode (Geocoder) -> Identify (MapServer).
2.  **Coordinate Flow:** 
    - Input (Coordinates) -> Identify (MapServer).

### API Endpoints
- **Geocoder Suggestions:** `https://nysgeohub.ny.gov/arcgis/rest/services/Geocoder/NYS_Geocoder/GeocodeServer/suggest`
- **Geocoder Candidates:** `https://nysgeohub.ny.gov/arcgis/rest/services/Geocoder/NYS_Geocoder/GeocodeServer/findAddressCandidates`
- **Reference Marker Identification:** `https://gis.dot.ny.gov/hostingny/rest/services/Ref_Marker/MapServer/identify`

## How to Use the GUI
1.  **Launch the Application:** Run `gui_app.py` using Python.
2.  **Enter Query:** Type your address or coordinates into the "Address" field.
    - **Address:** E.g., "5700 Route 44 55, Kerhonkson, NY, 12446"
    - **Coordinates (Projected):** E.g., "560638, 4621699" (Assumed UTM 18N)
    - **Coordinates (Lat/Lon):** E.g., "41.7, -74.3" (Assumed WGS84)
3.  **Search:** Press `Enter` or click the "Search" button.
4.  **Select Location:** If an address was searched, a list of location suggestions will appear. Select a suggestion from the list to populate the results.
5.  **View Results:** The table will display attribute information for nearby reference markers, along with the Latitude and Longitude of the searched point.
