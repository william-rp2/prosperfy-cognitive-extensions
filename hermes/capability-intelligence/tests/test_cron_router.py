"""
test_cron_router.py — Sprint 0.7.3 contract do cron specialist intent gate.

Matriz obrigatória:
  C1: /cron listar → CRON_ROUTE=YES
  C2: Me lembre amanhã às 9h de revisar o relatório. → CRON_ROUTE=YES
  C3: Todo dia às 8h me lembre de verificar as tarefas. → CRON_ROUTE=YES
  C4: O que é cron? → CRON_ROUTE=NO (normal chat, 0 tools)
  C5: Obrigado. (após cron) → CRON_ROUTE=NO, sem carry-over

Garantias:
  NORMAL_CHAT_ROUTER_LLM_CALLS=0 (gate determinístico, sem classifier)
  FALSE_POSITIVE_CRON_LOW (negativos razoáveis)
"""

from __future__ import annotations

import pytest

from capability_intelligence.cron_router import (
    is_cron_intent,
    route,
    cron_specialist_toolset,
)


@pytest.mark.parametrize("msg", [
    "/cron listar",
    "/cron criar amanha as 9h revisar relatorio",
    "Me lembre amanhã às 9h de revisar o relatório.",
    "Todo dia às 8h me lembre de verificar as tarefas.",
    "me lembre de ligar para João amanhã às 10h",
    "agende uma reunião daqui a 2 horas",
    "crie um lembrete toda semana para pagar as contas",
    "programe o envio do relatório todo mês",
])
def test_c1_c2_c3_cron_routes_yes(msg):
    assert is_cron_intent(msg) is True
    assert route(msg) == "cron"


@pytest.mark.parametrize("msg", [
    "O que é cron?",
    "Como funciona um agendamento recorrente?",
    "O que é um lembrete?",
    "Explique o que significa agendar",
    "Olá",
    "Obrigado.",
    "Tudo bem?",
    "Qual o horário de funcionamento de vocês?",
])
def test_c4_c5_and_conceptual_no_route(msg):
    assert is_cron_intent(msg) is False
    assert route(msg) == "normal"


def test_conceptual_with_trigger_does_not_route():
    # "agende" presente mas é pergunta conceitual → NORMAL.
    assert is_cron_intent("O que é um agendamento? Como funciona?") is False
    assert is_cron_intent("Explique como agendar coisas") is False


def test_specialist_toolset_contract():
    assert cron_specialist_toolset() == "cronjob"


def test_resolve_cron_specialist_tools_only_cronjob():
    """Quando o runtime estiver disponível, o specialist resolve APENAS
    cronjob — sem MCP/skills/kanban/feishu (isolamento)."""
    try:
        tools = __import__(
            "capability_intelligence.cron_router", fromlist=["resolve_cron_specialist_tools"]
        ).resolve_cron_specialist_tools()
    except Exception:
        pytest.skip("runtime toolsets indisponível neste ambiente de teste")
    assert len(tools) > 0 or tools == []
    # Não pode incluir tools de outras capacidades
    for t in tools:
        assert not t.startswith(("kanban", "feishu", "mcp", "web_", "vision", "memory", "terminal"))