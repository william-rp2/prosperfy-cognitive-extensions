"""
adapters/prosperfy_skills/mock.py — MockSkillsAdapter para testes e CI.

Default em CI (COGNITIVE_LIVE_MCP != "1").
Não faz chamadas HTTP reais. Retorna respostas determinísticas por tool_name.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Respostas mock por tool_name
_MOCK_RESPONSES: dict[str, dict[str, Any]] = {
    "prosperfy_vps_panorama": {
        "status": "ok",
        "host": "mock-host",
        "uptime_seconds": 86400,
        "load_avg": [0.1, 0.2, 0.3],
    },
    "prosperfy_vps_listar_containers": {
        "containers": [
            {"name": "cognitive-api", "status": "running", "image": "prosperfy/cognitive:latest"},
            {"name": "postgres", "status": "running", "image": "postgres:16"},
        ]
    },
    "prosperfy_vps_verificar_portas": {
        "ports": {
            "8800": "open",
            "5432": "open",
            "80": "open",
        }
    },
    "prosperfy_vps_status_servico": {
        "service": "mock-service",
        "status": "active",
        "since": "2026-08-16T00:00:00Z",
    },
    "prosperfy_hello": {
        "message": "Hello from MockSkillsAdapter",
    },
}


class MockSkillsAdapter:
    """
    Adapter mock para ProsperfySkill.

    Implementa a interface de SkillsAdapterPort sem chamadas HTTP.
    Usado por padrão em testes e quando COGNITIVE_LIVE_MCP != "1".
    """

    async def invoke_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        tenant_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        logger.debug(
            "MockSkillsAdapter.invoke_tool tool=%s tenant=%s correlation=%s",
            tool_name, tenant_id, correlation_id,
        )
        response = _MOCK_RESPONSES.get(tool_name, {"mock": True, "tool": tool_name})
        return {"success": True, "data": response}

    async def health(self) -> bool:
        return True
