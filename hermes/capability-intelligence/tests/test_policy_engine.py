"""
Testes do Policy Engine.
"""

import pytest

from capability_intelligence.policy_engine import (
    PolicyEngine,
    PolicyResult,
    PolicyVerdict,
    policy_environment_allowed,
    policy_requires_approval,
)


class TestPolicyEngine:
    """Testes de políticas de execução."""

    @pytest.mark.asyncio
    async def test_allow_when_no_policies(self):
        engine = PolicyEngine()
        verdicts = await engine.evaluate(
            capability_id="test", user="will",
            environment="staging", domain="infrastructure",
        )
        assert len(verdicts) == 0

    @pytest.mark.asyncio
    async def test_environment_allowed(self):
        engine = PolicyEngine(policies=[policy_environment_allowed])
        verdicts = await engine.evaluate(
            capability_id="test", user="will",
            environment="staging", domain="infrastructure",
        )
        assert all(v.result == PolicyResult.ALLOW for v in verdicts)

    @pytest.mark.asyncio
    async def test_environment_denied(self):
        engine = PolicyEngine(policies=[policy_environment_allowed])
        verdicts = await engine.evaluate(
            capability_id="test", user="will",
            environment="production-test", domain="infrastructure",
        )
        assert any(v.result == PolicyResult.DENY for v in verdicts)

    @pytest.mark.asyncio
    async def test_requires_approval_with_auth(self):
        engine = PolicyEngine(policies=[policy_requires_approval])
        verdicts = await engine.evaluate(
            capability_id="test", user="will",
            environment="staging", domain="infrastructure",
            authorization_result={"requires_approval": True},
        )
        assert engine.requires_approval(verdicts)

    @pytest.mark.asyncio
    async def test_requires_approval_without_auth(self):
        engine = PolicyEngine(policies=[policy_requires_approval])
        verdicts = await engine.evaluate(
            capability_id="test", user="will",
            environment="staging", domain="infrastructure",
            authorization_result={"requires_approval": False},
        )
        assert not engine.requires_approval(verdicts)

    @pytest.mark.asyncio
    async def test_multiple_policies(self):
        engine = PolicyEngine(policies=[
            policy_environment_allowed,
            policy_requires_approval,
        ])
        verdicts = await engine.evaluate(
            capability_id="test", user="will",
            environment="production-test", domain="infrastructure",
        )
        assert any(v.result == PolicyResult.DENY for v in verdicts)