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
- **Half-Mile Search Radius:** Searching an address or clicking the map shows every reference marker within 0.5 miles of that spot.
- **Bi-Directional Highlight & Sync:**
  - Clicking any reference marker pin (Emerald Green) on the map instantly highlights and **smoothly scrolls to its matching row** in the details table.
  - Clicking any row in the details table automatically **pans and focuses the map** on that specific marker pin.
- **Auto-Zoom to Fit:** The map automatically calculates bounds and adjusts zoom levels so that your search target and all surrounding reference markers are perfectly framed.
- **Deep Metadata Modal:** Click "Details" on any row to open a blurred overlay modal showing the complete list of attribute fields for that reference marker.
- **Graceful Clean Shutdown:** Closing the Electron window automatically triggers an API shutdown request to the local FastAPI server, leaving no background Python processes orphaned.

---

## Installing the App

1. Go to the repository's **Releases** page on GitHub and open the latest release.
2. Download the installer for your computer:
   - **Windows:** the `.exe` file. Run it and follow the prompts.
   - **macOS:** the `.dmg` file. Open it and drag **NYS GIS Lookup** into Applications.
   - **Linux:** the `.AppImage` (make it executable, then run it) or the `.deb` (install with `sudo apt install ./<file>.deb`).
3. Launch **NYS GIS Lookup**. It may take a few seconds to open while its lookup service starts in the background.

An internet connection is required, because the app looks up addresses and reference markers from New York State's online GIS services.

**macOS note:** the app isn't signed with an Apple developer certificate yet, so macOS may block it the first time. Right-click the app in Applications, choose **Open**, then confirm **Open**.

### Troubleshooting

- **"NYS GIS Lookup could not start":** the background lookup service failed to start. The message shows the location of `backend.log`, which records what went wrong. The most common cause is another program already using port 8000; close it and try again.
- **"...is taking too long to respond":** a New York State GIS service is slow or overloaded. The app already retried once for you; wait a moment and search again.
- **"Could not reach the...":** the app couldn't connect to a New York State GIS service. Check your internet connection (and any VPN or firewall), then try again.
- **"...reported a problem":** the state service answered with an error. Try again; if it keeps happening, the service may be down for maintenance.
- **"Part of the search timed out, so some markers may be missing":** most of the marker search worked, but part of it was too slow. The markers shown are correct; search again to make sure none are missing.
- **Log file locations:**
  - Windows: `%APPDATA%\nys-gis-frontend\logs\backend.log`
  - macOS: `~/Library/Logs/nys-gis-frontend/backend.log`
  - Linux: `~/.config/nys-gis-frontend/logs/backend.log`

---

## Running from Source (Developers)

### Prerequisites
- **Python 3.12+**
- **Node.js & npm** (LTS recommended)

### 1. Setup the Backend
From the root project directory, install the FastAPI backend dependencies:
```bash
python -m pip install fastapi uvicorn requests pydantic
```

### 2. Setup the Frontend
Navigate into the `gis-frontend` directory and install the Node/Electron dependencies:
```bash
cd gis-frontend
npm install
```

### 3. Run the Application
From inside the `gis-frontend` folder:
```bash
npm run dev
```
The app finds a Python interpreter that has the backend packages installed (it tries `python`, `py` and `python3` on Windows, and `python3` then `python` elsewhere), starts the backend with it, and opens the window once the backend is ready. Backend log messages appear in the same terminal, and the backend shuts down when you close the window. The `uvicorn` command does not need to be on your PATH.

If you have more than one Python installed, point the app at the right one with the `GIS_PYTHON` environment variable:
```bash
# Windows (PowerShell)
$env:GIS_PYTHON = "C:\path\to\python.exe"; npm run dev

# macOS / Linux
GIS_PYTHON=/path/to/python npm run dev
```

You can also run the backend yourself with `python main.py` from the root directory; `npm run dev` detects it and uses it instead of starting its own.

---

## Under-the-Hood GIS Pipeline Flow
The backend pipes queries through the core orchestrator engine in `gis_pipeline.py` using one of two workflows:

1.  **Address Flow:** 
    - Input (Address) -> Suggest (Geocoder) -> Geocode (Geocoder) -> Find Nearby Markers (MapServer query).
2.  **Coordinate Flow:** 
    - Input (Coordinates) -> Find Nearby Markers (MapServer query).

Markers are found with a distance query: the NYSDOT service buffers the location by a true 0.5-mile radius in its own UTM 18N (meter) coordinate system, so the search area is an accurate circle whether the location arrives as lat/lon, UTM or Web Mercator. The service draws the same markers in nine scale-dependent sub-layers; all are queried in parallel and duplicates are removed by `OBJECTID`.

### Native API Endpoints Queried:
- **Geocoder Suggestions:** `https://nysgeohub.ny.gov/arcgis/rest/services/Geocoder/NYS_Geocoder/GeocodeServer/suggest`
- **Geocoder Candidates:** `https://nysgeohub.ny.gov/arcgis/rest/services/Geocoder/NYS_Geocoder/GeocodeServer/findAddressCandidates`
- **Reference Marker Query:** `https://gis.dot.ny.gov/hostingny/rest/services/Ref_Marker/MapServer/<layer 1-9>/query`

### Running the Tests
From the root project directory:
```bash
pip install httpx
python -m unittest discover -s tests -t . -v
```
