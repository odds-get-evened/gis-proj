import argparse
import logging
import sys
import threading
from dataclasses import asdict
from typing import Dict, List

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gis_pipeline import ArcGISError, CoordinateError, PipelineOrchestrator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Must match the address the Electron frontend (main.js and index.html) talks to
HOST = "127.0.0.1"
PORT = 8000

app = FastAPI()

# Allow CORS so Electron can communicate with this local API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Partial-Results"],  # lets the frontend read it
)

orchestrator = PipelineOrchestrator()


@app.exception_handler(ArcGISError)
def handle_arcgis_error(request: Request, error: ArcGISError):
    """Turns NYS service failures into a status code and a message the UI can show."""
    logger.error(f"{request.url.path} failed: {error}")
    return JSONResponse(status_code=error.status_code, content={"detail": error.user_message})


@app.exception_handler(CoordinateError)
def handle_coordinate_error(request: Request, error: CoordinateError):
    """Typed coordinates that can't be used, e.g. outside New York."""
    return JSONResponse(status_code=422, content={"detail": error.user_message})


class BackendServer:
    """Runs the FastAPI app in-process with uvicorn and supports a clean programmatic stop.

    Used when the backend is started directly (``python main.py``) or as the
    PyInstaller-compiled ``gis-backend`` executable bundled with the installers.
    """

    def __init__(self, application: FastAPI, host: str = HOST, port: int = PORT):
        config = uvicorn.Config(application, host=host, port=port, log_level="info")
        self._server = uvicorn.Server(config)

    def run(self, stop_on_stdin_close: bool = False) -> None:
        """Blocks, serving requests until stop() is called or the process is interrupted.

        With stop_on_stdin_close, the server also stops when standard input reaches
        end-of-file. The Electron app starts the backend with a stdin pipe and closes
        it on quit; if Electron crashes, the operating system closes it instead. Only
        the process that started the backend holds that pipe, so no web page or other
        program can shut the backend down.
        """
        if stop_on_stdin_close:
            threading.Thread(target=self._stop_when_stdin_closes, name="stdin-watcher", daemon=True).start()
        logger.info(f"Starting GIS backend on http://{HOST}:{PORT}")
        self._server.run()

    def stop(self) -> None:
        """Asks uvicorn to finish in-flight requests and exit."""
        self._server.should_exit = True

    def _stop_when_stdin_closes(self) -> None:
        if sys.stdin is None:
            logger.warning("No standard input available; the backend will not stop when the app closes")
            return
        try:
            # Blocks until the parent closes the pipe; anything written to it is ignored
            while sys.stdin.buffer.read(1024):
                pass
        except (OSError, ValueError):
            pass  # a broken pipe means the parent is gone, same as end-of-file
        logger.info("The app closed the backend's standard input; shutting down")
        self.stop()



class GeocodeRequest(BaseModel):
    magic_key: str

class SuggestionRef(BaseModel):
    text: str
    magic_key: str

class SuggestionDetailsRequest(BaseModel):
    suggestions: List[SuggestionRef] = Field(..., max_length=25)

class IdentifyRequest(BaseModel):
    point: Dict[str, float]
    sr: int
    radius_miles: float = 0.5

@app.get("/health")
def health():
    """Readiness probe polled by the Electron app before it opens its window."""
    return {"status": "ok"}

@app.get("/search")
def search(text: str):
    """Handles whatever was typed in the search box.

    Coordinates come back as {"type": "coordinates", "point", "sr", "description",
    "display_point"}: point/sr are ready for /identify, and display_point is the same
    location in latitude/longitude (WGS 84) for drawing the pin on the map.

    A reference marker number (complete, or partial while typing, e.g. "44 8601")
    that matches markers comes back as {"type": "markers", "query", "is_complete",
    "total", "is_partial", "markers": [...]}; each marker has the same shape as
    /identify results plus "number" (e.g. "44 8601 1035"). If no marker matches,
    the text is treated as a place name instead.

    Anything else is treated as a place name and comes back as
    {"type": "suggestions", "groups": [{"category", "label", "suggestions": [...]}, ...]},
    grouped by kind of place (addresses, intersections, roads, towns & cities, counties).
    """
    coordinates = orchestrator.coordinate_parser.parse(text)
    if coordinates:
        return {
            "type": "coordinates",
            "point": coordinates.point,
            "sr": coordinates.sr,
            "description": coordinates.description,
            "display_point": coordinates.display_point,
        }
    number = orchestrator.marker_number_parser.parse(text)
    if number:
        matches = orchestrator.marker_service.find_by_number(number)
        if matches.markers:
            return {
                "type": "markers",
                "query": number.display,
                "is_complete": number.is_complete,
                "total": matches.total,
                "is_partial": matches.is_partial,
                "markers": matches.markers,
            }

    groups = orchestrator.geocoder.suggest_grouped(text)
    return {"type": "suggestions", "groups": [asdict(group) for group in groups]}

@app.post("/suggestion-details")
def suggestion_details(request: SuggestionDetailsRequest):
    """Town, county and location for up to 25 suggestions, looked up in parallel.

    The frontend calls this after showing the suggestion list, and fills in each
    line as the answer arrives. Lookups that fail come back with found=false.
    """
    details = orchestrator.geocoder.suggestion_details([s.model_dump() for s in request.suggestions])
    return [asdict(d) for d in details]

@app.get("/suggestions")
def get_suggestions(text: str):
    return orchestrator.geocoder.suggest(text)

@app.post("/geocode")
def geocode_location(request: GeocodeRequest):
    return orchestrator.geocoder.geocode(request.magic_key)

@app.post("/identify")
def identify_marker(request: IdentifyRequest, response: Response):
    """Returns the unique reference markers within radius_miles of the point.

    Sets the X-Partial-Results header when part of the search failed, so the
    list may be incomplete.
    """
    result = orchestrator.marker_service.find_nearby(request.point, request.sr, request.radius_miles)
    if result.is_partial:
        response.headers["X-Partial-Results"] = "true"
    return result.markers

def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NYS GIS Lookup backend")
    parser.add_argument(
        "--stop-on-stdin-close",
        action="store_true",
        help="exit when standard input is closed (used by the Electron app to stop the backend)",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    BackendServer(app).run(stop_on_stdin_close=args.stop_on_stdin_close)
