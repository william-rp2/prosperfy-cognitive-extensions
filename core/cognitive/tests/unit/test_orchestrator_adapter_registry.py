"""
tests/unit/test_orchestrator_adapter_registry.py -- Track BH additive
multi-adapter dispatch in ExecutionOrchestrator (capability.adapter ->
adapter_registry[name], falls back to the single skills_adapter otherwise).

Goal: prove the Track BH change is 100% backward compatible (every existing
capability, unaware of adapter_registry, behaves exactly as before) AND
that browser.* capabilities really flow through BrowserAdapter over the
SAME Registry -> Grant -> Policy -> Adapter -> Audit pipeline as infra.*,
rather than a parallel reimplementation.
"""

from __future__ import annotations

from typing import Any

import pytest

from cognitive.audit.writer import InMemoryAuditWriter
from cognitive.contracts.tenancy import ActorContext, CapabilityGrant
from cognitive.execution.orchestrator import ExecutionOrchestrator
from cognitive.execution.resource_resolver import InMemoryResourceResolver
from cognitive.policy.engine import PolicyEngine
from cognitive.registry.registry import InMemoryCapabilityRegistry
from cognitive.telemetry.recorder import InMemoryTelemetryRecorder

TENANT = "tenant-bh"
PROFILE = "owner-core"


class RecordingAdapter:
    def __init__(self, label: str) -> None:
        self.label = label
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def invoke_tool(self, tool_name, arguments, tenant_id, correlation_id):
        self.calls.append((tool_name, dict(arguments)))
        return {"success": True, "pages": [], "label": self.label}

    async def health(self) -> bool:
        return True


def _ctx() -> ActorContext:
    return ActorContext(
        tenant_id=TENANT,
        actor_id="actor-bh",
        correlation_id="corr-bh",
        credential_ref="ref-bh",
        profile=PROFILE,
    )


def _build_orchestrator(*, skills_adapter, adapter_registry=None) -> ExecutionOrchestrator:
    registry = InMemoryCapabilityRegistry()
    registry.load_from_yaml()
    for capability_id in ("infra.inspect", "browser.read"):
        registry.register_grant(CapabilityGrant(
            tenant_id=TENANT, profile=PROFILE, capability_id=capability_id,
        ))
    resolver = InMemoryResourceResolver()
    resolver.register(TENANT, "prosperfy-main", {"host": "mock-vps.test", "type": "vps"})
    return ExecutionOrchestrator(
        registry=registry,
        policy_engine=PolicyEngine(),
        skills_adapter=skills_adapter,
        audit_writer=InMemoryAuditWriter(),
        telemetry_recorder=InMemoryTelemetryRecorder(),
        resource_resolver=resolver,
        adapter_registry=adapter_registry,
    )


@pytest.mark.asyncio
async def test_existing_capability_unaffected_when_adapter_registry_omitted():
    """Regression guard: infra.inspect must still hit skills_adapter exactly
    like before Track BH touched orchestrator.py."""
    skills = RecordingAdapter("skills")
    orchestrator = _build_orchestrator(skills_adapter=skills, adapter_registry=None)

    result = await orchestrator.execute(ctx=_ctx(), capability_id="infra.inspect", params={"resource": "prosperfy-main"})

    assert result.status.value == "completed"
    assert len(skills.calls) >= 1


@pytest.mark.asyncio
async def test_existing_capability_unaffected_when_registry_has_no_matching_entry():
    """adapter_registry provided but without 'prosperfy_skills' -> still
    falls back to skills_adapter (never a KeyError, never silently drops
    the call)."""
    skills = RecordingAdapter("skills")
    browser = RecordingAdapter("browser")
    orchestrator = _build_orchestrator(
        skills_adapter=skills, adapter_registry={"browser_harness": browser},
    )

    result = await orchestrator.execute(ctx=_ctx(), capability_id="infra.inspect", params={"resource": "prosperfy-main"})

    assert result.status.value == "completed"
    assert len(skills.calls) >= 1
    assert browser.calls == []


@pytest.mark.asyncio
async def test_browser_capability_dispatches_to_browser_adapter_not_skills():
    skills = RecordingAdapter("skills")
    browser = RecordingAdapter("browser")
    orchestrator = _build_orchestrator(
        skills_adapter=skills, adapter_registry={"browser_harness": browser},
    )

    result = await orchestrator.execute(
        ctx=_ctx(), capability_id="browser.read", params={"urls": ["https://example.com"]},
    )

    assert result.status.value == "completed", result.error
    assert len(browser.calls) == 1
    assert browser.calls[0][0] == "browser_read_links"
    assert skills.calls == []  # never touches the infra adapter


@pytest.mark.asyncio
async def test_browser_capability_falls_back_to_skills_adapter_without_registry():
    """No adapter_registry at all (None) -- browser.read still executes (via
    the default single-adapter fallback) instead of crashing. Documents the
    fallback explicitly rather than leaving it implicit."""
    skills = RecordingAdapter("skills")
    orchestrator = _build_orchestrator(skills_adapter=skills, adapter_registry=None)

    result = await orchestrator.execute(
        ctx=_ctx(), capability_id="browser.read", params={"urls": ["https://example.com"]},
    )

    assert result.status.value == "completed", result.error
    assert len(skills.calls) == 1
