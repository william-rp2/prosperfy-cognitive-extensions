"""
capability_router.py — Router determinístico pré-LLM de capabilities (Sprint 0.7.8).

Substitui o gate isolado de cron por um boundary compartilhado MINIMO que
resolve a rota de um turno ANTES do LLM normal, SEM classifier (LLM calls = 0).

Rotas:
  NORMAL          → 0 tools (slim)
  CRON            → toolset cronjob (agendamento com sinal temporal claro)
  SESSION_SEARCH  → toolset session_search (referência a conversas passadas)
  MEMORY          → toolset memory (salvar/recuperar memória explícita)
  SKILLS          → toolset skills (consultar/gerenciar skills sob demanda)

Precedência (determinística):
  1. rota slash explícita (/cron /memory /session /skills)
  2. CRON (ação + temporal de scheduling claro)
  3. SESSION_SEARCH (recall de conversa passada)
  4. MEMORY (write/read explícito)
  5. SKILLS (pedido explícito de skill)
  6. NORMAL

Colisão crítica resolvida:
  "Me lembre amanhã às 9h de ligar para João."   → CRON (temporal de scheduling)
  "Me lembre o que decidimos sobre o Hermes."     → SESSION_SEARCH (recall, sem
    temporal de scheduling → NÃO é cron)

NORMAL_CHAT_ROUTER_LLM_CALLS=0 · FALSE_POSITIVE_SPECIALIST=baixo (conservador).
"""

from __future__ import annotations

import re
from typing import Optional

from .cron_router import is_cron_intent

# ─── Rotas explícitas ───────────────────────────────────────────────────
_EXPLICIT = {
    "/cron": "CRON",
    "/memory": "MEMORY",
    "/memoria": "MEMORY",
    "/session": "SESSION_SEARCH",
    "/historico": "SESSION_SEARCH",
    "/skills": "SKILLS",
}

# ─── Conceitual (nunca roteia especialista) ─────────────────────────────
_CONCEPTUAL = (
    "o que é", "o que e", "como funciona", "explique", "o que significa",
    "qual a diferença", "qual a diferenca", "o que são", "o que sao",
    "exemplo de", "me explique",
)

# ─── SESSION_SEARCH (recall de conversa passada) ────────────────────────
_SESSION_RECALL = (
    "o que conversamos", "o que falamos", "o que decidimos", "quando falamos",
    "na outra sessão", "na outra sessao", "na última conversa", "na ultima conversa",
    "sessão anterior", "sessao anterior", "conversa anterior", "histórico",
    "historico", "falamos sobre", "conversamos sobre", "discutimos", "vimos antes",
    "decidimos antes", "conclusão da nossa conversa", "conclusao da nossa conversa",
    "o que ficou combinado", "o que combinamos", "o que acordamos",
)
_SESSION_PAST_TEMPORAL = (
    "ontem", "ontem à noite", "ontem a noite", "anteontem", "dias atrás",
    "dias atras", "semana passada", "na semana passada", "no dia anterior",
    "anteriormente", "em outra sessão", "em outra sessao",
)

# ─── MEMORY (explícito) ─────────────────────────────────────────────────
_MEMORY_WRITE = (
    "lembre que", "memorize", "memorize que", "guarde que",
    "guarde esta informação", "guarde essa informação", "guarde esta info",
    "guarde essa info", "grave que",
)
_MEMORY_READ = (
    "o que você lembra sobre", "o que voce lembra sobre", "o que você lembra a respeito",
    "o que voce lembra a respeito", "você lembra qual", "voce lembra qual",
    "você se lembra", "voce se lembra", "qual informação você tem salva",
    "qual informacao voce tem salva", "o que você sabe sobre", "o que voce sabe sobre",
    "tem salvo sobre", "tem salva sobre",
)

# ─── SKILLS (sob demanda) ───────────────────────────────────────────────
_SKILLS_MARKERS = (
    "quais skills", "skills você", "skills voce", "existe uma skill",
    "mostre a skill", "crie uma skill", "criar uma skill", "atualize a skill",
    "atualizar a skill", "remova a skill", "remover a skill", "skill para",
    "skill do", "skill de", "o que são skills", "o que sao skills",
    "lista de skills", "listar skills", "me mostre as skills", "skill x",
    "skills disponíveis", "skills disponiveis", "skill chamada",
)


def _has_any(text: str, markers) -> bool:
    return any(m in text for m in markers)


def _has_conceptual(text: str) -> bool:
    return any(c in text for c in _CONCEPTUAL)


def _is_explicit(text: str) -> Optional[str]:
    for prefix, route in _EXPLICIT.items():
        if text.startswith(prefix) or text.startswith(prefix + " "):
            return route
    return None


def _is_session_search(text: str) -> bool:
    low = text.lower()
    if _has_any(low, _SESSION_RECALL):
        return True
    # Referência temporal passada + verbo de conversa/decidir → recall.
    if _has_any(low, _SESSION_PAST_TEMPORAL) and _has_any(
        low, ("convers", "falamos", "falou", "decid", "combin", "acord", "vimos", "sess")
    ):
        return True
    return False


def _is_memory(text: str) -> bool:
    low = text.lower()
    return _has_any(low, _MEMORY_WRITE) or _has_any(low, _MEMORY_READ)


def _is_skills(text: str) -> bool:
    return _has_any(text.lower(), _SKILLS_MARKERS)


def resolve_specialist_route(message: str) -> str:
    """Resolve a rota determinística do turno: NORMAL | CRON | SESSION_SEARCH |
    MEMORY | SKILLS. Conservador: ambíguo → NORMAL."""
    text = (message or "").strip()
    if not text:
        return "NORMAL"
    explicit = _is_explicit(text)
    if explicit:
        return explicit
    if _has_conceptual(text.lower()):
        return "NORMAL"
    if is_cron_intent(text):
        return "CRON"
    if _is_session_search(text):
        return "SESSION_SEARCH"
    if _is_memory(text):
        return "MEMORY"
    if _is_skills(text):
        return "SKILLS"
    return "NORMAL"


_ROUTE_TOOLSETS = {
    "CRON": ["cronjob"],
    "SESSION_SEARCH": ["session_search"],
    "MEMORY": ["memory"],
    "SKILLS": ["skills"],
    "NORMAL": [],
}


def route_toolsets(route: str) -> list[str]:
    """Toolsets do specialist para a rota (sem recovery de plataforma)."""
    return list(_ROUTE_TOOLSETS.get(route, []))


def is_specialist(route: str) -> bool:
    return route != "NORMAL"