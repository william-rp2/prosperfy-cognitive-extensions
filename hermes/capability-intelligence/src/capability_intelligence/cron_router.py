"""
cron_router.py — Deterministic CRON intent gate (Sprint 0.7.3).

Pre-LLM, SEM classifier LLM por turno (NORMAL_CHAT_ROUTER_LLM_CALLS=0).

Rotas EXPLÍCITAS:
  /cron ...  (native built-in Hermes — determinístico, não usa toolset)

Intenções temporais claras (V1 conservadora — FALSE_POSITIVE_CRON_LOW):
  me lembre / lembre-me / crie um lembrete / agende / programe
  todo dia / toda semana / todo mês
  daqui a X minutos/horas
  amanhã às ...

NÃO roteia perguntas conceituais ("o que é cron?", "como funciona um
agendamento recorrente?"). Ambíguo → normal chat (0 tools).
"""

from __future__ import annotations

import re
from typing import Optional

# Prefixos de ação temporal → cron
_ACTION_PREFIXES = (
    "me lembre",
    "lembre-me",
    "lembre de",
    "crie um lembrete",
    "criar um lembrete",
    "agende",
    "agendar",
    "programe",
    "programar",
    "marcar",
    "lembrete",
)

# Marcadores de temporalidade → cron (V1 conservador)
_TEMPORAL_MARKERS = (
    "todo dia",
    "toda semana",
    "todo mês",
    "todo mes",
    "todas as manhãs",
    "toda manhã",
    "toda noite",
    "daqui a",
    "amanhã às",
    "amanha as",
    "diariamente",
    "semanalmente",
    "a cada",
    "às 8h",
    "as 8h",
    "horário",
    "horario",
)

# Perguntas conceituais que NUNCA roteiam (mesmo com "cron"/"agendar")
_CONCEPTUAL = (
    "o que é",
    "o que e",
    "como funciona",
    "o que significa",
    "explique",
    "qual a diferença",
    "qual a diferenca",
    "exemplo de",
    "o que são",
    "o que sao",
)

# Scheduling temporal adicional (Sprint 0.7.8 §5): "em X minutos/horas/dias",
# "hoje às", dias da semana — sinal claro de agendamento/recorrência.
_SCHEDULE_RE = re.compile(
    r"(em \d+ (minuto|minutos|hora|horas|dia|dias))"
    r"|(hoje às|hoje as|hoje à)"
    r"|(segunda-feira|terça-feira|quarta-feira|quinta-feira|sexta-feira|sábado|domingo)"
    r"|(segunda|terça|quarta|quinta|sexta|sabado)"
    r"|(às \d{1,2}h|as \d{1,2}h|a cada \d+)"
)
_WEEKDAYS_SCHEDULE = (
    "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
    "sexta-feira", "sábado", "domingo",
    "toda segunda", "toda terça", "toda quarta", "toda quinta",
    "toda sexta", "todo sábado", "todo domingo",
)


def _has_conceptual(text: str) -> bool:
    low = text.lower()
    return any(c in low for c in _CONCEPTUAL)


def is_cron_intent(message: str) -> bool:
    """True → rota para o cron specialist; False → normal chat (0 tools)."""
    text = (message or "").strip()
    if not text:
        return False
    # Rota explícita /cron (native built-in do Hermes) — determinística.
    if text.startswith("/cron") or text.startswith("/cron "):
        return True
    low = text.lower()
    # Conceitual primeiro — NUNCA roteia mesmo com gatilhos presentes.
    if _has_conceptual(low):
        return False
    has_action = any(p in low for p in _ACTION_PREFIXES)
    has_temporal = any(m in low for m in _TEMPORAL_MARKERS)
    has_schedule = bool(_SCHEDULE_RE.search(low)) or any(m in low for m in _WEEKDAYS_SCHEDULE)
    if has_action and (has_temporal or has_schedule):
        return True
    # "/cron" no meio (ex.: "execute /cron listar") — raro, aceito.
    if "/cron " in text:
        return True
    return False


def route(message: str) -> str:
    """Resolve a rota: 'cron' | 'normal'."""
    return "cron" if is_cron_intent(message) else "normal"


def cron_specialist_toolset() -> str:
    """Toolset mínimo do specialist (contrato): apenas 'cronjob'."""
    return "cronjob"


def resolve_cron_specialist_tools() -> list[str]:
    """Resolve o toolset do specialist (somente cronjob). Sem MCP/skills/etc."""
    try:
        from toolsets import resolve_toolset
        return sorted(resolve_toolset("cronjob"))
    except Exception:
        return []