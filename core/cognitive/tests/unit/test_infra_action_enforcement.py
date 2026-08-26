"""
tests/unit/test_infra_action_enforcement.py — Phase 1B Slice 1H.

Enforcement restart-only para infra.action no ExecutionOrchestrator.
ZERO MCP real — fake/recording adapter.
"""

from __future__ import annotations

from typing import Any

import pytest

from cognitive.audit.writer import InMemoryAuditWriter
from cognitive.contracts.tenancy import ActorContext, CapabilityGrant
from cognitive.adapters.prosperfy_skills.guard import (
    ForbiddenArgumentError,
    guard_arguments,
)
from cognitive.execution.orchestrator import (
    ExecutionOrchestrator,
    _build_infra_action_restart_plan,
)
from cognitive.execution.resource_resolver import InMemoryResourceResolver
from cognitive.policy.engine import PolicyEngine
from cognitive.registry.registry import InMemoryCapabilityRegistry
from cognitive.telemetry.recorder import InMemoryTelemetryRecorder

TENANT = "tenant-1b"
PROFILE = "hermes-homolog"
RESOLVED_HOST = "homolog-vps.prosperfy.com.br"
ALLOWED_RESOURCE = "prosperfy-vps-homolog"
INFRA_ACTION_TOOLS = [{"name": "prosperfy_vps_controlar_container", "args_from_resource": True, "required": True}]


class RecordingAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def invoke_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        tenant_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        self.calls.append((tool_name, dict(arguments)))
        return {"success": True, "data": {"ok": True}}

    async def health(self) -> bool:
        return True


def _ctx() -> ActorContext:
    return ActorContext(
        tenant_id=TENANT,
        actor_id="actor-1b",
        correlation_id="corr-1b",
        credential_ref="ref-1b",
        profile=PROFILE,
    )


def _valid_params(**overrides: Any) -> dict[str, Any]:
    base = {
        "resource": ALLOWED_RESOURCE,
        "action": "restart",
        "target_type": "container",
        "target": "omniroute",
    }
    base.update(overrides)
    return base


def _build_orchestrator(adapter: RecordingAdapter) -> ExecutionOrchestrator:
    registry = InMemoryCapabilityRegistry()
    registry.load_from_yaml()
    registry.register_grant(
        CapabilityGrant(
            tenant_id=TENANT,
            profile=PROFILE,
            capability_id="infra.action",
            policy_override="allow",
        ),
    )
    resolver = InMemoryResourceResolver()
    resolver.register(
        TENANT,
        ALLOWED_RESOURCE,
        {"host": RESOLVED_HOST, "type": "vps"},
    )
    for slug, host in (
        ("black", "black.example.com"),
        ("manager1", "manager1.example.com"),
        ("hostinger-one", "hostinger-one.example.com"),
        ("prosperfy-main", "main.example.com"),
    ):
        resolver.register(TENANT, slug, {"host": host, "type": "vps"})
    return ExecutionOrchestrator(
        registry=registry,
        policy_engine=PolicyEngine(),
        skills_adapter=adapter,
        audit_writer=InMemoryAuditWriter(),
        telemetry_recorder=InMemoryTelemetryRecorder(),
        resource_resolver=resolver,
    )


