"""
tests/unit/test_mcp_extra_kwarg_rejected.py — Sprint 0.3 HOTFIX, regressão.

Replica, 100% offline (sem rede), a mecânica exata do servidor ProsperfySkill
(FastMCP 3.x) que causou o 'PROSPERFY_VPS_PANORAMA RETURNED MCP
PROTOCOL-LEVEL ERROR' no live gate: o orquestrador repassava 'type'
(metadado do resource resolvido, que vive no JSONB de resolved_params) como
argumento de tool MCP. O FastMCP valida arguments contra a assinatura da tool
e rejeita qualquer chave fora do schema (pydantic 'Unexpected keyword
argument') — a chamada vira CallToolResult com isError=True e o adapter
levanta 'erro de protocolo MCP'.

O fix remove metadados no orquestrador (orchestrator.py,
_RESOURCE_METADATA_NOT_TOOL_ARG_KEYS). Estes testes documentam o invariante
do servidor que justifica o fix e, como controle, provam que os MESMOS
argumentos sem a chave de metadados executam com sucesso.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

import fastmcp


def _build_server() -> fastmcp.FastMCP:
    server = fastmcp.FastMCP("sprint-0.3-hotfix-repro")

    @server.tool()
    def prosperfy_vps_panorama(
        host: str,
        token: str | None = None,
        porta: int | None = None,
        incluir_parados: bool | None = None,
    ) -> dict:
        return {"status": "ok", "data": {"host": host, "uptime_seconds": 1}}

    return server


@pytest.mark.asyncio
async def test_extra_metadata_key_is_rejected_by_fastmcp_server():
    """'type' (metadado do resource) fora do schema da tool é rejeitado pelo
    FastMCP com 'Unexpected keyword argument' — causa raiz do 'erro de
    protocolo MCP' do gate."""
    server = _build_server()

    with pytest.raises(ValidationError) as excinfo:
        await server.call_tool(
            "prosperfy_vps_panorama",
            {"host": "mock-vps.test", "type": "vps"},
        )

    message = str(excinfo.value)
    assert "Unexpected keyword argument" in message
    assert "type" in message


@pytest.mark.asyncio
async def test_clean_tool_args_succeed_on_fastmcp_server():
    """Controle do fix: os mesmos argumentos sem a chave de metadados executam
    com sucesso no servidor."""
    server = _build_server()

    result = await server.call_tool(
        "prosperfy_vps_panorama",
        {"host": "mock-vps.test"},
    )

    assert result.structured_content is not None
    assert result.structured_content.get("status") == "ok"