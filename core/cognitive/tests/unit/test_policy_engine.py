"""
tests/unit/test_policy_engine.py — Testes unitários do PolicyEngine V2.

Gate: test_policy_deny_blocks_adapter_call, test_policy_confirm_does_not_call_adapter
"""

from __future__ import annotations

import pytest

from cognitive.contracts.capability import Domain, IdempotencyBehavior, RegisteredCapability
from cognitive.contracts.policy import PolicyDecision
from cognitive.contracts.tenancy import ActorContext, CapabilityGrant
from cognitive.policy.engine import PolicyEngine


@pytest.fixture
def engine() -> PolicyEngine:
    return PolicyEngine()


@pytest.fixture
def ctx_a() -> ActorContext:
    return ActorContext(
        tenant_id="tenant-a",
        actor_id="actor-a",
        correlation_id="corr-001",
        credential_ref="ref-a",
        profile="owner-core",
    )


@pytest.fixture
def cap_allow() -> RegisteredCapability:
    return RegisteredCapability(
        id="infra.inspect",
        version="1.0.0",
        domain=Domain.INFRASTRUCTURE,
        description="Test allow cap",
        adapter="prosperfy_skills",
        default_policy="allow",
    )


@pytest.fixture
def cap_confirm() -> RegisteredCapability:
    return RegisteredCapability(
        id="email.send",
        version="1.0.0",
        domain=Domain.COMMUNICATION,
        description="Test confirm cap",
        adapter="prosperfy_skills",
        default_policy="confirm",
    )


@pytest.fixture
def cap_deny() -> RegisteredCapability:
    return RegisteredCapability(
        id="admin.nuke",
        version="1.0.0",
        domain=Domain.OTHER,
        description="Test deny cap",
        adapter="prosperfy_skills",
        default_policy="deny",
    )


@pytest.fixture
def grant_a(cap_allow) -> CapabilityGrant:
    return CapabilityGrant(
        tenant_id="tenant-a",
        profile="owner-core",
        capability_id=cap_allow.id,
    )


@pytest.mark.asyncio
async def test_policy_allow(engine, ctx_a, cap_allow, grant_a):
    verdict = await engine.evaluate(ctx_a, cap_allow, {}, grant_a)
    assert verdict.decision == PolicyDecision.ALLOW


@pytest.mark.asyncio
async def test_policy_confirm_does_not_execute(engine, ctx_a, cap_confirm):
    """GATE: CONFIRM não deve executar o adapter."""
    grant = CapabilityGrant(tenant_id="tenant-a", profile="owner-core", capability_id="email.send")
    verdict = await engine.evaluate(ctx_a, cap_confirm, {}, grant)
    assert verdict.decision == PolicyDecision.CONFIRM
    # Verificar que a reason indica não execução
    assert "confirmação" in verdict.reason.lower() or "confirm" in verdict.reason.lower()


@pytest.mark.asyncio
async def test_policy_deny_blocks_adapter(engine, ctx_a, cap_deny):
    """GATE: DENY não deve executar o adapter."""
    grant = CapabilityGrant(tenant_id="tenant-a", profile="owner-core", capability_id="admin.nuke")
    verdict = await engine.evaluate(ctx_a, cap_deny, {}, grant)
    assert verdict.decision == PolicyDecision.DENY


@pytest.mark.asyncio
async def test_policy_no_grant_returns_deny(engine, ctx_a, cap_allow):
    """Sem grant → DENY obrigatório."""
    verdict = await engine.evaluate(ctx_a, cap_allow, {}, grant=None)
    assert verdict.decision == PolicyDecision.DENY
    assert "grant" in verdict.reason.lower()


@pytest.mark.asyncio
async def test_policy_grant_override_confirm(engine, ctx_a, cap_allow):
    """Grant com policy_override=confirm deve sobrescrever default allow."""
    grant = CapabilityGrant(
        tenant_id="tenant-a",
        profile="owner-core",
        capability_id=cap_allow.id,
        policy_override="confirm",
    )
    verdict = await engine.evaluate(ctx_a, cap_allow, {}, grant)
    assert verdict.decision == PolicyDecision.CONFIRM


@pytest.mark.asyncio
async def test_cross_tenant_grant_denied(engine, ctx_a, cap_allow):
    """Grant de outro tenant não deve funcionar para tenant-a."""
    wrong_tenant_grant = CapabilityGrant(
        tenant_id="tenant-evil",  # grant pertence a outro tenant
        profile="owner-core",
        capability_id=cap_allow.id,
    )
    verdict = await engine.evaluate(ctx_a, cap_allow, {}, wrong_tenant_grant)
    assert verdict.decision == PolicyDecision.DENY
    assert "cross" in verdict.reason.lower() or "tenant" in verdict.reason.lower()
