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
from typing import Any, Callable, Optional

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

# ─── SUPABASE_OPS (P0 — Supabase Ops + Anti-Hibernação) ───────────────────
# Palavras-chave + intents operacionais (doc P0 §7): "supabase", "banco",
# hiberna(ção), pausad(o/a), keepalive. Conservador: keyword sozinha não
# roteia — exige também contexto operacional/pergunta (mesmo shape de
# _is_infra_read), ou "meus supabases"/"meus bancos" que já é operacional
# por si só.
# NOTA (integração P0/P2): "banco"/"bancos" REMOVIDOS de propósito. Em PT-BR
# "banco" é ambíguo (database vs. banco financeiro) e colidia com o contrato
# FINANCE do P2 — "Sincronize meus bancos" roteava para SUPABASE_OPS em vez de
# finance.sync.run. Supabase Ops tem chaves inequívocas; linguagem bancária
# pertence à rota FINANCE.
_SUPABASE_KEYWORDS = (
    "supabase", "supabases", "hiberna", "hibernacao", "hibernação",
    "pausad", "keepalive", "keep-alive",
)
_SUPABASE_OPERATIONAL = (
    "como está", "como esta", "como estão", "como estao", "como andam",
    "quais", "algum", "alguma", "com problema", "quando foi", "teste agora",
    "teste o", "teste a", "último", "ultimo", "status dos", "status do",
)


def _is_supabase_ops(text: str) -> bool:
    """Intenção operacional sobre Supabase (P0, read-only na rota — a ação
    real de keepalive/teste é sempre read-only no projeto monitorado).
    Conceitual é bloqueado antes ("o que é Supabase?" → NORMAL). Se dúvida:
    NORMAL."""
    low = text.lower()
    if _has_conceptual(low):
        return False
    if not _has_any(low, _SUPABASE_KEYWORDS):
        return False
    if "meus supabases" in low:
        return True
    return _has_any(low, _SUPABASE_OPERATIONAL)


# ─── WORK_MANAGEMENT (Track P1 — Ideias/Projetos/Tarefas) ────────────────
_WORK_KEYWORDS = (
    "ideia", "ideias", "projeto", "projetos", "tarefa", "tarefas",
    "backlog", "kanban", "bloqueado", "bloqueada", "conclua", "concluir",
    "anote", "anotar",
)

# ─── BROWSER (Track BH — Browser Harness V1, sob demanda) ────────────────
# Doc 00 §4.2: só quando clique/digitação/upload/login/sessão autenticada
# são necessários — nunca substitui fetch/API simples. Conservador: link
# solto sem verbo de interação cai em NORMAL (fetch resolve fora do
# specialist route); pergunta conceitual já caiu em NORMAL antes de chegar
# aqui (guard em resolve_specialist_route).
_BROWSER_URL_RE = re.compile(r"https?://\S+")
_BROWSER_NAV_VERBS = (
    "acesse", "acesse o site", "acesse esse site", "acesse essa página",
    "abra o site", "abra esse site", "abra esse link", "visite o site", "visite esse site",
    "navegue até", "navegue ate",
)
_BROWSER_INTERACTION_VERBS = (
    "faça login", "faca login", "logue em", "loga em", "faça o login", "faca o login",
    "preencha o formulário", "preencha o formulario", "preencher o formulário",
    "cadastre-se em", "cadastre-me em", "faça o cadastro em", "faca o cadastro em",
    # Use case literal do doc 00 §4.1: "Faça meu cadastro nessa ferramenta".
    # O gate original exigia a preposição "em" e deixava essa frase em NORMAL.
    "faça meu cadastro", "faca meu cadastro", "faça o cadastro", "faca o cadastro",
    "criar conta em", "criar uma conta em",
    "crie uma conta em", "crie minha conta em", "clique no botão", "clique em enviar",
    "envie o formulário", "envie o formulario", "submeta o formulário",
)


# Verbos de LEITURA. Sozinhos nunca roteiam — exigem URL explícita na
# mensagem (ver _is_browser).
_BROWSER_READ_VERBS = (
    "leia", "leiam", "resuma", "resumir", "resumo", "analise", "analisar",
    "extraia", "extrair", "consulte", "consultar", "o que tem em",
    "o que diz", "me diga o que", "confira",
)


def _is_browser(text: str) -> bool:
    """Intenção de uso do Browser Worker isolado (doc 00 §4.1/§4.2).

    INTEGRAÇÃO — correção do gate original da track BH: ele mandava
    "Leia e resuma <url1> <url2>" para NORMAL, argumentando que fetch
    resolveria fora do specialist. Só que NORMAL é slim e tem 0 tools, então
    ninguém buscava nada e a primeira use case do doc 00 §4.1 (justamente
    "Leia e resuma estes materiais" + links) não fechava ponta a ponta.

    Agora: URL explícita + verbo de leitura/navegação → BROWSER. A escolha
    entre fetch e navegador NÃO é feita aqui por keyword; ela é o decision
    gate do §4.2, aplicado dentro de browser.read, que é onde existe a
    evidência real (página pública/estática → fetch; JS/login/bot-protection
    → navegador). Roteador decide QUEM atende, a capability decide COMO.

    Sem URL e sem verbo de interação → NORMAL (conservador, inalterado).
    """
    low = text.lower()
    if _has_any(low, _BROWSER_INTERACTION_VERBS):
        return True
    if _BROWSER_URL_RE.search(text) and (
        _has_any(low, _BROWSER_NAV_VERBS) or _has_any(low, _BROWSER_READ_VERBS)
    ):
        return True
    return False


