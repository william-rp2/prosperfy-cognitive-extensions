"""
tests/conftest.py — Fixtures compartilhadas (Sprint 0.2).

Monta TestClient com IdentityResolver in-memory (sem DB).
Mantém retrocompatibilidade com todos os 45 testes do Sprint 0.1.

Tenants de teste:
  tenant-a / actor-a / credential: "secret-a" (profile: owner-core)
  tenant-b / actor-b / credential: "secret-b" (profile: owner-core, sem grants)
  confirmtest / actor-c / credential: "secret-c" (profile: owner-core, CONFIRM override)
"""

from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient

from cognitive.adapters.prosperfy_skills.mock import MockSkillsAdapter
from cognitive.audit.writer import InMemoryAuditWriter
from cognitive.contracts.tenancy import CapabilityGrant
from cognitive.execution.orchestrator import ExecutionOrchestrator
from cognitive.execution.resource_resolver import InMemoryResourceResolver
from cognitive.gateway.app import create_app
from cognitive.policy.engine import PolicyEngine
from cognitive.registry.registry import InMemoryCapabilityRegistry
from cognitive.telemetry.recorder import InMemoryTelemetryRecorder
from cognitive.tenancy.identity_resolver import IdentityResolver


def _make_identity_resolver() -> IdentityResolver:
    """Cria IdentityResolver in-memory com credenciais de teste."""
    resolver = IdentityResolver(identity_repo=None)
    resolver.register_static("secret-a", "tenant-a", "actor-a", "owner-core")
    resolver.register_static("secret-b", "tenant-b", "actor-b", "owner-core")
    resolver.register_static("secret-c", "confirmtest", "actor-c", "owner-core")
    return resolver


@pytest.fixture
def app_and_services():
    """Monta app com todos os serviços in-memory para testes."""
    # Garantir que DB não seja usado nos testes in-memory
    os.environ.pop("COGNITIVE_DB_URL", None)
    os.environ["COGNITIVE_GATEWAY_CREDENTIAL"] = "__disabled_in_test__"

    registry = InMemoryCapabilityRegistry()
    registry.load_from_yaml()

    policy_engine = PolicyEngine()
    audit_writer = InMemoryAuditWriter()
    telemetry_recorder = InMemoryTelemetryRecorder()
    skills_adapter = MockSkillsAdapter()
    identity_resolver = _make_identity_resolver()

    resource_resolver = InMemoryResourceResolver()
    resource_resolver.register("tenant-a", "prosperfy-main",
                                {"host": "mock-vps.test", "type": "vps"})
    resource_resolver.register("tenant-b", "prosperfy-main",
                                {"host": "mock-vps-b.test", "type": "vps"})

    orchestrator = ExecutionOrchestrator(
        registry=registry,
        policy_engine=policy_engine,
        skills_adapter=skills_adapter,
        audit_writer=audit_writer,
        telemetry_recorder=telemetry_recorder,
    )

    app = create_app()
    # Sobrescrever estado com serviços de teste
    app.state.registry = registry
    app.state.orchestrator = orchestrator
    app.state.audit_writer = audit_writer
    app.state.telemetry_recorder = telemetry_recorder
    app.state.identity_resolver = identity_resolver
    app.state.resource_resolver = resource_resolver
    app.state.use_db = False

    return app, registry, audit_writer, telemetry_recorder


@pytest.fixture
def tenant_a_headers():
    """Headers para tenant-a / actor-a."""
    return {
        "Authorization": "Bearer secret-a",
        "X-Tenant-Id": "tenant-a",
        "X-Actor-Id": "actor-a",
        "X-Correlation-Id": "test-correlation-001",
    }


@pytest.fixture
def tenant_b_headers():
    """Headers para tenant-b / actor-b (sem grants por default)."""
    return {
        "Authorization": "Bearer secret-b",
        "X-Tenant-Id": "tenant-b",
        "X-Actor-Id": "actor-b",
        "X-Correlation-Id": "test-correlation-002",
    }


@pytest.fixture
def confirm_headers():
    """Headers para confirmtest / actor-c."""
    return {
        "Authorization": "Bearer secret-c",
        "X-Tenant-Id": "confirmtest",
        "X-Actor-Id": "actor-c",
        "X-Correlation-Id": "test-correlation-003",
    }


@pytest.fixture
def client_with_grants(app_and_services, tenant_a_headers):
    """Client com tenant-a que tem grant para infra.inspect."""
    app, registry, audit_writer, telemetry_recorder = app_and_services
    registry.register_grant(CapabilityGrant(
        tenant_id="tenant-a",
        profile="owner-core",
        capability_id="infra.inspect",
    ))
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, audit_writer, telemetry_recorder, tenant_a_headers


@pytest.fixture
def client_no_grants(app_and_services, tenant_b_headers):
    """Client com tenant-b sem nenhum grant."""
    app, registry, audit_writer, _ = app_and_services
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, audit_writer, tenant_b_headers


@pytest.fixture
def client_confirm(app_and_services, confirm_headers):
    """Client com confirmtest com CONFIRM override para infra.inspect."""
    app, registry, audit_writer, telemetry_recorder = app_and_services
    registry.register_grant(CapabilityGrant(
        tenant_id="confirmtest",
        profile="owner-core",
        capability_id="infra.inspect",
        policy_override="confirm",
    ))
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, audit_writer, telemetry_recorder, confirm_headers
