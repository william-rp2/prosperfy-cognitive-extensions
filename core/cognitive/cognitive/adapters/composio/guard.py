"""
adapters/composio/guard.py — Boundary guard para argumentos indo ao Compose MCP.

Contexto (P0 — Supabase Ops + Anti-Hibernação, doc 3 "Fora de escopo": SQL
arbitrário via WhatsApp, migrations ad-hoc, drop/truncate, pause/resume
manual NUNCA passam por este adapter):

Allowlist estrita em DUAS camadas:
  1. tool_name — só as 5 tools Supabase read-only do Composio usadas pelas
     capabilities supabase.* passam. Qualquer outra (ex.:
     SUPABASE_BETA_RUN_SQL_QUERY, SUPABASE_SELECT_FROM_TABLE, ou qualquer
     tool de outro toolkit Composio) é rejeitada — nunca um passthrough
     genérico de tool_name/arguments para o Compose MCP.
  2. Por tool, os argumentos aceitos são validados exatamente (chaves
     permitidas, formato de 'ref', e — crítico — 'query' restrita a um
     allowlist fixo de duas queries read-only sem side effect, nunca SQL
     livre). Isso é o "negativo obrigatório" de SQL arbitrário do gate
     NO_MUTATION: mesmo que um caller/capability YAML tente injetar outra
     query, este guard recusa antes de qualquer chamada de rede.

Aplicado tanto no adapter real (client.py) quanto no mock (mock.py), mesmo
contrato de segurança em CI e produção — mesmo padrão de
adapters/prosperfy_skills/guard.py.
"""

from __future__ import annotations

import re
from typing import Any

_REF_RE = re.compile(r"^[a-z]{20}$")

# Únicas duas queries read-only permitidas (doc §5.1: "Exemplo conceitual:
# SELECT 1 / SELECT now()"). Comparação normalizada (case-insensitive,
# espaços/`;` finais ignorados) mas o conjunto em si é fechado — nunca um
# padrão/regex permissivo que aceitaria SQL arbitrário disfarçado.
_ALLOWED_QUERIES = frozenset({"select 1", "select now()"})

_HEALTH_SERVICES = frozenset({
    "auth", "db", "db_postgres_user", "pg_bouncer", "pooler", "realtime",
    "rest", "storage",
})


class ForbiddenArgumentError(ValueError):
    """Levantado quando tool_name ou arguments não passam na allowlist do Compose MCP."""


def _normalize_query(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip().rstrip(";").strip().lower()


def _require_ref(arguments: dict[str, Any], tool_name: str) -> None:
    ref = arguments.get("ref")
    if not isinstance(ref, str) or not _REF_RE.match(ref):
        raise ForbiddenArgumentError(
            f"'ref' inválido para '{tool_name}': exige exatamente 20 letras minúsculas "
            "(project ref público do Supabase, nunca secret)."
        )


def _guard_run_read_only_query(arguments: dict[str, Any]) -> None:
    allowed_keys = {"ref", "query"}
    extra = set(arguments.keys()) - allowed_keys
    if extra:
        raise ForbiddenArgumentError(
            f"Argumento(s) extra(s) para 'SUPABASE_RUN_READ_ONLY_QUERY': {sorted(extra)}"
        )
    missing = allowed_keys - set(arguments.keys())
    if missing:
        raise ForbiddenArgumentError(
            f"Argumento(s) ausente(s) para 'SUPABASE_RUN_READ_ONLY_QUERY': {sorted(missing)}"
        )
    _require_ref(arguments, "SUPABASE_RUN_READ_ONLY_QUERY")
    normalized = _normalize_query(arguments.get("query"))
    if normalized not in _ALLOWED_QUERIES:
        raise ForbiddenArgumentError(
            "'query' não permitida para 'SUPABASE_RUN_READ_ONLY_QUERY': somente "
            f"{sorted(_ALLOWED_QUERIES)} — SQL arbitrário é sempre negado (NO_MUTATION)."
        )


def _guard_get_project(arguments: dict[str, Any]) -> None:
    extra = set(arguments.keys()) - {"ref"}
    if extra:
        raise ForbiddenArgumentError(
            f"Argumento(s) extra(s) para 'SUPABASE_GET_PROJECT': {sorted(extra)}"
        )
    _require_ref(arguments, "SUPABASE_GET_PROJECT")


def _guard_health_status(arguments: dict[str, Any]) -> None:
    allowed_keys = {"ref", "services"}
    extra = set(arguments.keys()) - allowed_keys
    if extra:
        raise ForbiddenArgumentError(
            f"Argumento(s) extra(s) para 'SUPABASE_GETS_PROJECT_S_SERVICE_HEALTH_STATUS': {sorted(extra)}"
        )
    _require_ref(arguments, "SUPABASE_GETS_PROJECT_S_SERVICE_HEALTH_STATUS")
    services = arguments.get("services")
    if services is not None:
        if not isinstance(services, list) or not set(services).issubset(_HEALTH_SERVICES):
            raise ForbiddenArgumentError(
                "'services' inválido para 'SUPABASE_GETS_PROJECT_S_SERVICE_HEALTH_STATUS': "
                f"subconjunto de {sorted(_HEALTH_SERVICES)} exigido."
            )


def _guard_no_args(arguments: dict[str, Any], tool_name: str) -> None:
    if arguments:
        raise ForbiddenArgumentError(
            f"'{tool_name}' não aceita argumentos — recebido: {sorted(arguments.keys())}."
        )


# tool_name -> validador. Qualquer tool_name fora deste dict é rejeitada em
# guard_arguments() antes mesmo de olhar os argumentos — allowlist fechada.
_TOOL_GUARDS = {
    "SUPABASE_RUN_READ_ONLY_QUERY": _guard_run_read_only_query,
    "SUPABASE_GET_PROJECT": _guard_get_project,
    "SUPABASE_LIST_ALL_PROJECTS": lambda a: _guard_no_args(a, "SUPABASE_LIST_ALL_PROJECTS"),
    "SUPABASE_LIST_ALL_ORGANIZATIONS": lambda a: _guard_no_args(a, "SUPABASE_LIST_ALL_ORGANIZATIONS"),
    "SUPABASE_GETS_PROJECT_S_SERVICE_HEALTH_STATUS": _guard_health_status,
}


def guard_arguments(tool_name: str, arguments: dict[str, Any]) -> None:
    """
    Valida (tool_name, arguments) antes de invocar o Compose MCP (real ou mock).

    Fail-closed em duas camadas: tool_name fora da allowlist -> rejeita
    direto; tool_name conhecida mas arguments fora do formato esperado
    (chaves extras/ausentes, 'ref' malformado, 'query' fora do allowlist
    fixo) -> rejeita. Nunca deixa passar silenciosamente.
    """
    validator = _TOOL_GUARDS.get(tool_name)
    if validator is None:
        raise ForbiddenArgumentError(
            f"Tool '{tool_name}' não está na allowlist do Compose MCP para capabilities "
            "supabase.* — nenhuma tool de escrita/SQL livre/migration é permitida aqui."
        )
    validator(arguments)
