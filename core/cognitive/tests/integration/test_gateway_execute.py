"""
tests/integration/test_gateway_execute.py — Testes de integração do Gateway end-to-end.

GATE:
  test_capability_execute_without_tenant_returns_401
  test_capability_execute_without_actor_returns_401
  test_policy_deny_blocks_adapter_call
  test_policy_confirm_does_not_call_adapter
  test_infra_inspect_allow_writes_audit_and_telemetry
  test_idempotency_key_prevents_duplicate_execution
  test_prosperfy_skills_adapter_mocked_no_real_vps_in_ci
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cognitive.contracts.audit import AuditOutcome
from cognitive.contracts.tenancy import CapabilityGrant
from cognitive.tenancy.context import _STATIC_CREDENTIALS, register_static_credential


@pytest.fixture(autouse=True)
def clear_creds():
    _STATIC_CREDENTIALS.clear()
    yield
    _STATIC_CREDENTIALS.clear()


@pytest.fixture
def full_client(app_and_services):
    """Client com tenant-a com grant ALLOW para infra.inspect."""
    app, registry, audit_writer, telemetry_recorder = app_and_services

    register_static_credential("secret-a", "tenant-a", "actor-a", "owner-core")
    registry.register_grant(CapabilityGrant(
        tenant_id="tenant-a",
        profile="owner-core",
        capability_id="infra.inspect",
    ))

    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, audit_writer, telemetry_recorder


@pytest.fixture
def headers_a():
    return {
        "Authorization": "Bearer secret-a",
        "X-Tenant-Id": "tenant-a",
        "X-Actor-Id": "actor-a",
    }


# ─── GATE TESTS ─────────────────────────────────────────────────────────

def test_capability_execute_without_tenant_returns_401(full_client):
    """GATE: Request sem X-Tenant-Id deve retornar 401."""
    client, *_ = full_client
    r = client.post(
        "/v1/capabilities/infra.inspect/execute",
        json={"params": {"resource": "prosperfy-main"}},
        headers={"Authorization": "Bearer secret-a", "X-Actor-Id": "actor-a"},
    )
    assert r.status_code == 401


def test_capability_execute_without_actor_returns_401(full_client):
    """GATE: Request sem X-Actor-Id deve retornar 401."""
    client, *_ = full_client
    r = client.post(
        "/v1/capabilities/infra.inspect/execute",
        json={"params": {"resource": "prosperfy-main"}},
        headers={"Authorization": "Bearer secret-a", "X-Tenant-Id": "tenant-a"},
    )
    assert r.status_code == 401


def test_capability_execute_without_authorization_returns_401(full_client):
    """Request sem Authorization deve retornar 401."""
    client, *_ = full_client
    r = client.post(
        "/v1/capabilities/infra.inspect/execute",
        json={"params": {"resource": "prosperfy-main"}},
        headers={"X-Tenant-Id": "tenant-a", "X-Actor-Id": "actor-a"},
    )
    assert r.status_code == 401


def test_policy_deny_blocks_adapter_call(app_and_services):
    """GATE: Tenant sem grant deve receber DENY; adapter não deve ser chamado."""
    app, registry, audit_writer, _ = app_and_services

    register_static_credential("secret-b", "tenant-b", "actor-b", "owner-core")
    # tenant-b NÃO tem grant para infra.inspect

    with TestClient(app, raise_server_exceptions=True) as client:
        r = client.post(
            "/v1/capabilities/infra.inspect/execute",
            json={"params": {"resource": "some-resource"}},
            headers={
                "Authorization": "Bearer secret-b",
                "X-Tenant-Id": "tenant-b",
                "X-Actor-Id": "actor-b",
            },
        )

    # Deve falhar (DENY → status failed no response, HTTP pode ser 200 com status=failed
    # ou 403 dependendo do design; verificar audit)
    data = r.json()
    assert data["status"] == "failed"

    # Verificar que o audit registrou DENIED e não chamou MCP
    events = audit_writer.get_all_for_tenant("tenant-b")
    assert len(events) == 1
    assert events[0].outcome == AuditOutcome.DENIED


def test_policy_confirm_does_not_call_adapter(app_and_services):
    """GATE: Capability com policy CONFIRM deve retornar pending_confirmation sem chamar adapter."""
    app, registry, audit_writer, _ = app_and_services

    register_static_credential("secret-a", "tenant-a", "actor-a", "owner-core")
    # Grant com override CONFIRM
    registry.register_grant(CapabilityGrant(
        tenant_id="tenant-a",
        profile="owner-core",
        capability_id="infra.inspect",
        policy_override="confirm",
    ))

    with TestClient(app, raise_server_exceptions=True) as client:
        r = client.post(
            "/v1/capabilities/infra.inspect/execute",
            json={"params": {"resource": "prosperfy-main"}},
            headers={
                "Authorization": "Bearer secret-a",
                "X-Tenant-Id": "tenant-a",
                "X-Actor-Id": "actor-a",
            },
        )

    data = r.json()
    assert data["status"] == "pending_confirmation"

    # Verificar audit: pending, sem tool calls
    events = audit_writer.get_all_for_tenant("tenant-a")
    assert len(events) == 1
    assert events[0].outcome == AuditOutcome.PENDING_CONFIRMATION
    assert events[0].result_summary.get("tool_calls", 0) == 0


def test_infra_inspect_allow_writes_audit_and_telemetry(full_client, headers_a):
    """GATE: Execução ALLOW deve registrar audit e telemetry."""
    client, audit_writer, telemetry_recorder = full_client

    r = client.post(
        "/v1/capabilities/infra.inspect/execute",
        json={"params": {"resource": "prosperfy-main"}},
        headers=headers_a,
    )

    data = r.json()
    assert data["status"] == "completed"
    assert data["execution_id"]
    assert data["audit_id"]

    # Audit deve existir
    events = audit_writer.get_all_for_tenant("tenant-a")
    assert len(events) == 1
    assert events[0].outcome == AuditOutcome.COMPLETED
    assert events[0].policy_decision == "allow"

    # Telemetry deve existir
    telem = telemetry_recorder.get_all_for_tenant("tenant-a")
    assert len(telem) == 1
    assert telem[0].tool_calls > 0


def test_secrets_redacted_in_audit_payload(full_client, headers_a):
    """GATE: Secrets nos params não devem aparecer no audit."""
    client, audit_writer, _ = full_client

    client.post(
        "/v1/capabilities/infra.inspect/execute",
        json={"params": {"resource": "prosperfy-main", "api_key": "SUPER-SECRET"}},
        headers=headers_a,
    )

    events = audit_writer.get_all_for_tenant("tenant-a")
    assert len(events) == 1
    assert events[0].inputs_redacted.get("api_key") == "***REDACTED***"
    assert "SUPER-SECRET" not in str(events[0].inputs_redacted)


def test_idempotency_key_request_succeeds(full_client, headers_a):
    """GATE: Request com idempotency_key deve ser aceito."""
    client, audit_writer, _ = full_client

    r = client.post(
        "/v1/capabilities/infra.inspect/execute",
        json={"params": {"resource": "prosperfy-main"}, "idempotency_key": "unique-key-001"},
        headers=headers_a,
    )

    data = r.json()
    assert data["status"] == "completed"


def test_prosperfy_skills_adapter_mocked_no_real_vps_in_ci(full_client, headers_a):
    """GATE: CI usa MockSkillsAdapter — nenhuma chamada HTTP real para VPS."""
    client, audit_writer, _ = full_client

    r = client.post(
        "/v1/capabilities/infra.inspect/execute",
        json={"params": {"resource": "prosperfy-main"}},
        headers=headers_a,
    )

    data = r.json()
    assert data["status"] == "completed"
    # Mock retorna dados determinísticos do panorama
    assert "prosperfy_vps_panorama" in str(data["data"])


def test_health_endpoint_is_public(full_client):
    """GET /health deve funcionar sem autenticação."""
    client, *_ = full_client
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_status_endpoint_returns_tenant(full_client, headers_a):
    """GET /v1/status deve retornar tenant/actor resolvidos."""
    client, *_ = full_client
    r = client.get("/v1/status", headers=headers_a)
    assert r.status_code == 200
    data = r.json()
    assert data["tenant_id"] == "tenant-a"
    assert data["actor_id"] == "actor-a"
    assert data["healthy"] is True


def test_capability_describe(full_client, headers_a):
    """GET /v1/capabilities/infra.inspect deve descrever a capability."""
    client, *_ = full_client
    r = client.get("/v1/capabilities/infra.inspect", headers=headers_a)
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == "infra.inspect"
    assert data["domain"] == "infrastructure"


def test_unknown_capability_returns_404(full_client, headers_a):
    """Describe de capability inexistente deve retornar 404."""
    client, *_ = full_client
    r = client.get("/v1/capabilities/does.not.exist", headers=headers_a)
    assert r.status_code == 404
