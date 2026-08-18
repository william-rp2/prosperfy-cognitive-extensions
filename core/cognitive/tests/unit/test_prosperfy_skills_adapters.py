"""
tests/unit/test_prosperfy_skills_adapters.py — MockSkillsAdapter e ProsperfySkillsAdapter (Sprint 0.3).

Cobre:
- guard aplicada em ambos os adapters (mock e real)
- real adapter nunca abre conexão de rede antes da guard rejeitar
- erros HTTP/transporte do adapter real são sanitizados (não vazam corpo/headers upstream)
- seleção de adapter via COGNITIVE_LIVE_MCP no gateway (default OFF)
"""

from __future__ import annotations

import os

import httpx
import pytest

from cognitive.adapters.prosperfy_skills.client import ProsperfySkillsAdapter
from cognitive.adapters.prosperfy_skills.guard import ForbiddenArgumentError
from cognitive.adapters.prosperfy_skills.mock import MockSkillsAdapter
from cognitive.gateway.app import create_app


# ─── MockSkillsAdapter ────────────────────────────────────────────────────

class TestMockSkillsAdapterGuard:
    @pytest.mark.asyncio
    async def test_forbidden_command_rejected(self):
        adapter = MockSkillsAdapter()
        with pytest.raises(ForbiddenArgumentError):
            await adapter.invoke_tool(
                tool_name="prosperfy_vps_panorama",
                arguments={"resource": "prosperfy-main", "command": "rm -rf /"},
                tenant_id="tenant-a",
                correlation_id="corr-1",
            )

    @pytest.mark.asyncio
    async def test_malformed_resource_rejected(self):
        adapter = MockSkillsAdapter()
        with pytest.raises(ForbiddenArgumentError):
            await adapter.invoke_tool(
                tool_name="prosperfy_vps_panorama",
                arguments={"resource": "192.168.1.1"},
                tenant_id="tenant-a",
                correlation_id="corr-1",
            )

    @pytest.mark.asyncio
    async def test_valid_call_returns_mock_data(self):
        adapter = MockSkillsAdapter()
        result = await adapter.invoke_tool(
            tool_name="prosperfy_vps_panorama",
            arguments={"resource": "prosperfy-main"},
            tenant_id="tenant-a",
            correlation_id="corr-1",
        )
        assert result["success"] is True
        assert "uptime_seconds" in result["data"]

    @pytest.mark.asyncio
    async def test_health_always_true_no_network(self):
        adapter = MockSkillsAdapter()
        assert await adapter.health() is True


# ─── ProsperfySkillsAdapter (real, mas sem rede nestes testes) ────────────

class _ExplodingAsyncClient:
    """Substitui httpx.AsyncClient para provar que nenhuma conexão é aberta."""

    def __init__(self, *args, **kwargs):
        raise AssertionError(
            "httpx.AsyncClient foi instanciado — a guard deveria ter bloqueado "
            "ANTES de qualquer tentativa de rede"
        )


class TestProsperfySkillsAdapterGuardBlocksBeforeNetwork:
    @pytest.mark.asyncio
    async def test_forbidden_command_blocked_before_any_network_call(self, monkeypatch):
        monkeypatch.setattr(httpx, "AsyncClient", _ExplodingAsyncClient)
        adapter = ProsperfySkillsAdapter(api_key="fake-key", host="skills.invalid.test")
        with pytest.raises(ForbiddenArgumentError):
            await adapter.invoke_tool(
                tool_name="prosperfy_vps_panorama",
                arguments={"resource": "prosperfy-main", "shell": "/bin/sh"},
                tenant_id="tenant-a",
                correlation_id="corr-1",
            )

    @pytest.mark.asyncio
    async def test_malformed_resource_blocked_before_any_network_call(self, monkeypatch):
        monkeypatch.setattr(httpx, "AsyncClient", _ExplodingAsyncClient)
        adapter = ProsperfySkillsAdapter(api_key="fake-key", host="skills.invalid.test")
        with pytest.raises(ForbiddenArgumentError):
            await adapter.invoke_tool(
                tool_name="prosperfy_vps_panorama",
                arguments={"resource": "10.0.0.5"},
                tenant_id="tenant-a",
                correlation_id="corr-1",
            )

    @pytest.mark.asyncio
    async def test_missing_api_key_rejected_before_network(self, monkeypatch):
        monkeypatch.setattr(httpx, "AsyncClient", _ExplodingAsyncClient)
        monkeypatch.delenv("MCP_PROSPERFYSKILLS_API_KEY", raising=False)
        adapter = ProsperfySkillsAdapter(api_key="", host="skills.invalid.test")
        with pytest.raises(RuntimeError, match="API_KEY"):
            await adapter.invoke_tool(
                tool_name="prosperfy_vps_panorama",
                arguments={"resource": "prosperfy-main"},
                tenant_id="tenant-a",
                correlation_id="corr-1",
            )


