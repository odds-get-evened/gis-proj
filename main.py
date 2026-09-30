import logging
import os
import signal
from typing import Dict, Optional

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from gis_pipeline import ArcGISError, PipelineOrchestrator

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


class BackendServer:
    """Runs the FastAPI app in-process with uvicorn and supports a clean programmatic stop.

    Used when the backend is started directly (``python main.py``) or as the
    PyInstaller-compiled ``gis-backend`` executable bundled with the installers.
    """

    def __init__(self, application: FastAPI, host: str = HOST, port: int = PORT):
        config = uvicorn.Config(application, host=host, port=port, log_level="info")
        self._server = uvicorn.Server(config)

    def run(self) -> None:
        """Blocks, serving requests until stop() is called or the process is interrupted."""
        logger.info(f"Starting GIS backend on http://{HOST}:{PORT}")
        self._server.run()

    def stop(self) -> None:
        """Asks uvicorn to finish in-flight requests and exit."""
        self._server.should_exit = True


# Set only when this module is run as the entry point (see bottom of file)
backend_server: Optional[BackendServer] = None

class GeocodeRequest(BaseModel):
    magic_key: str

class IdentifyRequest(BaseModel):
    point: Dict[str, float]
    sr: int
    radius_miles: float = 0.5

@app.get("/health")
def health():
    """Readiness probe polled by the Electron app before it opens its window."""
    return {"status": "ok"}

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

@app.post("/shutdown")
def shutdown():
    if backend_server is not None:
        backend_server.stop()
    else:
        # Started by the uvicorn CLI (npm run dev): SIGINT triggers uvicorn's graceful shutdown
        os.kill(os.getpid(), signal.SIGINT)
    return {"status": "shutting down"}


if __name__ == "__main__":
    backend_server = BackendServer(app)
    backend_server.run()
