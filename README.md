# NYS GIS Reference Marker Lookup Tool

This tool provides a user-friendly interface for querying NYSDOT reference markers based on locations. It is a desktop dashboard built with an **Electron** frontend and a Python **FastAPI** backend.

---

![App screenshot](screenshot.png)

---

## Architecture
A decoupled, web-native desktop app. A Python FastAPI backend handles the GIS lookups, and an Electron frontend hosts a fully interactive **ArcGIS Map** side-by-side with your attribute details.

---

## Features
- **Interactive ArcGIS Map:** Embedded, fully interactive vector map pane displaying search targets and results.
- **Bi-Directional Highlight & Sync:**
  - Clicking any reference marker pin (Emerald Green) on the map instantly highlights and **smoothly scrolls to its matching row** in the details table.
  - Clicking any row in the details table automatically **pans and focuses the map** on that specific marker pin.
- **Auto-Zoom to Fit:** The map automatically calculates bounds and adjusts zoom levels so that your search target and all surrounding reference markers are perfectly framed.
- **Deep Metadata Modal:** Click "Details" on any row to open a blurred overlay modal showing the complete list of attribute fields for that reference marker.
- **Graceful Clean Shutdown:** Closing the Electron window automatically triggers an API shutdown request to the local FastAPI server, leaving no background Python processes orphaned.

---

## How to Set Up & Use

### Prerequisites
- **Python 3.12+**
- **Node.js & npm** (LTS recommended)

### 1. Setup the Backend
From the root project directory, install the FastAPI backend dependencies:
```bash
pip install fastapi uvicorn requests pydantic
```

### 2. Setup the Frontend
Navigate into the `gis-frontend` directory and install the Node/Electron dependencies:
```bash
cd gis-frontend
npm install
npm install concurrently --save-dev
```

### 3. Run the Application
Start both the FastAPI backend and the Electron UI simultaneously with a single command from inside the `gis-frontend` folder:
```bash
npm run dev
```
*(The UI will open, automatically establish a robust connection with retry handling, and the backend server will shut down completely when you close the UI window.)*

---

## Under-the-Hood GIS Pipeline Flow
The backend pipes queries through the core orchestrator engine in `gis_pipeline.py` using one of two workflows:

1.  **Address Flow:** 
    - Input (Address) -> Suggest (Geocoder) -> Geocode (Geocoder) -> Identify (MapServer).
2.  **Coordinate Flow:** 
    - Input (Coordinates) -> Identify (MapServer).

### Native API Endpoints Queried:
- **Geocoder Suggestions:** `https://nysgeohub.ny.gov/arcgis/rest/services/Geocoder/NYS_Geocoder/GeocodeServer/suggest`
- **Geocoder Candidates:** `https://nysgeohub.ny.gov/arcgis/rest/services/Geocoder/NYS_Geocoder/GeocodeServer/findAddressCandidates`
- **Reference Marker Identification:** `https://gis.dot.ny.gov/hostingny/rest/services/Ref_Marker/MapServer/identify`
