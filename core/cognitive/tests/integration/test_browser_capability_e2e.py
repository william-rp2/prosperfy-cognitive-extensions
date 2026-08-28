"""
tests/integration/test_browser_capability_e2e.py -- Track BH, full HTTP path.

Mirrors tests/integration/test_gateway_execute.py's pattern but wires an
explicit adapter_registry={"browser_harness": ...} into the orchestrator
(conftest.py's app_and_services fixture does not exercise Track BH's
adapter dispatch, since it predates it), so this is the one test that
proves the WHOLE chain for real over HTTP: request -> auth -> grant ->
PolicyEngine -> ExecutionOrchestrator._resolve_adapter("browser_harness")
-> BrowserAdapter (recording double here) -> audit_events written with the
URL visible and no secret field, exactly as capability.audit_rules /
redaction_rules declare in browser.read.yaml / browser.act.yaml.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from cognitive.adapters.browser_harness.guard import BrowserToolError
from cognitive.adapters.prosperfy_skills.mock import MockSkillsAdapter
from cognitive.audit.writer import InMemoryAuditWriter
from cognitive.contracts.audit import AuditOutcome
from cognitive.contracts.tenancy import CapabilityGrant
from cognitive.execution.orchestrator import ExecutionOrchestrator
from cognitive.execution.resource_resolver import InMemoryResourceResolver
from cognitive.gateway.app import create_app
from cognitive.policy.engine import PolicyEngine
from cognitive.registry.registry import InMemoryCapabilityRegistry
from cognitive.telemetry.recorder import InMemoryTelemetryRecorder
from cognitive.tenancy.identity_resolver import IdentityResolver


class RecordingBrowserAdapter:
    """Stands in for BrowserAdapter -- records calls, never touches network."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def invoke_tool(self, tool_name, arguments, tenant_id, correlation_id):
        from cognitive.adapters.browser_harness.guard import guard_browser_tool
        guard_browser_tool(tool_name, arguments)
        self.calls.append((tool_name, dict(arguments)))
        return {
            "success": True,
            "pages": [{"url": u, "fetched_via": "fetch", "title": "t", "text": "body"} for u in arguments.get("urls", [])],
            "job_id": "e2e-job", "correlation_id": correlation_id,
        }

    async def health(self) -> bool:
        return True


@pytest.fixture
def browser_client():
    os.environ["COGNITIVE_MODE"] = "in_memory"
    os.environ.pop("COGNITIVE_DB_URL", None)
    os.environ["COGNITIVE_GATEWAY_CREDENTIAL"] = "__disabled_in_test__"

    registry = InMemoryCapabilityRegistry()
    registry.load_from_yaml()
    registry.register_grant(CapabilityGrant(
        tenant_id="tenant-a", profile="owner-core", capability_id="browser.read",
    ))

    audit_writer = InMemoryAuditWriter()
    telemetry_recorder = InMemoryTelemetryRecorder()
    skills_adapter = MockSkillsAdapter()
    browser_adapter = RecordingBrowserAdapter()

    identity_resolver = IdentityResolver(identity_repo=None)
    identity_resolver.register_static("secret-a", "tenant-a", "actor-a", "owner-core")

    resource_resolver = InMemoryResourceResolver()

    orchestrator = ExecutionOrchestrator(
        registry=registry,
        policy_engine=PolicyEngine(),
        skills_adapter=skills_adapter,
        audit_writer=audit_writer,
        telemetry_recorder=telemetry_recorder,
        resource_resolver=resource_resolver,
        adapter_registry={"browser_harness": browser_adapter},
    )

    app = create_app()
    app.state.registry = registry
    app.state.orchestrator = orchestrator
    app.state.audit_writer = audit_writer
    app.state.telemetry_recorder = telemetry_recorder
    app.state.identity_resolver = identity_resolver
    app.state.resource_resolver = resource_resolver
    app.state.use_db = False

    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, audit_writer, browser_adapter, skills_adapter


HEADERS_A = {
    "Authorization": "Bearer secret-a",
    "X-Tenant-Id": "tenant-a",
    "X-Actor-Id": "actor-a",
    "X-Correlation-Id": "corr-browser-e2e-1",
}


def test_browser_read_dispatches_to_browser_adapter_over_http(browser_client):
    client, audit_writer, browser_adapter, skills_adapter = browser_client

    r = client.post(
        "/v1/capabilities/browser.read/execute",
        json={"params": {"urls": ["https://example.com/doc"]}},
        headers=HEADERS_A,
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"

    # Dispatched to the BROWSER adapter, never the infra one.
    assert len(browser_adapter.calls) == 1
    assert browser_adapter.calls[0][0] == "browser_read_links"
    assert skills_adapter is not None  # sanity: fixture wiring intact


def test_browser_read_audit_event_shows_url_and_no_secret(browser_client):
    """doc 00 Sec.7: audit deve mostrar URL host / acao / resultado / duracao
    / correlation id -- e nunca conteudo secreto (redaction_rules do YAML)."""
    client, audit_writer, browser_adapter, _ = browser_client

    client.post(
        "/v1/capabilities/browser.read/execute",
        json={"params": {"urls": ["https://example.com/doc"]}},
        headers=HEADERS_A,
    )

    events = audit_writer.get_all_for_tenant("tenant-a")
    assert len(events) == 1
    event = events[0]
    assert event.capability_id == "browser.read"
    assert event.correlation_id == "corr-browser-e2e-1"
    assert event.outcome == AuditOutcome.COMPLETED
    assert event.duration_ms >= 0
    # URL/host is not a secret -- must stay visible for operators.
    assert "example.com" in str(event.inputs_redacted)
    # None of the redacted field names ever appear with a real value attached.
    for secret_field in ("password", "token", "secret", "cookie", "authorization"):
        assert secret_field not in event.inputs_redacted


def test_browser_read_denied_without_grant(browser_client):
    client, audit_writer, browser_adapter, _ = browser_client
    headers_no_grant = {**HEADERS_A, "X-Tenant-Id": "tenant-without-grant", "Authorization": "Bearer secret-a"}
    # tenant-without-grant has no identity registered -> 401, proving the
    # gate runs before any grant/adapter logic (same as existing infra tests).
    r = client.post(
        "/v1/capabilities/browser.read/execute",
        json={"params": {"urls": ["https://example.com"]}},
        headers=headers_no_grant,
    )
    assert r.status_code == 401
    assert browser_adapter.calls == []


@pytest.mark.asyncio
async def test_browser_act_unknown_tool_never_reaches_worker(browser_client):
    """Defense in depth: even if something upstream mis-shapes the call, the
    BrowserAdapter guard rejects it before any (would-be) transport call."""
    _, _, browser_adapter, _ = browser_client
    with pytest.raises(BrowserToolError):
        await browser_adapter.invoke_tool("shell_exec", {"cmd": "rm -rf /"}, "tenant-a", "c-1")
    assert browser_adapter.calls == []
