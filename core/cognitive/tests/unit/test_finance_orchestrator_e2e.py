"""
tests/unit/test_finance_orchestrator_e2e.py — P2 (Financeiro pelo WhatsApp).

End-to-end through the real ExecutionOrchestrator + real YAML-loaded
registry + real PolicyEngine, wired to RoutingSkillsAdapter so finance.*
reaches MockFinanceApiAdapter while everything else would still reach the
(unused-here) default adapter. Proves the whole chain — grant/policy order,
capability-simple dispatch (tool_name == capability_id), audit — works for
a finance.* capability exactly like it does for infra.* today.

F2B: finance.* é fail-closed no PolicyEngine — sem ACL, ou sem contexto de
finance válido, é DENY. Estes testes exercitam a ORQUESTRAÇÃO, então rodam
com uma FinanceAcl configurada e um contexto internal confiável (o caller
server-side já autenticado pela boundary: ActorContext.credential_ref).
Não existe caminho aqui que autorize finance por ausência de configuração.
"""

from __future__ import annotations

from cognitive.adapters.finance_api.mock import MockFinanceApiAdapter
from cognitive.adapters.routing import RoutingSkillsAdapter
from cognitive.audit.writer import InMemoryAuditWriter
from cognitive.contracts.gateway import GatewayStatus
from cognitive.contracts.tenancy import ActorContext, CapabilityGrant
from cognitive.execution.orchestrator import ExecutionOrchestrator
from cognitive.policy.engine import PolicyEngine
from cognitive.policy.finance_acl import (
    FinanceAcl,
    FinanceAclConfig,
    FinanceActorDirectory,
    FinanceChannelContext,
    FinanceContextKind,
)
from cognitive.registry.registry import InMemoryCapabilityRegistry
from cognitive.telemetry.recorder import InMemoryTelemetryRecorder

TENANT = "tenant-p2-e2e"
PROFILE = "finance-user"
OWNER_ACTOR = "actor-p2"

# Caller server-side já autenticado pela boundary: sem chat_id, por contrato.
INTERNAL_CHANNEL = FinanceChannelContext(kind=FinanceContextKind.INTERNAL)


def _finance_acl() -> FinanceAcl:
    """Identidade vem de configuração — nunca de nome nem de texto."""
    return FinanceAcl(
        config=FinanceAclConfig(owner_actor_ids=frozenset({OWNER_ACTOR})),
        directory=FinanceActorDirectory({}),
    )


class _UnusedAdapter:
    """Default adapter for the router — asserts nothing finance.* ever reaches it."""

    async def invoke_tool(self, tool_name, arguments, tenant_id, correlation_id):
        raise AssertionError(f"non-finance adapter should never be called for {tool_name!r}")

    async def health(self) -> bool:
        return True


def _ctx(profile: str = PROFILE) -> ActorContext:
    return ActorContext(
        tenant_id=TENANT,
        actor_id=OWNER_ACTOR,
        correlation_id="corr-p2-e2e",
        credential_ref="ref-p2",
        profile=profile,
    )


def _build_orchestrator(grants: dict[str, str] | None = None) -> ExecutionOrchestrator:
    """grants: {capability_id: policy_override} — registered for PROFILE/TENANT."""
    registry = InMemoryCapabilityRegistry()
    registry.load_from_yaml()
    for capability_id, policy_override in (grants or {}).items():
        registry.register_grant(
            CapabilityGrant(
                tenant_id=TENANT,
                profile=PROFILE,
                capability_id=capability_id,
                policy_override=policy_override,
            )
        )
    adapter = RoutingSkillsAdapter(default_adapter=_UnusedAdapter(), routes={"finance.": MockFinanceApiAdapter()})
    return ExecutionOrchestrator(
        registry=registry,
        policy_engine=PolicyEngine(finance_acl=_finance_acl()),
        skills_adapter=adapter,
        audit_writer=InMemoryAuditWriter(),
        telemetry_recorder=InMemoryTelemetryRecorder(),
    )


async def test_finance_summary_read_completes_with_grant():
    orchestrator = _build_orchestrator({"finance.summary.read": "allow"})
    response = await orchestrator.execute(
        _ctx(), "finance.summary.read", {"month": "2026-08"}, channel=INTERNAL_CHANNEL
    )

    assert response.status == GatewayStatus.COMPLETED
    assert response.data["success"] is True
    assert response.data["data"]["monthExpense"] == 300.0


async def test_finance_capability_denied_without_a_grant():
    """Policy order is inviolable (ADR-V2-004): no grant -> DENY -> FAILED, adapter never called."""
    orchestrator = _build_orchestrator(grants=None)
    response = await orchestrator.execute(
        _ctx(), "finance.summary.read", {}, channel=INTERNAL_CHANNEL
    )

    assert response.status == GatewayStatus.FAILED
    assert "Denied" in (response.error or "")


async def test_finance_capability_confirm_never_invokes_the_adapter():
    orchestrator = _build_orchestrator({"finance.manual.create": "confirm"})
    response = await orchestrator.execute(
        _ctx(),
        "finance.manual.create",
        {"amount": 10, "direction": "expense", "description": "x"},
        channel=INTERNAL_CHANNEL,
    )

    assert response.status == GatewayStatus.PENDING_CONFIRMATION


async def test_unknown_finance_capability_id_fails_before_reaching_any_adapter():
    orchestrator = _build_orchestrator()
    response = await orchestrator.execute(
        _ctx(), "finance.does.not.exist", {}, channel=INTERNAL_CHANNEL
    )
    assert response.status == GatewayStatus.FAILED


async def test_manual_create_reaches_the_finance_adapter_with_capability_id_as_tool_name():
    """No `tools:` in the YAML -> orchestrator calls invoke_tool(tool_name=capability_id, ...)
    directly (execution/orchestrator.py, 'capability simples' branch)."""
    orchestrator = _build_orchestrator({"finance.manual.create": "allow"})
    response = await orchestrator.execute(
        _ctx(),
        "finance.manual.create",
        {"amount": 89, "direction": "expense", "description": "Combustível"},
        channel=INTERNAL_CHANNEL,
    )

    assert response.status == GatewayStatus.COMPLETED
    assert response.data["data"]["transaction"]["source"] == "manual"
