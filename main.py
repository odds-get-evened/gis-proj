from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from gis_pipeline import PipelineOrchestrator
from typing import Optional, Dict
import os
import signal
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Allow CORS so Electron can communicate with this local API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

orchestrator = PipelineOrchestrator()

class GeocodeRequest(BaseModel):
    magic_key: str

class IdentifyRequest(BaseModel):
    point: Dict[str, float]
    sr: int
    radius_miles: float = 0.5

@app.get("/suggestions")
def get_suggestions(text: str):
    return orchestrator.geocoder.suggest(text)

@app.post("/geocode")
def geocode_location(request: GeocodeRequest):
    return orchestrator.geocoder.geocode(request.magic_key)

@app.post("/identify")
def identify_marker(request: IdentifyRequest):
    results = orchestrator.marker_service.identify(request.point, request.sr, request.radius_miles)
    
    # Deduplicate based on OBJECTID and keep both attributes and geometry
    unique_results = {}
    for r in results.get('results', []):
        attrs = r.get('attributes', {})
        obj_id = attrs.get('OBJECTID')
        if obj_id not in unique_results:
            unique_results[obj_id] = {
                "attributes": attrs,
                "geometry": r.get('geometry')
            }
            
    return list(unique_results.values())

@app.post("/shutdown")
def shutdown():
    # Send SIGINT to self to trigger graceful uvicorn shutdown
    os.kill(os.getpid(), signal.SIGINT)
    return {"status": "shutting down"}
