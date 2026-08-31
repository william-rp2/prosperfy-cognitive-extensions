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
from ...contracts.tenancy import ActorContext
from ...policy.finance_acl import FinanceChannelContext
from ..deps import AUTH_HEADER_DOCS, ActorContextDep

router = APIRouter()


def _accept_channel_context(
    ctx: ActorContext,
    body: CapabilityExecuteRequest,
) -> FinanceChannelContext | None:
    """
    Converte o envelope de canal do body em FinanceChannelContext — ou o descarta.

    F2B/D11. Dois gates, ambos fail-closed:

    1. FONTE: só `body.channel` (campo tipado de topo) é lido. `body.params`
       nunca é inspecionado, então um `channel` injetado dentro de
       params/arguments — o caminho por onde passa qualquer coisa derivada de
       texto interpretado por LLM — é simplesmente ignorado.

    2. IDENTIDADE: o envelope só é aceito de um caller com service identity
       de transporte AUTENTICADA. O mecanismo é o mesmo que o gateway já usa
       para autenticar chamadas de serviço: Bearer credential -> Identity
       Resolver (tenancy/identity_resolver.py), invocado por
       gateway/deps.get_actor_context. `credential_ref` é o sha256 truncado
       dessa credential e SÓ é preenchido nesse caminho — um ActorContext
       montado por qualquer outra via chega com credential_ref vazio.

    Quando o envelope é descartado, isso acontece em SILÊNCIO (não é um erro
    ao caller): a ACL de finance então avalia sem canal e nega com
    DENY_NO_CHANNEL. Rejeitar com erro distinto contaria ao caller que o
    canal existe — é exatamente o canal lateral que finance_acl.py evita ao
    usar uma mensagem única para todo DENY.
    """
    if body.channel is None:
        return None
    if not ctx.credential_ref:
        # Sem prova de service identity: descarta (nunca 4xx específico).
        return None
    return FinanceChannelContext(
        chat_id=body.channel.chat_id,
        is_group=body.channel.is_group,
        transport_principal=body.channel.transport_principal,
        incoming_message_id=body.channel.incoming_message_id,
        reply_to_message_id=body.channel.reply_to_message_id,
    )


@router.get(
    "/v1/capabilities",
    response_model=list[CapabilityDescribeResponse],
    tags=["capabilities"],
    summary="List registered capabilities",
    openapi_extra={"parameters": AUTH_HEADER_DOCS},
)
async def list_capabilities(
    ctx: ActorContextDep,
    request: Request,
) -> list[CapabilityDescribeResponse]:
    """Lista capabilities conhecidas pelo registry YAML."""
    registry = request.app.state.registry
    return [
        CapabilityDescribeResponse(
            id=cap.id,
            version=cap.version,
            domain=str(cap.domain),
            description=cap.description,
            default_policy=cap.default_policy,
            required_scopes=cap.required_scopes,
            input_schema=cap.input_schema,
        )
        for cap in registry.list_all()
    ]


@router.post(
    "/v1/capabilities/{capability_id}/execute",
    response_model=CapabilityExecuteResponse,
    tags=["capabilities"],
    openapi_extra={"parameters": AUTH_HEADER_DOCS},
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
        channel=_accept_channel_context(ctx, body),
    )


@router.get(
    "/v1/capabilities/{capability_id}",
    response_model=CapabilityDescribeResponse,
    tags=["capabilities"],
    openapi_extra={"parameters": AUTH_HEADER_DOCS},
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
