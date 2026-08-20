"""
tests/unit/test_known_gaps_execution_wiring.py — Sprint 0.3, gaps found by
Subagent C (adapters/registry/contracts) and closed by the Lead Dev in
execution/orchestrator.py + gateway/app.py (outside Subagent C's ownership).

Originally these two tests were marked xfail(strict=True) as gap markers:

1) ResourceResolver existed and was instantiated in gateway/app.py but
   ExecutionOrchestrator never received/called it — params["resource"]
   (lógico, ex. "prosperfy-main") ia cru para o adapter em vez de resolvido
   para parâmetros concretos (ex. host) ANTES da chamada — violava
   ADR-V2-002 §3.

2) idempotency_key era aceito no contrato e propagado até
   ExecutionOrchestrator.execute(), mas nunca usado — duas execuções com a
   mesma key re-executavam a capability integralmente.

Ambos corrigidos: ExecutionOrchestrator agora aceita resource_resolver
(injetado em gateway/app.py) e mantém um cache in-process por
(tenant_id, capability_id, idempotency_key) — só para execuções COMPLETED.
"""

from __future__ import annotations

from typing import Any

import pytest

from cognitive.audit.writer import InMemoryAuditWriter
from cognitive.contracts.tenancy import ActorContext, CapabilityGrant
from cognitive.execution.orchestrator import ExecutionOrchestrator
from cognitive.execution.resource_resolver import InMemoryResourceResolver
from cognitive.policy.engine import PolicyEngine
from cognitive.registry.registry import InMemoryCapabilityRegistry
from cognitive.telemetry.recorder import InMemoryTelemetryRecorder


class _RecordingAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def invoke_tool(
        self, tool_name: str, arguments: dict[str, Any], tenant_id: str, correlation_id: str,
    ) -> dict[str, Any]:
        self.calls.append((tool_name, dict(arguments)))
        return {"success": True, "data": {"tool": tool_name}}

    async def health(self) -> bool:
        return True


def _ctx() -> ActorContext:
    return ActorContext(
        tenant_id="tenant-gap",
        actor_id="actor-gap",
        correlation_id="corr-gap",
        credential_ref="ref-gap",
        profile="owner-core",
    )


def _build_orchestrator(adapter, *, with_resource_resolver: bool = True):
    registry = InMemoryCapabilityRegistry()
    registry.load_from_yaml()
    registry.register_grant(CapabilityGrant(
        tenant_id="tenant-gap", profile="owner-core", capability_id="infra.inspect",
    ))

    resolver = None
    if with_resource_resolver:
        resolver = InMemoryResourceResolver()
        resolver.register(
            "tenant-gap", "prosperfy-main",
            {"host": "resolved-vps.prosperfy.com.br", "type": "vps"},
        )

    return ExecutionOrchestrator(
        registry=registry,
        policy_engine=PolicyEngine(),
        skills_adapter=adapter,
        audit_writer=InMemoryAuditWriter(),
        telemetry_recorder=InMemoryTelemetryRecorder(),
        resource_resolver=resolver,
    )


@pytest.mark.asyncio
async def test_resource_is_resolved_to_concrete_params_before_adapter():
    """ADR-V2-002 §3: adapter recebe 'host' resolvido, nunca 'resource' cru."""
    adapter = _RecordingAdapter()
    orchestrator = _build_orchestrator(adapter)

    result = await orchestrator.execute(
        ctx=_ctx(),
        capability_id="infra.inspect",
        params={"resource": "prosperfy-main"},
    )

    assert result.status.value == "completed"
    panorama_call = next(a for name, a in adapter.calls if name == "prosperfy_vps_panorama")
    assert "resource" not in panorama_call
    assert "_resolved_resource" not in panorama_call
    assert panorama_call.get("host") == "resolved-vps.prosperfy.com.br"


