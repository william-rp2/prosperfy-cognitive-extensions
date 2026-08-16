"""
gateway/routes/health.py — GET /health (público, sem autenticação).
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health", tags=["system"])
async def health() -> JSONResponse:
    """Healthcheck público do Cognitive Gateway."""
    return JSONResponse({"status": "ok", "service": "prosperfy-cognitive"})
