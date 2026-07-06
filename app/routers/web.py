import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(tags=["Web UI"])


@router.get("/")
def serve_dashboard():
    """Serves the main interactive simulator and schedule dashboard."""
    static_file = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
    if not os.path.exists(static_file):
        raise HTTPException(status_code=404, detail="Dashboard UI file not found.")
    return FileResponse(static_file)
