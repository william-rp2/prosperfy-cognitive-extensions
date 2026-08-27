"""
adapters/composio/mock.py — MockComposioAdapter para testes e CI.

Default em CI (COGNITIVE_LIVE_COMPOSIO_MCP != "1"). Não faz chamadas HTTP
reais. Aplica o MESMO guard.py do adapter real (mesmo contrato de segurança
em CI e produção — allowlist de tool_name + argumentos, SQL arbitrário
sempre rejeitado).
"""

from __future__ import annotations

import logging
from typing import Any

from .guard import guard_arguments

logger = logging.getLogger(__name__)

_MOCK_PROJECTS = [
    {"id": "wioorhtdwnfujkrynxij", "ref": "wioorhtdwnfujkrynxij", "name": "Hermes",
     "region": "sa-east-1", "status": "ACTIVE_HEALTHY", "organization_id": "mock-org"},
    {"id": "esvjfkknrzzziafovwrv", "ref": "esvjfkknrzzziafovwrv", "name": "Prosperfy Cognitive Homolog",
     "region": "sa-east-1", "status": "ACTIVE_HEALTHY", "organization_id": "mock-org"},
]


def _mock_response(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "SUPABASE_RUN_READ_ONLY_QUERY":
        query = arguments.get("query", "").strip().lower()
        if query.rstrip(";") == "select now()":
            return {"result": [{"now": "2026-08-27T00:00:00+00:00"}], "rows_returned": 1}
        return {"result": [{"?column?": 1}], "rows_returned": 1}
    if tool_name == "SUPABASE_GET_PROJECT":
        ref = arguments.get("ref")
        match = next((p for p in _MOCK_PROJECTS if p["ref"] == ref), _MOCK_PROJECTS[0])
        return dict(match)
    if tool_name == "SUPABASE_LIST_ALL_PROJECTS":
        return {"details": [dict(p) for p in _MOCK_PROJECTS]}
    if tool_name == "SUPABASE_LIST_ALL_ORGANIZATIONS":
        return {"details": [{"id": "mock-org", "name": "Mock Org", "slug": "mock-org"}]}
    if tool_name == "SUPABASE_GETS_PROJECT_S_SERVICE_HEALTH_STATUS":
        return {"services": [{"name": "db", "healthy": True, "status": "ACTIVE_HEALTHY"}]}
    return {"mock": True, "tool": tool_name}


class MockComposioAdapter:
    """Adapter mock para o Compose MCP. Implementa SkillsAdapterPort sem HTTP real."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def invoke_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        tenant_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        composio_args = {k: v for k, v in arguments.items() if k != "account"}
        guard_arguments(tool_name, composio_args)

        logger.debug(
            "MockComposioAdapter.invoke_tool tool=%s tenant=%s correlation=%s",
            tool_name, tenant_id, correlation_id,
        )
        self.calls.append((tool_name, dict(arguments)))
        return {"success": True, "data": _mock_response(tool_name, composio_args)}

    async def health(self) -> bool:
        return True
