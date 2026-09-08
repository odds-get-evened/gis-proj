# NYS GIS Reference Marker Lookup Tool

This tool provides a user-friendly interface for querying NYSDOT reference markers based on locations. It is available in two distinct architectures: a modern, interactive **Electron + FastAPI Dashboard**, and a legacy standalone **Tkinter Widget**.

---

## Architectural Options

### Option 1: Modern GIS Dashboard (Electron + FastAPI) - *Recommended*
A decoupled, high-performance web-native desktop app. It leverages a Python FastAPI backend for GIS computations and a JavaScript Electron frontend to host a fully interactive **ArcGIS Map** side-by-side with your attribute details.

### Option 2: Legacy Standalone Widget (Tkinter)
A lightweight, classic single-file Python Tkinter desktop GUI. Ideal for offline environments or systems where Node.js/npm is not installed.

---

## Features (Modern GIS Dashboard)
- **Interactive ArcGIS Map:** Embedded, fully interactive vector map pane displaying search targets and results.
- **Bi-Directional Highlight & Sync:**
  - Clicking any reference marker pin (Emerald Green) on the map instantly highlights and **smoothly scrolls to its matching row** in the details table.
  - Clicking any row in the details table automatically **pans and focuses the map** on that specific marker pin.
- **Auto-Zoom to Fit:** The map automatically calculates bounds and adjusts zoom levels so that your search target and all surrounding reference markers are perfectly framed.
- **Deep Metadata Modal:** Click "Details" on any row to open a blurred overlay modal showing the complete list of attribute fields for that reference marker.
- **Graceful Clean Shutdown:** Closing the Electron window automatically triggers an API shutdown request to the local FastAPI server, leaving no background Python processes orphaned.

---

## How to Set Up & Use

### Option 1: Modern GIS Dashboard (Electron + FastAPI)

#### Prerequisites
- **Python 3.12+**
- **Node.js & npm** (LTS recommended)

#### 1. Setup the Backend
From the root project directory, install the FastAPI backend dependencies:
```bash
pip install fastapi uvicorn requests pydantic
```

#### 2. Setup the Frontend
Navigate into the `gis-frontend` directory and install the Node/Electron dependencies:
```bash
cd gis-frontend
npm install
npm install concurrently --save-dev
```

#### 3. Run the Application
Start both the FastAPI backend and the Electron UI simultaneously with a single command from inside the `gis-frontend` folder:
```bash
npm run dev
```
*(The UI will open, automatically establish a robust connection with retry handling, and the backend server will shut down completely when you close the UI window.)*

---

### Option 2: Legacy Standalone Widget (Tkinter GUI)

#### Prerequisites
- **Python 3.12+** with `tkinter` (usually bundled by default)
- Install requests:
```bash
pip install requests
```

#### 1. Run the Application
Run the classic UI script directly from the root directory:
```bash
python gui_app.py
```

#### 2. Usage Instructions
1.  **Enter Query:** Type your address or coordinates into the "Address" field.
    - **Address:** E.g., "5700 Route 44 55, Kerhonkson, NY, 12446"
    - **Coordinates (Projected):** E.g., "560638, 4621699" (Assumed UTM 18N)
    - **Coordinates (Lat/Lon):** E.g., "41.7, -74.3" (Assumed WGS84)
2.  **Search:** Press `Enter` or click the "Search" button.
3.  **Select Location:** If an address was searched, select a suggestion from the populated list to display the nearest reference markers.

---

## Under-the-Hood GIS Pipeline Flow
Both frontends pipe queries through the core orchestrator engine in `gis_pipeline.py` using one of two workflows:

1.  **Address Flow:** 
    - Input (Address) -> Suggest (Geocoder) -> Geocode (Geocoder) -> Identify (MapServer).
2.  **Coordinate Flow:** 
    - Input (Coordinates) -> Identify (MapServer).

### Native API Endpoints Queried:
- **Geocoder Suggestions:** `https://nysgeohub.ny.gov/arcgis/rest/services/Geocoder/NYS_Geocoder/GeocodeServer/suggest`
- **Geocoder Candidates:** `https://nysgeohub.ny.gov/arcgis/rest/services/Geocoder/NYS_Geocoder/GeocodeServer/findAddressCandidates`
- **Reference Marker Identification:** `https://gis.dot.ny.gov/hostingny/rest/services/Ref_Marker/MapServer/identify`
