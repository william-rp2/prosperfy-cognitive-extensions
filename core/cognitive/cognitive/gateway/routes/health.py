"""
gateway/routes/health.py — GET /health (público, sem autenticação).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter

from ..metadata import api_version, deployment_environment, service_name

router = APIRouter()


@dataclass
class HealthResponse:
    status: str
    service: str
    version: str
    environment: str


@router.get(
    "/health",
    tags=["system"],
    response_model=HealthResponse,
    summary="Public health check",
    description="Lightweight liveness probe. Does not require auth or database.",
)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=service_name(),
        version=api_version(),
        environment=deployment_environment(),
    )
