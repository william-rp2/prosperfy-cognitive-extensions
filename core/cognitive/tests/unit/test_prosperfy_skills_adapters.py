"""
tests/unit/test_prosperfy_skills_adapters.py — MockSkillsAdapter e ProsperfySkillsAdapter (Sprint 0.3).

Cobre:
- guard aplicada em ambos os adapters (mock e real)
- real adapter nunca abre conexão de rede antes da guard rejeitar
- invoke_tool real (fastmcp.Client, MCP real via Streamable HTTP) trata
  separadamente:
  - sucesso normal (retorna {"success": True, "data": <payload>})
  - erro de protocolo MCP (CallToolResult.is_error=True) -> RuntimeError
  - erro de aplicação: resultado MCP bem-sucedido (isError=False) cujo
    payload é o envelope {"status": "error", "error": {...}} do servidor
    (ex.: PERMISSION_DENIED — token autenticado mas não autorizado) ->
    RuntimeError, nunca retornado como sucesso
  - falha de transporte/conexão (DNS, TLS, handshake HTTP) -> RuntimeError
    sanitizado, sem vazar api_key/corpo/headers upstream
- health() nunca levanta exceção
- seleção de adapter via COGNITIVE_LIVE_MCP no gateway (default OFF)
"""

from __future__ import annotations

import logging

import fastmcp
import httpx
import pytest

from cognitive.adapters.prosperfy_skills.client import ProsperfySkillsAdapter
from cognitive.adapters.prosperfy_skills.guard import ForbiddenArgumentError
from cognitive.adapters.prosperfy_skills.mock import MockSkillsAdapter
from cognitive.gateway.app import create_app

# Chave de teste conhecida — usada para garantir (via caplog/exception text)
# que ela jamais aparece em logs ou mensagens de exceção do adapter real.
_FAKE_API_KEY = "fake-key-must-never-leak-in-logs-or-errors"


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


# ─── Fakes para fastmcp.Client (nenhuma rede real é usada) ────────────────

class _FakeCallToolResult:
    """Substitui fastmcp.client.client.CallToolResult nos testes."""

    def __init__(self, *, is_error: bool = False, structured_content=None, data=None):
        self.is_error = is_error
        self.structured_content = structured_content
        self.data = data if data is not None else structured_content
        self.content: list = []
        self.meta = None


class _ExplodingMcpClient:
    """Substitui fastmcp.Client para provar que nenhuma conexão MCP é aberta."""

    def __init__(self, *args, **kwargs):
        raise AssertionError(
            "fastmcp.Client foi instanciado — a guard (ou outro check "
            "pré-rede) deveria ter bloqueado ANTES de qualquer tentativa "
            "de conexão MCP"
        )


class _FakeMcpClient:
    """fastmcp.Client fake: async context manager sem rede real."""

    def __init__(self, url, auth=None, timeout=None, **kwargs):
        self.url = url
        self.auth = auth
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def call_tool(self, name, arguments=None, *, raise_on_error=True, **kwargs):
        raise NotImplementedError("subclasse/factory deve sobrescrever call_tool")

    async def ping(self):
        return True


def _make_result_client(result: _FakeCallToolResult):
    """fastmcp.Client fake cujo call_tool sempre retorna `result`."""

    class _Client(_FakeMcpClient):
        async def call_tool(self, name, arguments=None, *, raise_on_error=True, **kwargs):
            return result

    return _Client


def _make_raising_client(exc: Exception):
    """fastmcp.Client fake cujo call_tool sempre levanta `exc`."""

    class _Client(_FakeMcpClient):
        async def call_tool(self, name, arguments=None, *, raise_on_error=True, **kwargs):
            raise exc

    return _Client


def _make_ping_raising_client(exc: Exception):
    """fastmcp.Client fake cujo ping() sempre levanta `exc`."""

    class _Client(_FakeMcpClient):
        async def ping(self):
            raise exc

    return _Client


# ─── ProsperfySkillsAdapter — guard bloqueia antes de qualquer rede ───────

class TestProsperfySkillsAdapterGuardBlocksBeforeNetwork:
    @pytest.mark.asyncio
    async def test_forbidden_command_blocked_before_any_network_call(self, monkeypatch):
        monkeypatch.setattr(fastmcp, "Client", _ExplodingMcpClient)
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
        monkeypatch.setattr(fastmcp, "Client", _ExplodingMcpClient)
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
        monkeypatch.setattr(fastmcp, "Client", _ExplodingMcpClient)
        monkeypatch.delenv("MCP_PROSPERFYSKILLS_API_KEY", raising=False)
        adapter = ProsperfySkillsAdapter(api_key="", host="skills.invalid.test")
        with pytest.raises(RuntimeError, match="API_KEY"):
            await adapter.invoke_tool(
                tool_name="prosperfy_vps_panorama",
                arguments={"resource": "prosperfy-main"},
                tenant_id="tenant-a",
                correlation_id="corr-1",
            )


