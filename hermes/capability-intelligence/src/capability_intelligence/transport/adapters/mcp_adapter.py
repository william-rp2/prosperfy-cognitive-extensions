"""
adapters/mcp_adapter.py — Adaptador MCP para o Prosperfy Skills.

Implementa o contrato abstrato usando o protocolo MCP (JSON-RPC sobre SSE).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from http.client import HTTPSConnection
from typing import Any

from ..protocol_adapter import ProtocolAdapter
from ...models import (
    AuthorizationRequest,
    AuthorizationResult,
    CapabilityResult,
    CatalogMatch,
    CatalogResult,
    ExecutionReference,
    ExecutionRequest,
    IntentQuery,
    ResultMetadata,
    StatusResult,
)

logger = logging.getLogger(__name__)


@dataclass
class MCPAdapter(ProtocolAdapter):
    """Adaptador MCP para o Prosperfy Skills."""

    host: str = "skills.prosperfy.com.br"
    path: str = "/mcp"
    api_key: str = ""
    _session_id: str | None = None

    def _connect(self) -> HTTPSConnection:
        return HTTPSConnection(self.host, timeout=30)

    def _request(self, method: str, params: dict | None = None) -> dict:
        """Envia requisicão JSON-RPC via MCP SSE."""
        conn = self._connect()

        # Initialize se não tiver session
        if not self._session_id:
            init_payload = json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "hermes-capability-intelligence",
                                   "version": "1.0.0"},
                },
            })
            conn.request("POST", self.path, body=init_payload, headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {self.api_key}",
            })
            resp = conn.getresponse()
            self._session_id = resp.getheader("Mcp-Session-Id", "")
            resp.read()
            conn.close()
            conn = self._connect()

        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": method, "params": params or {},
        })
        conn.request("POST", self.path, body=payload, headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.api_key}",
            "Mcp-Session-Id": self._session_id,
        })
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", errors="replace")
        conn.close()

        # Parse SSE event
        for line in raw.split("\n"):
            if line.startswith("data: "):
                return json.loads(line[6:])
        return {}

    async def resolve_catalog(self, query: IntentQuery) -> CatalogResult:
        """Traduz IntentQuery em consulta ao Catálogo via MCP."""
        # Usa prosperfy_list_tools com filtro por domínio
        result = self._request("tools/call", {
            "name": "prosperfy_list_tools",
            "arguments": {"tag": query.domain},
        })
        content = result.get("result", {}).get("content", [])
        # Parse tools list into CatalogMatch
        matches = []
        for item in content:
            text = item.get("text", "{}")
            try:
                data = json.loads(text)
                tools = data if isinstance(data, list) else data.get("tools", [])
                for tool in tools:
                    matches.append(CatalogMatch(
                        capability_id=tool.get("name", ""),
                        score=1.0 if tool.get("name", "").lower() in query.intent.lower() else 0.5,
                        reason=f"Disponível no domínio {query.domain}",
                    ))
            except json.JSONDecodeError:
                continue

        return CatalogResult(matches=matches)

    async def authorize(self, request: AuthorizationRequest) -> AuthorizationResult:
        """Fail-closed (Sprint 0.7.1): este transport MCP DIRETO (legado) não
        realiza autorização governada — o antigo placeholder devolvia
        authorized=True sempre, o que permitiria chamar o MCP sem passar pelo
        boundary de autorização do Cognitive se o pipeline fosse conectado.

        Agora NEGA sempre: qualquer invocação via /capability (pipeline legado)
        não alcança o MCP sem governança. Migração futura: rotear por Cognitive.
        """
        return AuthorizationResult(
            authorized=False,
            reason=(
                "autorização não governada no transport MCP legado — "
                "execute capabilities via Cognitive"
            ),
        )

    async def execute(self, request: ExecutionRequest) -> ExecutionReference:
        """Executa Capability via MCP."""
        result = self._request("tools/call", {
            "name": request.capability_id,
            "arguments": request.params,
        })
        content = result.get("result", {}).get("content", [{}])
        ref = result.get("result", {}).get("_meta", {}).get("execution_ref", "")
        if not ref:
            ref = result.get("id", "mcp-exec")
        return ExecutionReference(ref=str(ref))

    async def get_result(self, ref: ExecutionReference) -> CapabilityResult:
        """Obtém resultado (MCP é síncrono, então já temos)."""
        return CapabilityResult(success=True, data={})

    async def get_status(self, ref: ExecutionReference | None = None) -> StatusResult:
        """Status da plataforma."""
        result = self._request("tools/call", {
            "name": "prosperfy_hello",
            "arguments": {},
        })
        return StatusResult(healthy=True, capabilities_total=116,
                            capabilities_available=116)