@pytest.mark.asyncio
async def test_resource_metadata_type_not_forwarded_to_mcp_tools():
    """
    Sprint 0.3 HOTFIX (erro de protocolo MCP no live gate): resolved_params
    carrega 'type' (metadado do recurso, espelho da coluna resource_type),
    que NÃO é argumento das tools VPS do ProsperfySkill. Servidor FastMCP
    rejeita chave fora do schema ('Unexpected keyword argument') com
    CallToolResult.isError=True — virando o 'erro de protocolo MCP' do
    adapter. O orquestrador deve filtrar metadados antes de chamar o adapter.
    """
    adapter = _RecordingAdapter()
    orchestrator = _build_orchestrator(adapter)

    result = await orchestrator.execute(
        ctx=_ctx(),
        capability_id="infra.inspect",
        params={"resource": "prosperfy-main"},
    )

    assert result.status.value == "completed"
    assert len(adapter.calls) == 3
    for tool_name, call_args in adapter.calls:
        assert tool_name in (
            "prosperfy_vps_panorama",
            "prosperfy_vps_listar_containers",
            "prosperfy_vps_verificar_portas",
        )
        assert "type" not in call_args
        assert "resource" not in call_args
        assert "_resolved_resource" not in call_args
        assert call_args == {"host": "resolved-vps.prosperfy.com.br"}


@pytest.mark.asyncio
async def test_unknown_resource_fails_closed_without_calling_adapter():
    """Resource não cadastrado para o tenant -> FAILED, adapter nunca chamado."""
    adapter = _RecordingAdapter()
    orchestrator = _build_orchestrator(adapter)

    result = await orchestrator.execute(
        ctx=_ctx(),
        capability_id="infra.inspect",
        params={"resource": "not-registered"},
    )

    assert result.status.value == "failed"
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_no_resolver_configured_raises_for_args_from_resource_tool():
    """Sem resource_resolver, uma tool args_from_resource=True não deve silenciosamente
    receber params crus — deve falhar de forma explícita (fail closed), não vazar 'resource'."""
    adapter = _RecordingAdapter()
    orchestrator = _build_orchestrator(adapter, with_resource_resolver=False)

    result = await orchestrator.execute(
        ctx=_ctx(),
        capability_id="infra.inspect",
        params={"resource": "prosperfy-main"},
    )

    assert result.status.value == "failed"
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_duplicate_idempotency_key_does_not_reexecute():
    """idempotency_behavior: return_cached (infra.inspect.yaml) — segunda chamada
    com a mesma key não deve re-invocar o adapter."""
    adapter = _RecordingAdapter()
    orchestrator = _build_orchestrator(adapter)

    first = await orchestrator.execute(
        ctx=_ctx(),
        capability_id="infra.inspect",
        params={"resource": "prosperfy-main"},
        idempotency_key="dedupe-key-001",
    )
    calls_after_first = len(adapter.calls)
    assert calls_after_first > 0

    second = await orchestrator.execute(
        ctx=_ctx(),
        capability_id="infra.inspect",
        params={"resource": "prosperfy-main"},
        idempotency_key="dedupe-key-001",
    )

    assert first.status.value == "completed"
    assert second.status.value == "completed"
    assert len(adapter.calls) == calls_after_first
    assert second.execution_id == first.execution_id


@pytest.mark.asyncio
async def test_different_idempotency_key_does_reexecute():
    """Chaves diferentes não compartilham cache — execução normal para cada uma."""
    adapter = _RecordingAdapter()
    orchestrator = _build_orchestrator(adapter)

    first = await orchestrator.execute(
        ctx=_ctx(), capability_id="infra.inspect",
        params={"resource": "prosperfy-main"}, idempotency_key="key-a",
    )
    second = await orchestrator.execute(
        ctx=_ctx(), capability_id="infra.inspect",
        params={"resource": "prosperfy-main"}, idempotency_key="key-b",
    )

    assert first.execution_id != second.execution_id
    assert len(adapter.calls) == 6  # 3 tools x 2 execuções independentes


@pytest.mark.asyncio
async def test_no_idempotency_key_never_cached():
    """Sem idempotency_key, cada chamada re-executa normalmente (comportamento pré-Sprint 0.3)."""
    adapter = _RecordingAdapter()
    orchestrator = _build_orchestrator(adapter)

    first = await orchestrator.execute(
        ctx=_ctx(), capability_id="infra.inspect", params={"resource": "prosperfy-main"},
    )
    second = await orchestrator.execute(
        ctx=_ctx(), capability_id="infra.inspect", params={"resource": "prosperfy-main"},
    )

    assert first.execution_id != second.execution_id
    assert len(adapter.calls) == 6
