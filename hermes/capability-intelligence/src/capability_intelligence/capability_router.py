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

import os
import re
from typing import Callable, Optional

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

# ─── INFRA_READ (Phase 1A — Infra Operations Read V1) ───────────────────
_INFRA_KEYWORDS = (
    "servidor", "servidores", "vps", "container", "containers", "docker",
    "porta", "portas", "serviço", "serviços", "infraestrutura",
    "containeres", "contêiner", "contêineres", "conteiner",
)
_INFRA_RESOURCES = (
    "prosperfy", "black", "manager1", "manager 1", "hostinger one",
    "hostinger", "prosperfy vps",
)
_INFRA_OPERATIONAL = (
    "como está", "como esta", "como estão", "como estao", "como andam",
    "quais", "o que está", "o que esta", "quantos", "tem algum",
    "existe algum", "meus servidores", "status dos", "o que aconteceu",
    "o que está acontecendo", "o que esta acontecendo", "andamento",
    "rodando", "parado", "parados", "abertas", "abertos", "funcionando",
    "listar", "mostre os", "mostrar os",
)

# ─── INFRA_ACTION (Phase 1B — Infra Actions V1, write explícito) ──────────
# Apenas intents operacionais EXPLÍCITOS de escrita/restart. Confirmado em 2
# turnos. Negativos conceituais ("por que reiniciar?") → NORMAL.
_INFRA_ACTION_VERBS = (
    "reinicie", "reiniciar", "restart", "reinicie o", "reinicia",
    "resete o", "resetar o", "reinicie o container",
)
_INFRA_ACTION_NEG = (
    "por que", "porque", "como funciona", "o que é", "o que e",
    "o que significa", "explica", "qual a diferença", "quando",
)

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
    "pedi para você lembrar", "pedi para voce lembrar",
    "pedi para você guardar", "pedi para voce guardar",
    "eu pedi para lembrar", "pedi que você lembrasse", "pedi que voce lembrasse",
    "qual foi a informação que eu pedi", "qual informação eu pedi",
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

# ─── WORK_MANAGEMENT (Track P1 — Ideias/Projetos/Tarefas) ────────────────
_WORK_KEYWORDS = (
    "ideia", "ideias", "projeto", "projetos", "tarefa", "tarefas",
    "backlog", "kanban", "bloqueado", "bloqueada", "conclua", "concluir",
    "anote", "anotar",
)

# ─── Confirmação afirmativa (Phase 1B — continuation routing restart V1) ───
# Match EXATO após normalização — "Sim, obrigado" permanece NORMAL.
_AFFIRMATIVE_CONFIRMATIONS = frozenset({
    "sim",
    "sim.",
    "confirmo",
    "confirmado",
    "pode",
    "pode executar",
    "ok",
})

_pending_restart_checker: Callable[[str], bool] | None = None


def set_pending_restart_checker(checker: Callable[[str], bool] | None) -> None:
    """Registra lookup read-only de pending restart (wire-in pelo restart_container_tools)."""
    global _pending_restart_checker
    _pending_restart_checker = checker


def _is_affirmative_confirmation(text: str) -> bool:
    normalized = (text or "").strip().lower().rstrip("!").strip()
    return normalized in _AFFIRMATIVE_CONFIRMATIONS


def _routing_actor_id(actor_id: str | None) -> str | None:
    if actor_id:
        return actor_id
    return os.getenv("COGNITIVE_ACTOR_ID") or None


def _has_any(text: str, markers) -> bool:
    return any(m in text for m in markers)


def _has_conceptual(text: str) -> bool:
    # Word-boundary: evita falso "o que e" casar dentro de "o que est..." 
    # (ex.: "o que está acontecendo" é operacional, não conceitual).
    return any(re.search(r"\b" + re.escape(c) + r"\b", text) for c in _CONCEPTUAL)


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


def _is_infra_action(text: str) -> bool:
    """Intenção EXPLÍCITA de escrita/restart (Phase 1B). Conservador:
    verbo de ação + recurso/container + NÃO é pergunta conceitual.
    "Reinicie o omniroute no Prosperfy." → YES · "Por que reiniciar?" → NO."""
    low = text.lower()
    if _has_any(low, _INFRA_ACTION_NEG):
        return False
    if not _has_any(low, _INFRA_ACTION_VERBS):
        return False
    has_resource = _has_any(low, _INFRA_RESOURCES)
    has_container = "container" in low or "container " in low
    # precisa de alvo: resource OU container explícito
    return has_resource or has_container


def _is_infra_read(text: str) -> bool:
    """Intenção operacional sobre a infraestrutura (Phase 1A, read-only).

    Conservador: exige sinal de keyword/recursos de infra + contexto
    operacional (pergunta/estado/ações read). Conceitual é bloqueado antes
    ("o que significa servidor web?", "diferença entre Docker e VM?" → NORMAL).
    Se dúvida: NORMAL.
    """
    low = text.lower()
    if _has_conceptual(low):
        return False
    has_infra_kw = _has_any(low, _INFRA_KEYWORDS)
    has_resource = _has_any(low, _INFRA_RESOURCES)
    has_operational = _has_any(low, _INFRA_OPERATIONAL)
    if not (has_infra_kw or has_resource):
        return False
    # "meus servidores" é operacional por si só; demais exigem pergunta/estado.
    if "meus servidores" in low:
        return True
    return has_operational


def _is_work_management(text: str) -> bool:
    """Intenção de gestão de trabalho (ideias/projetos/tarefas — Track P1).
    Conservador: keyword de domínio + não é pergunta conceitual."""
    low = text.lower()
    if _has_conceptual(low):
        return False
    return _has_any(low, _WORK_KEYWORDS)


def resolve_specialist_route(message: str, actor_id: str | None = None) -> str:
    """Resolve a rota determinística do turno: NORMAL | CRON | SESSION_SEARCH |
    MEMORY | SKILLS | INFRA_READ | INFRA_ACTION. Conservador: ambíguo → NORMAL.

    Phase 1B: confirmação afirmativa explícita + pending restart do mesmo actor
    → INFRA_ACTION (continuation routing — nunca "Sim" global).
    """
    text = (message or "").strip()
    if not text:
        return "NORMAL"

    actor = _routing_actor_id(actor_id)
    if actor and _pending_restart_checker is not None and _is_affirmative_confirmation(text):
        if _pending_restart_checker(actor):
            return "INFRA_ACTION"

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
    if _is_infra_action(text):
        return "INFRA_ACTION"
    if _is_infra_read(text):
        return "INFRA_READ"
    if _is_work_management(text):
        return "WORK_MANAGEMENT"
    return "NORMAL"


_ROUTE_TOOLSETS = {
    "CRON": ["cronjob"],
    "SESSION_SEARCH": ["session_search"],
    "MEMORY": ["memory"],
    "SKILLS": ["skills"],
    "INFRA_READ": ["infra_read"],
    "INFRA_ACTION": ["restart_container"],
    "WORK_MANAGEMENT": ["work_management"],
    "NORMAL": [],
}


def route_toolsets(route: str) -> list[str]:
    """Toolsets do specialist para a rota (sem recovery de plataforma)."""
    return list(_ROUTE_TOOLSETS.get(route, []))


def resolve_turn_toolsets(message: str, actor_id: str | None = None) -> tuple[str, list[str]]:
    """Boundary pré-LLM: rota + toolsets (espelha CAPABILITY_ROUTE / ENABLED_TOOLSETS)."""
    route = resolve_specialist_route(message, actor_id=actor_id)
    return route, route_toolsets(route)


def is_specialist(route: str) -> bool:
    return route != "NORMAL"