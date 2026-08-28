"""
adapters/browser_harness/mock.py -- MockBrowserAdapter para testes e CI.

Default em CI/dev (COGNITIVE_LIVE_MCP != "1"). Nao chama prosperfy_vps_* nem
o Browser Worker remoto. Respostas deterministicas por tool_name, mesma
guarda (guard_browser_tool) que o adapter real -- payload malformado e
rejeitado igual em mock e em producao.
"""

from __future__ import annotations

import logging
from typing import Any

from .guard import guard_browser_tool

logger = logging.getLogger(__name__)


class MockBrowserAdapter:
    """Implementa SkillsAdapterPort sem tocar o Browser Worker real."""

    async def invoke_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        tenant_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        guard_browser_tool(tool_name, arguments)
        logger.debug(
            "MockBrowserAdapter.invoke_tool tool=%s tenant=%s correlation=%s",
            tool_name, tenant_id, correlation_id,
        )
        if tool_name == "browser_read_links":
            pages = [
                {"url": u, "fetched_via": "fetch", "title": "mock title", "text": "mock text", "error": None}
                for u in arguments.get("urls", [])
            ]
            return {"success": True, "pages": pages, "job_id": "mock-job", "correlation_id": correlation_id}
        if tool_name == "browser_doctor":
            return {"success": True, "chrome_reachable": True, "detail": "mock"}
        if tool_name in ("browser_fill_form", "browser_create_account"):
            return {
                "success": True,
                "submitted": bool(arguments.get("submit")),
                "blocked_reason": None,
                "secret_aliases_used": [
                    v.split(":", 1)[1]
                    for v in (arguments.get("fields") or {}).values()
                    if isinstance(v, str) and v.startswith("secret_ref:")
                ],
                "job_id": "mock-job",
                "correlation_id": correlation_id,
            }
        return {"success": True, "data": {"mock": True, "tool": tool_name}}

    async def health(self) -> bool:
        return True
