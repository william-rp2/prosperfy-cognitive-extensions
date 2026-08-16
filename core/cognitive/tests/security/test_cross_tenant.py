"""
tests/security/test_cross_tenant.py — Testes de segurança cross-tenant.

GATE:
  test_cross_tenant_audit_isolation
  test_cross_tenant_capability_grant_denied
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cognitive.contracts.tenancy import CapabilityGrant
from cognitive.tenancy.context import _STATIC_CREDENTIALS, register_static_credential


@pytest.fixture(autouse=True)
def clear_creds():
    _STATIC_CREDENTIALS.clear()
    yield
    _STATIC_CREDENTIALS.clear()


def test_cross_tenant_audit_isolation(app_and_services):
    """
    GATE: tenant-b não deve conseguir acessar audits do tenant-a.

    Verifica isolamento de dados em nível de aplicação (Sprint 0.1).
    """
    app, registry, audit_writer, _ = app_and_services

    # Setup: tenant-a executa infra.inspect
    register_static_credential("secret-a", "tenant-a", "actor-a", "owner-core")
    registry.register_grant(CapabilityGrant(
        tenant_id="tenant-a",
        profile="owner-core",
        capability_id="infra.inspect",
    ))

    with TestClient(app) as client:
        r = client.post(
            "/v1/capabilities/infra.inspect/execute",
            json={"params": {"resource": "prosperfy-main"}},
            headers={
                "Authorization": "Bearer secret-a",
                "X-Tenant-Id": "tenant-a",
                "X-Actor-Id": "actor-a",
            },
        )

    assert r.json()["status"] == "completed"
    audit_id = r.json()["audit_id"]

    # tenant-b tenta acessar o audit_id do tenant-a diretamente (app-layer)
    import asyncio
    result = asyncio.get_event_loop().run_until_complete(
        audit_writer.get(audit_id, tenant_id="tenant-b")
    )
    # DEVE ser None — cross-tenant isolation
    assert result is None, "Cross-tenant audit access deve ser bloqueado"

    # tenant-a pode acessar o próprio audit
    own = asyncio.get_event_loop().run_until_complete(
        audit_writer.get(audit_id, tenant_id="tenant-a")
    )
    assert own is not None
    assert own.tenant_id == "tenant-a"


def test_cross_tenant_capability_grant_denied(app_and_services):
    """
    GATE: tenant-b não deve executar capability usando grant de tenant-a.

    Mesmo que tenant-b use os mesmos headers, sem grant próprio → DENY.
    """
    app, registry, audit_writer, _ = app_and_services

    # Somente tenant-a tem grant
    register_static_credential("secret-a", "tenant-a", "actor-a", "owner-core")
    register_static_credential("secret-b", "tenant-b", "actor-b", "owner-core")
    registry.register_grant(CapabilityGrant(
        tenant_id="tenant-a",
        profile="owner-core",
        capability_id="infra.inspect",
    ))

    with TestClient(app) as client:
        r = client.post(
            "/v1/capabilities/infra.inspect/execute",
            json={"params": {"resource": "prosperfy-main"}},
            headers={
                "Authorization": "Bearer secret-b",
                "X-Tenant-Id": "tenant-b",
                "X-Actor-Id": "actor-b",
            },
        )

    data = r.json()
    # tenant-b deve ser DENIED — sem grant próprio
    assert data["status"] == "failed"

    events_b = audit_writer.get_all_for_tenant("tenant-b")
    assert len(events_b) == 1
    from cognitive.contracts.audit import AuditOutcome
    assert events_b[0].outcome == AuditOutcome.DENIED

    # tenant-a não deve ter nenhum audit registrado (não executou)
    events_a = audit_writer.get_all_for_tenant("tenant-a")
    assert len(events_a) == 0


def test_wrong_tenant_header_rejected(app_and_services):
    """
    Credential de tenant-a não deve funcionar com X-Tenant-Id de tenant-b.

    Verificação de binding credential↔tenant nos headers.
    """
    app, *_ = app_and_services
    register_static_credential("secret-a", "tenant-a", "actor-a", "owner-core")

    with TestClient(app) as client:
        r = client.post(
            "/v1/capabilities/infra.inspect/execute",
            json={"params": {"resource": "prosperfy-main"}},
            headers={
                "Authorization": "Bearer secret-a",
                "X-Tenant-Id": "tenant-evil",  # tenant errado para esta credential
                "X-Actor-Id": "actor-a",
            },
        )

    assert r.status_code == 401
