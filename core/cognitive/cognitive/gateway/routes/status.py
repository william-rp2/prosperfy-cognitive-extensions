"""
gateway/routes/status.py — GET /v1/status (autenticado).

Retorna informações do tenant/actor resolvido e saúde básica do sistema.
"""

from fastapi import APIRouter

from ...contracts.gateway import StatusResponse
from ..deps import ActorContextDep

router = APIRouter()

VERSION = "0.1.0-sprint-0.1"


@router.get("/v1/status", tags=["gateway"])
async def get_status(ctx: ActorContextDep) -> StatusResponse:
    """
    Retorna status do Cognitive Gateway com contexto do tenant/actor resolvido.

    Requer headers: Authorization, X-Tenant-Id, X-Actor-Id.
    """
    return StatusResponse(
        healthy=True,
        version=VERSION,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.actor_id,
        correlation_id=ctx.correlation_id,
    )