@pytest.mark.asyncio
async def test_infra_action_positive_restart_container():
    adapter = RecordingAdapter()
    orchestrator = _build_orchestrator(adapter)

    result = await orchestrator.execute(
        ctx=_ctx(),
        capability_id="infra.action",
        params=_valid_params(),
    )

    assert result.status.value == "completed"
    assert len(adapter.calls) == 1
    tool_name, tool_args = adapter.calls[0]
    assert tool_name == "prosperfy_vps_controlar_container"
    assert tool_args == {
        "host": RESOLVED_HOST,
        "container": "omniroute",
        "acao": "restart",
        "confirmar": True,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        _valid_params(action="start"),
        _valid_params(action="stop"),
        _valid_params(action="delete"),
        _valid_params(action="restart", target_type="server"),
        _valid_params(target=""),
        _valid_params(target="   "),
        _valid_params(resource="black"),
        _valid_params(resource="manager1"),
        _valid_params(resource="hostinger-one"),
        _valid_params(resource="prosperfy-main"),
    ],
    ids=[
        "action=start",
        "action=stop",
        "action=delete",
        "target_type=server",
        "target=empty",
        "target=whitespace",
        "resource=black",
        "resource=manager1",
        "resource=hostinger-one",
        "resource=prosperfy-main",
    ],
)
async def test_infra_action_deny_invalid_semantics(params: dict[str, Any]):
    adapter = RecordingAdapter()
    orchestrator = _build_orchestrator(adapter)

    result = await orchestrator.execute(
        ctx=_ctx(),
        capability_id="infra.action",
        params=params,
    )

    assert result.status.value == "failed"
    assert adapter.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra_key,extra_value",
    [
        ("acao", "stop"),
        ("acao", "restart"),
        ("confirmar", False),
        ("host", "evil.example.com"),
        ("token", "secret"),
        ("linhas", 100),
    ],
    ids=[
        "caller_acao=stop",
        "caller_acao=restart",
        "caller_confirmar=false",
        "caller_host",
        "caller_token",
        "caller_linhas",
    ],
)
async def test_infra_action_rejects_caller_mcp_fields(extra_key: str, extra_value: Any):
    adapter = RecordingAdapter()
    orchestrator = _build_orchestrator(adapter)
    params = _valid_params(**{extra_key: extra_value})

    result = await orchestrator.execute(
        ctx=_ctx(),
        capability_id="infra.action",
        params=params,
    )

    assert result.status.value == "failed"
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_infra_action_missing_resolved_resource_no_adapter():
    adapter = RecordingAdapter()
    orchestrator = _build_orchestrator(adapter)

    with pytest.raises(ForbiddenArgumentError):
        await orchestrator._run_capability_tools(
            capability_id="infra.action",
            tools=INFRA_ACTION_TOOLS,
            params=_valid_params(),
            tenant_id=TENANT,
            correlation_id="corr-x",
        )
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_infra_action_missing_host_in_resolved_no_adapter():
    adapter = RecordingAdapter()
    orchestrator = _build_orchestrator(adapter)
    params = _valid_params(
        _resolved_resource={"type": "vps"},
    )

    with pytest.raises(ForbiddenArgumentError):
        await orchestrator._run_capability_tools(
            capability_id="infra.action",
            tools=INFRA_ACTION_TOOLS,
            params=params,
            tenant_id=TENANT,
            correlation_id="corr-x",
        )
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_infra_action_wrong_tool_in_yaml_no_adapter():
    adapter = RecordingAdapter()
    orchestrator = _build_orchestrator(adapter)
    params = _valid_params(
        _resolved_resource={"host": RESOLVED_HOST, "type": "vps"},
    )
    wrong_tools = [{"name": "prosperfy_vps_panorama", "args_from_resource": True}]

    with pytest.raises(ForbiddenArgumentError):
        await orchestrator._run_capability_tools(
            capability_id="infra.action",
            tools=wrong_tools,
            params=params,
            tenant_id=TENANT,
            correlation_id="corr-x",
        )
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_infra_action_two_tools_configured_no_adapter():
    adapter = RecordingAdapter()
    orchestrator = _build_orchestrator(adapter)
    params = _valid_params(
        _resolved_resource={"host": RESOLVED_HOST, "type": "vps"},
    )
    two_tools = [
        {"name": "prosperfy_vps_controlar_container", "args_from_resource": True},
        {"name": "prosperfy_vps_panorama", "args_from_resource": True},
    ]

    with pytest.raises(ForbiddenArgumentError):
        await orchestrator._run_capability_tools(
            capability_id="infra.action",
            tools=two_tools,
            params=params,
            tenant_id=TENANT,
            correlation_id="corr-x",
        )
    assert adapter.calls == []


def test_build_infra_action_restart_plan_exact_args():
    params = _valid_params(
        _resolved_resource={"host": RESOLVED_HOST, "type": "vps"},
    )
    tool_name, tool_args = _build_infra_action_restart_plan(params, INFRA_ACTION_TOOLS)
    assert tool_name == "prosperfy_vps_controlar_container"
    assert tool_args == {
        "host": RESOLVED_HOST,
        "container": "omniroute",
        "acao": "restart",
        "confirmar": True,
    }
    assert "resource" not in tool_args
    assert "action" not in tool_args


@pytest.mark.asyncio
async def test_infra_inspect_regression_unchanged():
    """infra.inspect continua no fluxo genérico — sem regressão."""
    adapter = RecordingAdapter()
    registry = InMemoryCapabilityRegistry()
    registry.load_from_yaml()
    registry.register_grant(
        CapabilityGrant(tenant_id=TENANT, profile=PROFILE, capability_id="infra.inspect"),
    )
    resolver = InMemoryResourceResolver()
    resolver.register(TENANT, "prosperfy-main", {"host": "main.example.com", "type": "vps"})
    orchestrator = ExecutionOrchestrator(
        registry=registry,
        policy_engine=PolicyEngine(),
        skills_adapter=adapter,
        audit_writer=InMemoryAuditWriter(),
        telemetry_recorder=InMemoryTelemetryRecorder(),
        resource_resolver=resolver,
    )

    result = await orchestrator.execute(
        ctx=_ctx(),
        capability_id="infra.inspect",
        params={"resource": "prosperfy-main"},
    )

    assert result.status.value == "completed"
    assert len(adapter.calls) == 3
    assert all(name != "prosperfy_vps_controlar_container" for name, _ in adapter.calls)
