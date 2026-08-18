"""
tests/unit/test_known_gaps_execution_wiring.py — Sprint 0.3 Subagent C findings.

Estes testes documentam duas lacunas arquiteturais CONFIRMADAS fora do
ownership deste subagente (execution/orchestrator.py, gateway/routes/) e por
isso NÃO corrigidas aqui — ver "Known issues" no relatório do Subagent C.

Marcados xfail(strict=True): se o Lead/outro subagent corrigir a lacuna, o
teste passa a passar de verdade e o `strict=True` faz a suite FALHAR até que
o marcador `xfail` seja removido — sinal claro de que é hora de atualizar
este arquivo, em vez de a lacuna voltar a ficar invisível silenciosamente.

1) ResourceResolver (execution/resource_resolver.py) existe e é instanciado
   em gateway/app.py (app.state.resource_resolver), mas ExecutionOrchestrator
   nunca o recebe nem chama — `params["resource"]` (lógico, ex.
   "prosperfy-main") é encaminhado cru para o adapter em vez de resolvido
   para parâmetros concretos (ex. host) ANTES da chamada, violando
   ADR-V2-002 §3.

2) `idempotency_key` é aceito no contrato (ExecutionRequest,
   CapabilityExecuteRequest) e propagado até ExecutionOrchestrator.execute(),
   mas o parâmetro nunca é usado dentro do método — duas execuções com a
   mesma idempotency_key re-executam a capability integralmente (sem cache),
   apesar de `infra.inspect.yaml` declarar
   `idempotency_behavior: "return_cached"`.
"""

from __future__ import annotations

from typing import Any

import pytest

from cognitive.audit.writer import InMemoryAuditWriter
from cognitive.contracts.tenancy import ActorContext, CapabilityGrant
from cognitive.execution.orchestrator import ExecutionOrchestrator
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


def _build_orchestrator(adapter):
    registry = InMemoryCapabilityRegistry()
    registry.load_from_yaml()
    registry.register_grant(CapabilityGrant(
        tenant_id="tenant-gap", profile="owner-core", capability_id="infra.inspect",
    ))
    return ExecutionOrchestrator(
        registry=registry,
        policy_engine=PolicyEngine(),
        skills_adapter=adapter,
        audit_writer=InMemoryAuditWriter(),
        telemetry_recorder=InMemoryTelemetryRecorder(),
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "ResourceResolver não está wired em ExecutionOrchestrator (execution/"
        "orchestrator.py) — 'resource' lógico chega cru ao adapter em vez de "
        "'host' resolvido. Fora do ownership do Subagent C (adapters/registry/"
        "contracts). Ver Sprint 0.3 report, item 3."
    ),
)
@pytest.mark.asyncio
async def test_resource_is_resolved_to_concrete_params_before_adapter_KNOWN_GAP():
    adapter = _RecordingAdapter()
    orchestrator = _build_orchestrator(adapter)

    result = await orchestrator.execute(
        ctx=_ctx(),
        capability_id="infra.inspect",
        params={"resource": "prosperfy-main"},
    )

    assert result.status.value == "completed"
    panorama_call = next(a for name, a in adapter.calls if name == "prosperfy_vps_panorama")
    # Comportamento esperado (ADR-V2-002 §3): adapter recebe 'host' resolvido,
    # nunca o 'resource' lógico cru.
    assert "resource" not in panorama_call
    assert "host" in panorama_call


@pytest.mark.xfail(
    strict=True,
    reason=(
        "idempotency_key é aceito no contrato mas ignorado dentro de "
        "ExecutionOrchestrator.execute() — nenhum cache/dedup implementado. "
        "Fora do ownership do Subagent C (execution/orchestrator.py). "
        "Ver Sprint 0.3 report, item 4."
    ),
)
@pytest.mark.asyncio
async def test_duplicate_idempotency_key_does_not_reexecute_KNOWN_GAP():
    adapter = _RecordingAdapter()
    orchestrator = _build_orchestrator(adapter)

    first = await orchestrator.execute(
        ctx=_ctx(),
        capability_id="infra.inspect",
        params={"resource": "prosperfy-main"},
        idempotency_key="dedupe-key-001",
    )
    calls_after_first = len(adapter.calls)

    second = await orchestrator.execute(
        ctx=_ctx(),
        capability_id="infra.inspect",
        params={"resource": "prosperfy-main"},
        idempotency_key="dedupe-key-001",
    )

    assert first.status.value == "completed"
    assert second.status.value == "completed"
    # Comportamento esperado (idempotency_behavior: return_cached no YAML):
    # a segunda chamada com a MESMA idempotency_key não deve re-invocar o
    # adapter — deve retornar o resultado cacheado.
    assert len(adapter.calls) == calls_after_first
    assert second.execution_id == first.execution_id