# ─── ProsperfySkillsAdapter — chamada bem-sucedida ────────────────────────

class TestProsperfySkillsAdapterInvokeToolSuccess:
    @pytest.mark.asyncio
    async def test_successful_call_returns_expected_dict(self, monkeypatch):
        payload = {
            "status": "ok",
            "data": {"uptime_seconds": 123, "host": "prosperfy-main"},
            "meta": {"tool": "prosperfy_vps_panorama"},
            "error": None,
        }
        result = _FakeCallToolResult(is_error=False, structured_content=payload)
        monkeypatch.setattr(fastmcp, "Client", _make_result_client(result))
        adapter = ProsperfySkillsAdapter(api_key=_FAKE_API_KEY, host="skills.invalid.test")

        out = await adapter.invoke_tool(
            tool_name="prosperfy_vps_panorama",
            arguments={"resource": "prosperfy-main"},
            tenant_id="tenant-a",
            correlation_id="corr-1",
        )
        assert out == {"success": True, "data": payload}


# ─── ProsperfySkillsAdapter — erro de aplicação (PERMISSION_DENIED) ──────

class TestProsperfySkillsAdapterApplicationLevelDenial:
    @pytest.mark.asyncio
    async def test_permission_denied_envelope_raises_not_returned_as_success(
        self, monkeypatch, caplog
    ):
        """
        Forma exata confirmada no servidor real:
        CapabilityResult.fail(...).to_dict() — resultado MCP bem-sucedido
        (isError=False) cujo corpo é um envelope de erro da aplicação.
        """
        payload = {
            "status": "error",
            "data": None,
            "meta": {"tool": "prosperfy_vps_panorama"},
            "error": {
                "code": "PERMISSION_DENIED",
                "message": "role insuficiente para esta tool",
                "retryable": False,
                "details": {"required_role": "admin", "actual_role": "viewer"},
            },
        }
        result = _FakeCallToolResult(is_error=False, structured_content=payload)
        monkeypatch.setattr(fastmcp, "Client", _make_result_client(result))
        adapter = ProsperfySkillsAdapter(api_key=_FAKE_API_KEY, host="skills.invalid.test")

        with caplog.at_level(logging.ERROR):
            with pytest.raises(RuntimeError) as excinfo:
                await adapter.invoke_tool(
                    tool_name="prosperfy_vps_panorama",
                    arguments={"resource": "prosperfy-main"},
                    tenant_id="tenant-a",
                    correlation_id="corr-1",
                )

        message = str(excinfo.value)
        assert "PERMISSION_DENIED" in message
        # code/message podem aparecer; error.details nunca.
        assert "required_role" not in message
        assert "admin" not in message
        assert "viewer" not in message
        for record in caplog.records:
            assert "required_role" not in record.getMessage()


# ─── ProsperfySkillsAdapter — erro de protocolo MCP (isError) ────────────

class TestProsperfySkillsAdapterProtocolLevelError:
    @pytest.mark.asyncio
    async def test_protocol_level_is_error_raises_not_returned_as_success(self, monkeypatch):
        result = _FakeCallToolResult(is_error=True, structured_content=None, data=None)
        monkeypatch.setattr(fastmcp, "Client", _make_result_client(result))
        adapter = ProsperfySkillsAdapter(api_key=_FAKE_API_KEY, host="skills.invalid.test")

        with pytest.raises(RuntimeError, match="protocolo MCP"):
            await adapter.invoke_tool(
                tool_name="does_not_exist",
                arguments={"resource": "prosperfy-main"},
                tenant_id="tenant-a",
                correlation_id="corr-1",
            )


# ─── ProsperfySkillsAdapter — falhas de transporte/conexão ───────────────

