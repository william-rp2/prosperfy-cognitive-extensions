"""
tests/unit/test_routing_skills_adapter.py — P2 (Financeiro pelo WhatsApp).

RoutingSkillsAdapter (cognitive/adapters/routing.py) lets ExecutionOrchestrator
keep injecting a single SkillsAdapterPort while finance.* is actually served
by a different concrete adapter (HTTP) than everything else (MCP).
"""

from __future__ import annotations

from typing import Any

from cognitive.adapters.routing import RoutingSkillsAdapter


class RecordingAdapter:
    def __init__(self, name: str, healthy: bool = True) -> None:
        self.name = name
        self.healthy = healthy
        self.calls: list[str] = []

    async def invoke_tool(self, tool_name: str, arguments: dict[str, Any], tenant_id: str, correlation_id: str) -> dict[str, Any]:
        self.calls.append(tool_name)
        return {"success": True, "data": {"handled_by": self.name}}

    async def health(self) -> bool:
        return self.healthy


async def test_prefix_match_routes_to_the_mapped_adapter():
    default = RecordingAdapter("default")
    finance = RecordingAdapter("finance")
    router = RoutingSkillsAdapter(default_adapter=default, routes={"finance.": finance})

    result = await router.invoke_tool("finance.summary.read", {}, "tenant-1", "corr-1")

    assert result["data"]["handled_by"] == "finance"
    assert finance.calls == ["finance.summary.read"]
    assert default.calls == []


async def test_no_prefix_match_falls_back_to_default():
    default = RecordingAdapter("default")
    finance = RecordingAdapter("finance")
    router = RoutingSkillsAdapter(default_adapter=default, routes={"finance.": finance})

    result = await router.invoke_tool("infra.inspect", {}, "tenant-1", "corr-1")

    assert result["data"]["handled_by"] == "default"
    assert default.calls == ["infra.inspect"]
    assert finance.calls == []


async def test_empty_routes_always_uses_default():
    default = RecordingAdapter("default")
    router = RoutingSkillsAdapter(default_adapter=default, routes=None)

    result = await router.invoke_tool("finance.summary.read", {}, "tenant-1", "corr-1")

    assert result["data"]["handled_by"] == "default"


async def test_health_is_true_only_when_every_routed_adapter_is_healthy():
    healthy_router = RoutingSkillsAdapter(
        default_adapter=RecordingAdapter("default"),
        routes={"finance.": RecordingAdapter("finance")},
    )
    assert await healthy_router.health() is True

    unhealthy_finance_router = RoutingSkillsAdapter(
        default_adapter=RecordingAdapter("default"),
        routes={"finance.": RecordingAdapter("finance", healthy=False)},
    )
    assert await unhealthy_finance_router.health() is False

    unhealthy_default_router = RoutingSkillsAdapter(
        default_adapter=RecordingAdapter("default", healthy=False),
        routes={"finance.": RecordingAdapter("finance")},
    )
    assert await unhealthy_default_router.health() is False
