"""
gateway/routes/capabilities.py — Rotas de capability do Cognitive Gateway.

POST /v1/capabilities/{capability_id}/execute — capability.execute
GET  /v1/capabilities/{capability_id}          — capability.describe
GET  /v1/data/query          → stub 501 (Fase 1)
GET  /v1/tasks/manage        → stub 501 (Fase 1)
GET  /v1/knowledge/search    → stub 501 (Fase 2)
GET  /v1/workflow/execute    → stub 501 (Fase 3)
"""

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from ...contracts.gateway import (
    CapabilityDescribeResponse,
    CapabilityExecuteRequest,
    CapabilityExecuteResponse,
)
from ..deps import ActorContextDep

router = APIRouter()


@router.post(
    "/v1/capabilities/{capability_id}/execute",
    response_model=CapabilityExecuteResponse,
    tags=["capabilities"],
)
async def execute_capability(
    capability_id: str,
    body: CapabilityExecuteRequest,
    ctx: ActorContextDep,
    request: Request,
) -> CapabilityExecuteResponse:
    """
    capability.execute — Executa uma capability via Cognitive Gateway.

    Ordem obrigatória (ADR-V2-004):
    AUTH → TENANT/ACTOR → CAPABILITY → GRANT → POLICY → EXECUTOR → ADAPTER

    Headers obrigatórios: Authorization, X-Tenant-Id, X-Actor-Id.
    """
    orchestrator = request.app.state.orchestrator
    return await orchestrator.execute(
        ctx=ctx,
        capability_id=capability_id,
        params=body.params,
        idempotency_key=body.idempotency_key,
    )


@router.get(
    "/v1/capabilities/{capability_id}",
    response_model=CapabilityDescribeResponse,
    tags=["capabilities"],
)
async def describe_capability(
    capability_id: str,
    ctx: ActorContextDep,
    request: Request,
) -> CapabilityDescribeResponse:
    """
    capability.describe — Descreve uma capability (sem executar).
    """
    registry = request.app.state.registry
    cap = registry.get(capability_id)
    if cap is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Capability '{capability_id}' não encontrada",
        )
    return CapabilityDescribeResponse(
        id=cap.id,
        version=cap.version,
        domain=str(cap.domain),
        description=cap.description,
        default_policy=cap.default_policy,
        required_scopes=cap.required_scopes,
        input_schema=cap.input_schema,
    )


# ─── Stubs para fases futuras ────────────────────────────────────────────

@router.get("/v1/data/query", tags=["stub"], include_in_schema=True)
async def data_query_stub(ctx: ActorContextDep) -> JSONResponse:
    """data.query — Fase 1 (Projects/Tasks). Não implementado."""
    raise HTTPException(status_code=501, detail="data.query disponível na Fase 1")


@router.get("/v1/knowledge/search", tags=["stub"], include_in_schema=True)
async def knowledge_search_stub(ctx: ActorContextDep) -> JSONResponse:
    """knowledge.search — Fase 2 (RAG). Não implementado."""
    raise HTTPException(status_code=501, detail="knowledge.search disponível na Fase 2")


@router.get("/v1/workflow/execute", tags=["stub"], include_in_schema=True)
async def workflow_execute_stub(ctx: ActorContextDep) -> JSONResponse:
    """workflow.execute — Fase 3 (Workflow Engine). Não implementado."""
    raise HTTPException(status_code=501, detail="workflow.execute disponível na Fase 3")