# ─── FINANCE (P2 — Financeiro pelo WhatsApp) ────────────────────────────
# Linguagem bancária pessoal é EXCLUSIVA desta rota — nunca reivindica
# "supabase"/"pausad"/"hiberna"/"keepalive" (P0) nem "ideia"/"projeto"/
# "tarefa"/"kanban" (P1). Bloqueio conceitual herdado do check global de
# _has_conceptual em resolve_specialist_route (roda antes de qualquer rota
# de domínio) — "o que é orçamento?" já cai em NORMAL antes de chegar aqui.
#
# F2B: "pendência(s)" sozinha NÃO roteia — exige âncora financeira
# (financeira/financeiro/finanças…) OU mês de competência. Assim
# "Tenho pendências no projeto" permanece fora de FINANCE (e cai em
# WORK_MANAGEMENT pela precedência de domínio, se houver "projeto").
_FINANCE_KEYWORDS = (
    "gastei", "gasto", "gastos", "receita", "receitas", "entrou", "entradas",
    "saldo", "orçamento", "orcamento", "orçamentos", "orcamentos",
    "fatura", "faturas", "extrato", "despesa", "despesas",
    "banco", "bancos", "vencem", "vencer", "a vencer", "vencimento", "vencimentos",
)
_FINANCE_SYNC_PHRASES = (
    "sincronize meus bancos", "sincronizar meus bancos", "sincronize os bancos",
    "sincronizar os bancos", "sincronize meu banco",
)
_FINANCE_ACTION_VERBS = (
    "registre", "registrar", "lancei", "lançar", "lancar", "anote", "anotar",
)
_FINANCE_MONEY_MARKERS = ("r$", " reais", "centavos")
# Categorias internas seed (migration 002, apps/financeiro-pessoal-api) —
# só conta como sinal de finance quando combinada com um valor monetário
# (evita "saúde"/"lazer" isolados colidirem com outros domínios).
_FINANCE_CATEGORY_NAMES = (
    "alimentação", "alimentacao", "transporte", "moradia", "saúde", "saude",
    "lazer", "combustível", "combustivel", "compras", "educação", "educacao",
    "serviços", "servicos", "salário", "salario",
)
_FINANCE_MONEY_VALUE_RE = re.compile(r"\d+[.,]\d{2}\b")
_FINANCE_DOMAIN_PHRASES = (
    "pendência financeira", "pendências financeiras",
    "pendencia financeira", "pendencias financeiras",
    "pendências do financeiro", "pendencias do financeiro",
    "pendência do financeiro", "pendencia do financeiro",
    "financeiro pessoal", "finanças pessoais", "financas pessoais",
)
_FINANCE_PENDING_WORDS = (
    "pendência", "pendências", "pendencia", "pendencias",
)
_FINANCE_PENDING_ANCHORS = (
    "financeira", "financeiras", "financeiro", "finanças", "financas",
)
_FINANCE_MONTH_NAMES = (
    "janeiro", "fevereiro", "março", "marco", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)
_FINANCE_COMPETENCE_MONTH_RE = re.compile(r"\b20\d{2}[-/]\d{1,2}\b")


def _is_finance_pending_intent(low: str) -> bool:
    """Pendências/clarifications F2B — frases compostas, nunca 'pendência' solta."""
    if _has_any(low, _FINANCE_DOMAIN_PHRASES):
        return True
    has_pending = _has_any(low, _FINANCE_PENDING_WORDS)
    if not has_pending:
        return False
    if _has_any(low, _FINANCE_PENDING_ANCHORS):
        return True
    if _has_any(low, _FINANCE_MONTH_NAMES) or bool(_FINANCE_COMPETENCE_MONTH_RE.search(low)):
        return True
    return False


def _is_finance(text: str) -> bool:
    """Intenção financeira pessoal: leitura ("quanto gastei"), lançamento
    manual, reclassificação de categoria, orçamento, sync com o banco,
    pendências/clarifications F2B.

    Conservador: keyword de domínio OU frase de sync OU (valor monetário +
    verbo de lançamento) OU (valor monetário + nome de categoria conhecida)
    OU pendência com âncora financeira/mês — cobre "Registre 120 reais, mas
    foi ontem" (sem 'R$') e "Essa compra de 54,90 do X é Alimentação" (sem
    keyword nem verbo de lançamento) do doc 00 §7, sem deixar um valor
    monetário sozinho roteando qualquer frase.
    """
    low = text.lower()
    if _has_any(low, _FINANCE_KEYWORDS):
        return True
    if _has_any(low, _FINANCE_SYNC_PHRASES):
        return True
    if _is_finance_pending_intent(low):
        return True
    has_money = _has_any(low, _FINANCE_MONEY_MARKERS) or bool(_FINANCE_MONEY_VALUE_RE.search(low))
    if has_money and _has_any(low, _FINANCE_ACTION_VERBS):
        return True
    if has_money and _has_any(low, _FINANCE_CATEGORY_NAMES):
        return True
    return False


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


