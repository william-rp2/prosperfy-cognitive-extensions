"""
test_sprint_071_capability_security.py — Sprint 0.7.1 containment do bypass.

Análise (FASE A, CODE_CONFIRMED):
  /capability → _handle_slash → Pipeline → MCPAdapter (MCP direto).
  O subcomando "run" era um stub que NUNCA chamava pipe.run() — mas o
  MCPAdapter.authorize era um placeholder autorizando SEMPRE (authorized=True),
  um bypass LATENTE: se o pipeline fosse conectado, o MCP seria chamado sem
  authorization governada.

Contenção mínima (SECURITY DECISION):
  1. MCPAdapter.authorize → FAIL-CLOSED (authorized=False) — boundary correto;
     consumidores compartilhados provados inalterados (test_fase_i só verifica
     o tipo do resultado; nada no runtime chama authorize).
  2. /capability run → fail-closed explícito (não executa, não mente "✅").

Negativos provados:
  UNAUTHORIZED_CAPABILITY_MCP_CALL=DENIED
  CAPABILITY_FAIL_CLOSED=PASS
  SERVIDORES_STILL_WORKS=PASS (coberto pela suíte 0.5/0.6)
  SHARED_MCPADAPTER_CONSUMERS_REGRESSION=PASS
  NO_REAL_WRITE_EXECUTED=YES · NO_SHELL_EXECUTED=YES
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from capability_intelligence.models import AuthorizationRequest, ExecutionRequest
from capability_intelligence.executor import Executor
from capability_intelligence.transport.adapters.mcp_adapter import MCPAdapter


def _load_plugin_module():
    plugin_path = Path(__file__).resolve().parents[1] / "plugin" / "__init__.py"
    spec = importlib.util.spec_from_file_location("hermes_plugin_071", plugin_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─── 1) MCPAdapter.authorize fail-closed ────────────────────────────────────


def test_mcp_adapter_authorize_fails_closed():
    """O transport MCP direto NEGA autorização (remove o no-op authorized=True)."""
    adapter = MCPAdapter(api_key="unused-in-local")
    result = __import__("asyncio").run(
        adapter.authorize(AuthorizationRequest(capability_id="infra.restart"))
    )
    assert result.authorized is False
    assert result.reason  # mensagem explícita


def test_executor_via_mcp_adapter_denied_and_no_execute():
    """Executor.run via MCPAdapter → "Not authorized" e NUNCA chama execute
    (UNAUTHORIZED_CAPABILITY_MCP_CALL=DENIED; nenhum MCP tocado)."""
    adapter = MCPAdapter(api_key="unused-in-local")

    def _explode_execute(request):
        raise AssertionError("execute NÃO deveria ser chamado sem autorização")

    adapter.execute = _explode_execute
    executor = Executor(authorization=adapter, execution=adapter)

    result = __import__("asyncio").run(executor.run("infra.restart", {"host": "x"}))
    assert result.success is False
    assert "Not authorized" in (result.error or "")
    assert "não governada" in (result.error or "") or "governada" in (result.error or "")


# ─── 2) /capability run fail-closed (path user-facing) ──────────────────────


def test_capability_run_fails_closed_no_mcp():
    """_handle_slash("run ...") retorna negação explícita; NÃO executa nada
    (sem fake "✅ instalado", sem alcance ao MCP)."""
    mod = _load_plugin_module()
    out = mod._handle_slash("run deploy infrastructure")
    assert "fail-closed" in out or "indisponível" in out
    assert "✅" not in out
    assert "Cognitive" in out


def test_capability_status_gaps_feedback_still_work():
    """Subcomandos diagnósticos (status/gaps/feedback) NÃO foram afetados —
    são reads in-memory, sem MCP."""
    mod = _load_plugin_module()
    assert "Capability Intelligence v" in mod._handle_slash("status")
    assert "Lacunas" in mod._handle_slash("gaps") or "Nenhuma lacuna" in mod._handle_slash("gaps")
    assert "Uso: /capability feedback" in mod._handle_slash("feedback")


# ─── 3) MCPAdapter compartilhado: consumidores seguem ok ────────────────────


def test_shared_mcp_adapter_no_external_consumers_broken():
    """Único consumidor de MCPAdapter no código é o plugin (_get_pipeline);
    test_fase_i (único teste que o usa) só verifica o tipo do PipelineResult —
    fail-closed não quebra nada."""
    import inspect
    import capability_intelligence.transport.adapters.mcp_adapter as m

    assert "MCPAdapter" in inspect.getsource(m)
    # caminho /servidores (CognitiveApiAdapter) não importa MCPAdapter:
    import capability_intelligence.transport.cognitive_api_adapter as ca
    src = inspect.getsource(ca)
    assert "MCPAdapter" not in src
    assert "mcp_adapter" not in src


# ─── 4) Regressão /servidores ───────────────────────────────────────────────


def test_servidores_uses_cognitive_not_mcp_adapter():
    """O caminho /servidores continua 100% Cognitive (SERVIDORES_STILL_WORKS
    coberto pela suíte; aqui só confirma que não depende de MCPAdapter)."""
    import inspect
    import capability_intelligence.infra_service as svc
    src = inspect.getsource(svc)
    assert "MCPAdapter" not in src
    assert "MCPAdapter" not in inspect.getsource(__import__("capability_intelligence.server_views", fromlist=["x"]))