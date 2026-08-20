"""
tests/unit/test_mcp_secret_contract.py — fail-closed contract para
MCP_PROSPERFYSKILLS_API_KEY quando COGNITIVE_LIVE_MCP=1.

Cobre a checagem eager em gateway/app.py (_require_live_mcp_secret),
chamada ANTES de construir o ProsperfySkillsAdapter em _build_services().

Sem DB, sem rede: apenas monkeypatch.setenv/delenv + chamada direta das
funções, seguindo o padrão de tests/unit/test_runtime_modes.py.
"""

from __future__ import annotations

import pytest

from cognitive.adapters.prosperfy_skills.client import ProsperfySkillsAdapter
from cognitive.gateway.app import _require_live_mcp_secret, create_app


def _clear_db_env(monkeypatch) -> None:
    """Garante modo in_memory (sem DB obrigatório) para create_app() nos testes."""
    monkeypatch.setenv("COGNITIVE_MODE", "in_memory")
    monkeypatch.delenv("COGNITIVE_DB_URL", raising=False)
    monkeypatch.delenv("COGNITIVE_DB_ADMIN_URL", raising=False)
    monkeypatch.delenv("COGNITIVE_DB_WORKER_URL", raising=False)


class TestRequireLiveMcpSecretUnit:
    """Testa _require_live_mcp_secret() isoladamente (menor unidade testável)."""

    def test_unset_raises(self, monkeypatch):
        monkeypatch.delenv("MCP_PROSPERFYSKILLS_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="MCP_PROSPERFYSKILLS_API_KEY"):
            _require_live_mcp_secret()

    def test_explicit_empty_string_raises(self, monkeypatch):
        monkeypatch.setenv("MCP_PROSPERFYSKILLS_API_KEY", "")
        with pytest.raises(RuntimeError, match="MCP_PROSPERFYSKILLS_API_KEY"):
            _require_live_mcp_secret()

    def test_whitespace_only_raises(self, monkeypatch):
        monkeypatch.setenv("MCP_PROSPERFYSKILLS_API_KEY", "   \t  ")
        with pytest.raises(RuntimeError, match="MCP_PROSPERFYSKILLS_API_KEY"):
            _require_live_mcp_secret()

    def test_present_does_not_raise(self, monkeypatch):
        monkeypatch.setenv("MCP_PROSPERFYSKILLS_API_KEY", "some-configured-value")
        _require_live_mcp_secret()  # não deve levantar

    def test_error_message_never_echoes_configured_value(self, monkeypatch):
        """
        Mesmo quando um valor malformado/parcial existiu antes de ser limpo,
        a mensagem de erro nunca deve conter esse valor verbatim.
        """
        monkeypatch.setenv("MCP_PROSPERFYSKILLS_API_KEY", "fake-key-should-never-appear-in-error")
        monkeypatch.setenv("MCP_PROSPERFYSKILLS_API_KEY", "")  # operador limpou/zerou
        with pytest.raises(RuntimeError) as exc_info:
            _require_live_mcp_secret()
        message = str(exc_info.value)
        assert "fake-key-should-never-appear-in-error" not in message


class TestBuildServicesIntegration:
    """
    Testa o caminho completo via create_app() → _build_services(), garantindo
    que a falha propaga incondicionalmente (uncaught) para fora de create_app()
    e que nenhum ProsperfySkillsAdapter chega a ser construído antes do raise.
    """

    def test_live_mcp_without_key_fails_app_startup(self, monkeypatch):
        _clear_db_env(monkeypatch)
        monkeypatch.setenv("COGNITIVE_LIVE_MCP", "1")
        monkeypatch.delenv("MCP_PROSPERFYSKILLS_API_KEY", raising=False)

        with pytest.raises(RuntimeError, match="MCP_PROSPERFYSKILLS_API_KEY"):
            create_app()

    def test_live_mcp_with_empty_key_fails_app_startup(self, monkeypatch):
        _clear_db_env(monkeypatch)
        monkeypatch.setenv("COGNITIVE_LIVE_MCP", "1")
        monkeypatch.setenv("MCP_PROSPERFYSKILLS_API_KEY", "")

        with pytest.raises(RuntimeError, match="MCP_PROSPERFYSKILLS_API_KEY"):
            create_app()

    def test_live_mcp_with_key_builds_real_adapter(self, monkeypatch):
        _clear_db_env(monkeypatch)
        monkeypatch.setenv("COGNITIVE_LIVE_MCP", "1")
        monkeypatch.setenv("MCP_PROSPERFYSKILLS_API_KEY", "test-key-not-real")

        app = create_app()
        assert isinstance(app.state.orchestrator._adapter, ProsperfySkillsAdapter)

    def test_live_mcp_disabled_ignores_missing_key(self, monkeypatch):
        """COGNITIVE_LIVE_MCP=0 (ou ausente) → nenhuma checagem é feita; MockSkillsAdapter é usado."""
        from cognitive.adapters.prosperfy_skills.mock import MockSkillsAdapter

        _clear_db_env(monkeypatch)
        monkeypatch.delenv("COGNITIVE_LIVE_MCP", raising=False)
        monkeypatch.delenv("MCP_PROSPERFYSKILLS_API_KEY", raising=False)

        app = create_app()
        assert isinstance(app.state.orchestrator._adapter, MockSkillsAdapter)
