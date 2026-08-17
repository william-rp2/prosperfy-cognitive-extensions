"""
gateway/routes/status.py — GET /v1/status (autenticado).
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Request

from ...contracts.gateway import StatusResponse
from ..deps import AUTH_HEADER_DOCS, ActorContextDep
from ..metadata import api_version, deployment_environment
from ...config.runtime import cognitive_mode

router = APIRouter()


@router.get(
    "/v1/status",
    tags=["gateway"],
    response_model=StatusResponse,
    summary="Authenticated gateway status",
    description=(
        "Operational status for the resolved tenant/actor. "
        "Requires Authorization, X-Tenant-Id, and X-Actor-Id headers."
    ),
    openapi_extra={"parameters": AUTH_HEADER_DOCS},
)
async def get_status(ctx: ActorContextDep, request: Request) -> StatusResponse:
    registry = request.app.state.registry
    db_configured = bool(
        os.getenv("COGNITIVE_DB_URL") or os.getenv("COGNITIVE_DB_ADMIN_URL")
    )
    return StatusResponse(
        healthy=True,
        version=api_version(),
        environment=deployment_environment(),
        runtime_mode=cognitive_mode(),
        db_configured=db_configured,
        registry_loaded=registry is not None,
        capabilities_count=len(registry.list_all()) if registry else 0,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.actor_id,
        correlation_id=ctx.correlation_id,
    )
