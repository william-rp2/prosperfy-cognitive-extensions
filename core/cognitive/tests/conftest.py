"""
tests/conftest.py — Fixtures compartilhadas para todos os testes do Cognitive Core.

Monta um TestClient FastAPI com:
- Tenant "tenant-a" / actor "actor-a" (credential: "secret-a")
- Tenant "tenant-b" / actor "actor-b" (credential: "secret-b")
- Grant de infra.inspect apenas para tenant-a (profile owner-core)
- Grant de infra.inspect com CONFIRM override para tenant confirmtest
- MockSkillsAdapter (sem MCP real)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cognitive.adapters.prosperfy_skills.mock import MockSkillsAdapter
from cognitive.audit.writer import InMemoryAuditWriter
from cognitive.contracts.tenancy import CapabilityGrant
from cognitive.execution.orchestrator import ExecutionOrchestrator
from cognitive.gateway.app import create_app
from cognitive.policy.engine import PolicyEngine
from cognitive.registry.registry import InMemoryCapabilityRegistry
from cognitive.telemetry.recorder import InMemoryTelemetryRecorder
from cognitive.tenancy.context import _STATIC_CREDENTIALS, register_static_credential


@pytest.fixture(autouse=True)
def clear_credentials():
    """Limpa credenciais estáticas antes de cada teste."""
    _STATIC_CREDENTIALS.clear()
    yield
    _STATIC_CREDENTIALS.clear()


@pytest.fixture
def app_and_services():
    """Monta app e retorna serviços para inspeção em testes."""
    # Limpa credenciais dev padrão
    import os
    os.environ["COGNITIVE_GATEWAY_CREDENTIAL"] = "__disabled__"

    registry = InMemoryCapabilityRegistry()
    registry.load_from_yaml()

    policy_engine = PolicyEngine()
    audit_writer = InMemoryAuditWriter()
    telemetry_recorder = InMemoryTelemetryRecorder()
    skills_adapter = MockSkillsAdapter()

    orchestrator = ExecutionOrchestrator(
        registry=registry,
        policy_engine=policy_engine,
        skills_adapter=skills_adapter,
        audit_writer=audit_writer,
        telemetry_recorder=telemetry_recorder,
    )

    app = create_app()
    # Sobrescrever serviços da app com os de teste
    app.state.registry = registry
    app.state.orchestrator = orchestrator
    app.state.audit_writer = audit_writer
    app.state.telemetry_recorder = telemetry_recorder

    return app, registry, audit_writer, telemetry_recorder


@pytest.fixture
def tenant_a_headers():
    """Headers para tenant-a / actor-a."""
    register_static_credential("secret-a", "tenant-a", "actor-a", profile="owner-core")
    return {
        "Authorization": "Bearer secret-a",
        "X-Tenant-Id": "tenant-a",
        "X-Actor-Id": "actor-a",
        "X-Correlation-Id": "test-correlation-001",
    }


@pytest.fixture
def tenant_b_headers():
    """Headers para tenant-b / actor-b (sem grants por default)."""
    register_static_credential("secret-b", "tenant-b", "actor-b", profile="owner-core")
    return {
        "Authorization": "Bearer secret-b",
        "X-Tenant-Id": "tenant-b",
        "X-Actor-Id": "actor-b",
        "X-Correlation-Id": "test-correlation-002",
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