class TestProsperfySkillsAdapterTransportErrors:
    @pytest.mark.asyncio
    async def test_connect_failure_sanitized_and_key_not_leaked(self, monkeypatch, caplog):
        # Formato real observado ao conectar fastmcp.Client a um host
        # inexistente: RuntimeError("Client failed to connect: ...").
        exc = RuntimeError("Client failed to connect: [Errno 11001] getaddrinfo failed")
        monkeypatch.setattr(fastmcp, "Client", _make_raising_client(exc))
        adapter = ProsperfySkillsAdapter(api_key=_FAKE_API_KEY, host="skills.invalid.test")

        with caplog.at_level(logging.ERROR):
            with pytest.raises(RuntimeError) as excinfo:
                await adapter.invoke_tool(
                    tool_name="prosperfy_vps_panorama",
                    arguments={"resource": "prosperfy-main"},
                    tenant_id="tenant-a",
                    correlation_id="corr-1",
                )

        assert "erro de transporte" in str(excinfo.value)
        assert _FAKE_API_KEY not in str(excinfo.value)
        for record in caplog.records:
            assert _FAKE_API_KEY not in record.getMessage()

    @pytest.mark.asyncio
    async def test_http_status_error_during_handshake_sanitized(self, monkeypatch, caplog):
        request = httpx.Request("POST", "https://skills.invalid.test/mcp")
        response = httpx.Response(
            401, text="Unauthorized upstream trace-id=xyz internal-detail", request=request
        )
        exc = httpx.HTTPStatusError("401 Unauthorized", request=request, response=response)
        monkeypatch.setattr(fastmcp, "Client", _make_raising_client(exc))
        adapter = ProsperfySkillsAdapter(api_key=_FAKE_API_KEY, host="skills.invalid.test")

        with caplog.at_level(logging.ERROR):
            with pytest.raises(RuntimeError) as excinfo:
                await adapter.invoke_tool(
                    tool_name="prosperfy_vps_panorama",
                    arguments={"resource": "prosperfy-main"},
                    tenant_id="tenant-a",
                    correlation_id="corr-1",
                )

        message = str(excinfo.value)
        assert "Unauthorized upstream trace-id" not in message
        assert _FAKE_API_KEY not in message
        for record in caplog.records:
            assert _FAKE_API_KEY not in record.getMessage()
            assert "Unauthorized upstream trace-id" not in record.getMessage()

    @pytest.mark.asyncio
    async def test_malformed_mcp_response_sanitized(self, monkeypatch, caplog):
        """Resposta MCP malformada (erro JSON-RPC de protocolo, ex.: McpError)."""

        class _FakeMcpProtocolError(Exception):
            pass

        exc = _FakeMcpProtocolError("Invalid JSON-RPC response from server")
        monkeypatch.setattr(fastmcp, "Client", _make_raising_client(exc))
        adapter = ProsperfySkillsAdapter(api_key=_FAKE_API_KEY, host="skills.invalid.test")

        with caplog.at_level(logging.ERROR):
            with pytest.raises(RuntimeError) as excinfo:
                await adapter.invoke_tool(
                    tool_name="prosperfy_vps_panorama",
                    arguments={"resource": "prosperfy-main"},
                    tenant_id="tenant-a",
                    correlation_id="corr-1",
                )
        assert "erro de transporte" in str(excinfo.value)
        assert _FAKE_API_KEY not in str(excinfo.value)
        for record in caplog.records:
            assert _FAKE_API_KEY not in record.getMessage()


# ─── ProsperfySkillsAdapter — health() ────────────────────────────────────

class TestProsperfySkillsAdapterHealth:
    @pytest.mark.asyncio
    async def test_health_true_when_ping_succeeds(self, monkeypatch):
        monkeypatch.setattr(fastmcp, "Client", _FakeMcpClient)
        adapter = ProsperfySkillsAdapter(api_key=_FAKE_API_KEY, host="skills.invalid.test")
        assert await adapter.health() is True

    @pytest.mark.asyncio
    async def test_health_false_when_ping_raises(self, monkeypatch):
        monkeypatch.setattr(fastmcp, "Client", _make_ping_raising_client(RuntimeError("boom")))
        adapter = ProsperfySkillsAdapter(api_key=_FAKE_API_KEY, host="skills.invalid.test")
        assert await adapter.health() is False

    @pytest.mark.asyncio
    async def test_health_false_when_connect_raises(self, monkeypatch):
        class _ExplodeOnEnter(_FakeMcpClient):
            async def __aenter__(self):
                raise RuntimeError("connect failed")

        monkeypatch.setattr(fastmcp, "Client", _ExplodeOnEnter)
        adapter = ProsperfySkillsAdapter(api_key=_FAKE_API_KEY, host="skills.invalid.test")
        assert await adapter.health() is False

    @pytest.mark.asyncio
    async def test_health_false_when_no_api_key_no_network(self, monkeypatch):
        monkeypatch.setattr(fastmcp, "Client", _ExplodingMcpClient)
        adapter = ProsperfySkillsAdapter(api_key="", host="skills.invalid.test")
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
        monkeypatch.setattr(fastmcp, "Client", _ExplodingMcpClient)
        # gateway/app.py fail-closed guard (Sprint 0.3 hardening): COGNITIVE_LIVE_MCP=1
        # agora exige MCP_PROSPERFYSKILLS_API_KEY presente ANTES de construir o
        # adapter — ver test_mcp_secret_contract.py para a cobertura da guard em si.
        monkeypatch.setenv("MCP_PROSPERFYSKILLS_API_KEY", "fake-key-for-adapter-selection-test-only")
        app = self._build_app_in_memory(monkeypatch, live_mcp="1")
        assert isinstance(app.state.orchestrator._adapter, ProsperfySkillsAdapter)

    def test_any_other_value_falls_back_to_mock(self, monkeypatch):
        app = self._build_app_in_memory(monkeypatch, live_mcp="true")
        assert isinstance(app.state.orchestrator._adapter, MockSkillsAdapter)