# F2B / 03 §"Reply binding": quando o owner RESPONDE CITANDO a mensagem da
# pergunta financeira, o vínculo é o provider_message_id citado — metadado de
# transporte (ContextEnvelope.reply_to_message_id), nunca o texto. O texto de
# uma resposta citada é arbitrário ("foi mercado", "sim", um emoji) e não
# contém keyword de finanças alguma, então nenhuma heurística textual daqui
# conseguiria rotear esse turno.
#
# O predicado é INJETADO (mesmo seam de _pending_restart_checker) para o
# router continuar puro e sem I/O. A verdade durável é a Finance API — ver
# finance_reply_binding.install_router_hook.
_finance_quoted_reply_checker: Callable[..., bool] | None = None


def set_finance_quoted_reply_checker(checker: Callable[..., bool] | None) -> None:
    """Registra lookup read-only 'esse message id citado é uma pergunta financeira?'.

    Sem checker registrado o comportamento é o pré-F2B (só heurística de
    texto): nunca abre rota por acidente.

    Assinatura preferida do checker: ``(message_id, context_envelope=None)``.
    Callers legados ``(message_id)`` continuam válidos.
    """
    global _finance_quoted_reply_checker
    _finance_quoted_reply_checker = checker


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


def resolve_specialist_route(
    message: str,
    actor_id: str | None = None,
    *,
    reply_to_message_id: str = "",
    context_envelope: Any = None,
) -> str:
    """Resolve a rota determinística do turno: NORMAL | CRON | SESSION_SEARCH |
    MEMORY | SKILLS | INFRA_READ | INFRA_ACTION | FINANCE. Conservador: ambíguo → NORMAL.

    Phase 1B: confirmação afirmativa explícita + pending restart do mesmo actor
    → INFRA_ACTION (continuation routing — nunca "Sim" global).

    F2B: `reply_to_message_id` é o provider_message_id CITADO pelo owner
    (ContextEnvelope.reply_to_message_id). Quando ele corresponde a uma
    pergunta financeira já entregue, a rota é FINANCE — decisão por metadado
    de transporte, antes de qualquer heurística de texto e antes do LLM.
    `context_envelope` (opcional) propaga channel trusted para o lookup durável.
    Rotear para FINANCE não autoriza nada: a ACL de finance (Cognitive
    policy) decide ALLOW/DENY depois, sobre a identidade canônica do ator.
    """
    text = (message or "").strip()

    # Precede até o guard de texto vazio: a resposta citada pode ser só um
    # emoji/sticker e ainda assim é a resposta a uma pergunta específica.
    if reply_to_message_id and _finance_quoted_reply_checker is not None:
        try:
            if _finance_quoted_reply_checker(reply_to_message_id, context_envelope):
                return "FINANCE"
        except TypeError:
            # Checker legado: Callable[[str], bool]
            if _finance_quoted_reply_checker(reply_to_message_id):
                return "FINANCE"

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
    if _is_supabase_ops(text):
        return "SUPABASE_OPS"
    if _is_work_management(text):
        return "WORK_MANAGEMENT"
    if _is_browser(text):
        return "BROWSER"
    if _is_finance(text):
        return "FINANCE"
    return "NORMAL"


_ROUTE_TOOLSETS = {
    "CRON": ["cronjob"],
    "SESSION_SEARCH": ["session_search"],
    "MEMORY": ["memory"],
    "SKILLS": ["skills"],
    "INFRA_READ": ["infra_read"],
    "INFRA_ACTION": ["restart_container"],
    "SUPABASE_OPS": ["supabase_ops"],
    "WORK_MANAGEMENT": ["work_management"],
    "BROWSER": ["browser_harness"],
    "FINANCE": ["finance"],
    "NORMAL": [],
}


def route_toolsets(route: str) -> list[str]:
    """Toolsets do specialist para a rota (sem recovery de plataforma)."""
    return list(_ROUTE_TOOLSETS.get(route, []))


def resolve_turn_toolsets(
    message: str,
    actor_id: str | None = None,
    *,
    reply_to_message_id: str = "",
    context_envelope: Any = None,
) -> tuple[str, list[str]]:
    """Boundary pré-LLM: rota + toolsets (espelha CAPABILITY_ROUTE / ENABLED_TOOLSETS)."""
    route = resolve_specialist_route(
        message,
        actor_id=actor_id,
        reply_to_message_id=reply_to_message_id,
        context_envelope=context_envelope,
    )
    return route, route_toolsets(route)


def is_specialist(route: str) -> bool:
    return route != "NORMAL"