class TestProsperfySkillsAdapterErrorSanitization:
    @pytest.mark.asyncio
    async def test_http_status_error_sanitized(self, monkeypatch):
        """Erro HTTP do upstream (com corpo sensível) não deve vazar para o chamador."""
        secret_body = "internal-trace-id=xyz api_key=LEAKED-SECRET-VALUE stacktrace: ..."

        class _FakeResponse:
            status_code = 500
            text = secret_body

            def raise_for_status(self):
                request = httpx.Request("POST", "https://skills.invalid.test/mcp/tools/call")
                response = httpx.Response(500, text=secret_body, request=request)
                raise httpx.HTTPStatusError("server error", request=request, response=response)

            def json(self):
                return {}

        class _FakeAsyncClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *a, **kw):
                return _FakeResponse()

        monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
        adapter = ProsperfySkillsAdapter(api_key="fake-key", host="skills.invalid.test")

        with pytest.raises(RuntimeError) as excinfo:
            await adapter.invoke_tool(
                tool_name="prosperfy_vps_panorama",
                arguments={"resource": "prosperfy-main"},
                tenant_id="tenant-a",
                correlation_id="corr-1",
            )

        message = str(excinfo.value)
        assert "LEAKED-SECRET-VALUE" not in message
        assert "internal-trace-id" not in message
        assert "fake-key" not in message

    @pytest.mark.asyncio
    async def test_transport_error_sanitized(self, monkeypatch):
        class _FakeAsyncClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *a, **kw):
                raise httpx.ConnectTimeout("connect timed out to internal-host-1.prosperfy.internal")

        monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
        adapter = ProsperfySkillsAdapter(api_key="fake-key", host="skills.invalid.test")

        with pytest.raises(RuntimeError) as excinfo:
            await adapter.invoke_tool(
                tool_name="prosperfy_vps_panorama",
                arguments={"resource": "prosperfy-main"},
                tenant_id="tenant-a",
                correlation_id="corr-1",
            )
        assert "fake-key" not in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_health_never_raises(self, monkeypatch):
        class _RaisingAsyncClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **kw):
                raise httpx.ConnectError("boom")

        monkeypatch.setattr(httpx, "AsyncClient", _RaisingAsyncClient)
        adapter = ProsperfySkillsAdapter(api_key="fake-key", host="skills.invalid.test")
        assert await adapter.health() is False


# ─── COGNITIVE_LIVE_MCP selection (gateway/app.py) ────────────────────────

class TestLiveMcpAdapterSelection:
    def _build_app_in_memory(self, monkeypatch, live_mcp: str | None):
        monkeypatch.setenv("COGNITIVE_MODE", "in_memory")
        monkeypatch.delenv("COGNITIVE_DB_URL", raising=False)
        monkeypatch.delenv("COGNITIVE_DB_ADMIN_URL", raising=False)
        monkeypatch.delenv("COGNITIVE_DB_WORKER_URL", raising=False)
        if live_mcp is None:
            monkeypatch.delenv("COGNITIVE_LIVE_MCP", raising=False)
        else:
            monkeypatch.setenv("COGNITIVE_LIVE_MCP", live_mcp)
        return create_app()

    def test_default_unset_uses_mock_adapter(self, monkeypatch):
        app = self._build_app_in_memory(monkeypatch, live_mcp=None)
        assert isinstance(app.state.orchestrator._adapter, MockSkillsAdapter)

    def test_explicit_zero_uses_mock_adapter(self, monkeypatch):
        app = self._build_app_in_memory(monkeypatch, live_mcp="0")
        assert isinstance(app.state.orchestrator._adapter, MockSkillsAdapter)

    def test_explicit_one_uses_real_adapter_no_network_at_construction(self, monkeypatch):
        """LIVE_MCP=1 instancia o adapter real — sem qualquer chamada de rede na construção."""
        monkeypatch.setattr(httpx, "AsyncClient", _ExplodingAsyncClient)
        app = self._build_app_in_memory(monkeypatch, live_mcp="1")
        assert isinstance(app.state.orchestrator._adapter, ProsperfySkillsAdapter)

    def test_any_other_value_falls_back_to_mock(self, monkeypatch):
        app = self._build_app_in_memory(monkeypatch, live_mcp="true")
        assert isinstance(app.state.orchestrator._adapter, MockSkillsAdapter)
