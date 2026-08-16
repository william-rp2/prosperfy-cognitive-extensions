"""
tests/security/test_cross_tenant.py — Testes de segurança cross-tenant (Sprint 0.2).

Usa fixtures do conftest.py com IdentityResolver in-memory.
"""

from __future__ import annotations

import asyncio
import pytest
from fastapi.testclient import TestClient

from cognitive.contracts.audit import AuditOutcome
from cognitive.contracts.tenancy import CapabilityGrant


def test_cross_tenant_audit_isolation(app_and_services, tenant_a_headers):
    """
    GATE: tenant-b não deve conseguir acessar audits do tenant-a.

    Verifica isolamento de dados em nível de aplicação (in-memory Sprint 0.1)
    e confirma que será reforçado por RLS no Sprint 0.2 (testes em tests/db/).
    """
    app, registry, audit_writer, _ = app_and_services

    registry.register_grant(CapabilityGrant(
        tenant_id="tenant-a",
        profile="owner-core",
        capability_id="infra.inspect",
    ))

    with TestClient(app) as client:
        r = client.post(
            "/v1/capabilities/infra.inspect/execute",
            json={"params": {"resource": "prosperfy-main"}},
            headers=tenant_a_headers,
        )

    assert r.json()["status"] == "completed"
    audit_id = r.json()["audit_id"]

    # tenant-b tenta acessar o audit_id do tenant-a
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(
            audit_writer.get(audit_id, tenant_id="tenant-b")
        )
    finally:
        loop.close()

    assert result is None, "Cross-tenant audit access deve ser bloqueado"

    # tenant-a pode acessar o próprio audit
    loop2 = asyncio.new_event_loop()
    try:
        own = loop2.run_until_complete(
            audit_writer.get(audit_id, tenant_id="tenant-a")
        )
    finally:
        loop2.close()

    assert own is not None
    assert own.tenant_id == "tenant-a"


def test_cross_tenant_capability_grant_denied(app_and_services, tenant_b_headers):
    """
    GATE: tenant-b não deve executar capability usando grant de tenant-a.

    Mesmo que tenant-b use os mesmos headers, sem grant próprio → DENY.
    """
    app, registry, audit_writer, _ = app_and_services

    # Somente tenant-a tem grant — tenant-b não tem
    registry.register_grant(CapabilityGrant(
        tenant_id="tenant-a",
        profile="owner-core",
        capability_id="infra.inspect",
    ))

    with TestClient(app) as client:
        r = client.post(
            "/v1/capabilities/infra.inspect/execute",
            json={"params": {"resource": "prosperfy-main"}},
            headers=tenant_b_headers,
        )

    data = r.json()
    assert data["status"] == "failed"

    events_b = audit_writer.get_all_for_tenant("tenant-b")
    assert len(events_b) == 1
    assert events_b[0].outcome == AuditOutcome.DENIED

    # tenant-a não deve ter nenhum audit registrado
    events_a = audit_writer.get_all_for_tenant("tenant-a")
    assert len(events_a) == 0


def test_wrong_tenant_header_rejected(app_and_services):
    """
    Credential de tenant-a não deve funcionar com X-Tenant-Id de tenant-b.

    Verificação de binding credential↔tenant no IdentityResolver.
    """
    app, *_ = app_and_services

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
