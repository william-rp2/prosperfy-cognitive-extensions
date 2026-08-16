"""
tests/unit/test_actor_context.py — Testes de construção do ActorContext.

GATE: test_capability_execute_without_tenant_returns_401
      test_capability_execute_without_actor_returns_401
"""

from __future__ import annotations

import pytest

from cognitive.tenancy.context import (
    _STATIC_CREDENTIALS,
    build_actor_context,
    register_static_credential,
)


@pytest.fixture(autouse=True)
def setup_credential():
    _STATIC_CREDENTIALS.clear()
    register_static_credential("valid-secret", "tenant-a", "actor-a", "owner-core")
    yield
    _STATIC_CREDENTIALS.clear()


def test_build_valid_context():
    ctx = build_actor_context(
        authorization="Bearer valid-secret",
        x_tenant_id="tenant-a",
        x_actor_id="actor-a",
        x_correlation_id="corr-001",
    )
    assert ctx.tenant_id == "tenant-a"
    assert ctx.actor_id == "actor-a"
    assert ctx.correlation_id == "corr-001"
    assert ctx.profile == "owner-core"
    # credential_ref é hash, não o valor original
    assert "valid-secret" not in ctx.credential_ref


def test_missing_authorization_raises():
    with pytest.raises(ValueError, match="Authorization"):
        build_actor_context(None, "tenant-a", "actor-a", None)


def test_missing_tenant_id_raises():
    with pytest.raises(ValueError, match="X-Tenant-Id"):
        build_actor_context("Bearer valid-secret", None, "actor-a", None)


def test_missing_actor_id_raises():
    with pytest.raises(ValueError, match="X-Actor-Id"):
        build_actor_context("Bearer valid-secret", "tenant-a", None, None)


def test_invalid_credential_raises():
    with pytest.raises(ValueError, match="[Cc]redencial|[Aa]uthoriz"):
        build_actor_context("Bearer wrong-secret", "tenant-a", "actor-a", None)


def test_tenant_mismatch_raises():
    """Tenant declarado no header deve corresponder à credential registrada."""
    with pytest.raises(ValueError, match="[Tt]enant"):
        build_actor_context("Bearer valid-secret", "tenant-evil", "actor-a", None)


def test_actor_mismatch_raises():
    """Actor declarado no header deve corresponder à credential registrada."""
    with pytest.raises(ValueError, match="[Aa]ctor"):
        build_actor_context("Bearer valid-secret", "tenant-a", "actor-evil", None)


def test_correlation_id_generated_if_absent():
    ctx = build_actor_context("Bearer valid-secret", "tenant-a", "actor-a", None)
    assert ctx.correlation_id  # gerado automaticamente
    assert len(ctx.correlation_id) > 8


def test_actor_context_is_immutable():
    ctx = build_actor_context("Bearer valid-secret", "tenant-a", "actor-a", "corr-x")
    with pytest.raises((AttributeError, TypeError)):
        ctx.tenant_id = "evil"  # type: ignore[misc]
