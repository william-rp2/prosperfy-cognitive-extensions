"""
finance_tools.py — Financeiro Pessoal F2B (Track P2).

Tool Hermes NARROW que fala com o Cognitive (capabilities finance.*),
preservando authorization/tenancy/audit do caminho canônico. NUNCA acessa
SQLite/Pluggy diretamente — mesmo contrato de
hermes/p0-supabase-ops/supabase_ops_tools.py.

  User → Hermes (rota FINANCE) → finance → CognitiveApiAdapter → Cognitive
  → finance.* → FinanceApiAdapter (HTTP) → apps/financeiro-pessoal-api
  (SQLite, Pluggy) → dados → LLM fraseia.

Só registrado no toolset "finance". NORMAL_CHAT_TOOLS continua 0: estas
tools só entram no schema do turno quando capability_router.py resolve a
rota FINANCE (ver _ROUTE_TOOLSETS). Bash/general tools NÃO entram nessa rota.

F2B: channel/chat_id/user_id/transport_principal NÃO entram no FINANCE_SCHEMA.
O handler lê ContextEnvelope trusted via turn_context (ligado pelo gateway).
Args LLM com esses campos são IGNORADOS (não autorizam transporte).

Ops F2B de pendência (clarifications) mapeiam para finance.clarification.list
— contagem/listagem dinâmica real; nunca cache/grep/bash/filesystem.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from tools.registry import registry, tool_error

logger = logging.getLogger(__name__)

# Campos de identidade/transporte — NUNCA do schema LLM; se vierem em args, ignore.
_TRANSPORT_SPOOF_KEYS = frozenset(
    {
        "channel",
        "chat_id",
        "user_id",
        "transport_principal",
        "is_group",
        "incoming_message_id",
        "reply_to_message_id",
    }
)

_PENDING_OPS = frozenset({"pending_count", "pending_list"})

FINANCE_SCHEMA = {
    "name": "finance",
    "description": (
        "Financeiro pessoal F2B via Cognitive (gastos, receitas, saldo, categorias, "
        "orcamento, faturas, sync bancario, pendencias/clarifications abertas). "
        "Nunca acessa o banco financeiro direto. Use pending_count/pending_list "
        "para quantas/quais pendencias financeiras (com filtro de mes de "
        "competencia). Nao use bash, filesystem, memory ou chute para isso."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": [
                    "summary", "transactions", "accounts", "bills",
                    "manual_create", "category_update",
                    "budget_read", "budget_write",
                    "sync_run", "sync_status",
                    "pending_count", "pending_list",
                ],
                "description": (
                    "summary = entradas/saidas/saldo do mes; "
                    "transactions = lista filtrada; accounts = contas e saldos; "
                    "bills = faturas a vencer; manual_create = registra despesa/receita; "
                    "category_update = reclassifica UMA transacao; budget_read/write = "
                    "orcamento; sync_run/status = sync bancario; "
                    "pending_count = quantas clarifications/pendencias (usa total "
                    "dinamico); pending_list = lista pendencias (status/mes/conta/limit)."
                ),
            },
            "month": {
                "type": "string",
                "description": (
                    "Mes YYYY-MM. Em summary/budget_* e mes do extrato; em "
                    "pending_count/pending_list e alias de competenceMonth. "
                    "Resolva 'agosto' para YYYY-MM real ANTES de chamar."
                ),
            },
            "competenceMonth": {
                "type": "string",
                "description": (
                    "Filtro de competencia efetiva YYYY-MM para pending_*. "
                    "Preferir este campo; se ausente, month e usado como alias."
                ),
            },
            "status": {
                "type": "string",
                "enum": ["open", "snoozed", "resolved", "any"],
                "description": (
                    "Estado da clarification em pending_*. Default: open "
                    "(pendencias em aberto)."
                ),
            },
            "account": {
                "type": "string",
                "description": "Conta/cartao (alias) para filtrar pending_*.",
            },
            "category": {
                "type": "string",
                "description": "Nome livre da categoria (ex.: Alimentacao, Combustivel).",
            },
            "amount": {
                "type": "number",
                "description": "Valor em reais. Obrigatorio em manual_create.",
            },
            "direction": {
                "type": "string",
                "enum": ["in", "out"],
                "description": "in = receita/entrada, out = despesa/saida. Obrigatorio em manual_create.",
            },
            "description": {
                "type": "string",
                "description": (
                    "Descricao do lancamento. Obrigatoria em manual_create; em "
                    "category_update ajuda a identificar a transacao."
                ),
            },
            "date": {
                "type": "string",
                "description": (
                    "Data do lancamento em YYYY-MM-DD. Default: hoje. Resolva "
                    "ontem/anteontem para a data real ANTES de chamar."
                ),
            },
            "notes": {"type": "string", "description": "Observacao livre do lancamento."},
            "limitAmount": {
                "type": "number",
                "description": "Limite planejado em reais. Obrigatorio em budget_write.",
            },
            "search": {"type": "string", "description": "Busca textual em transactions."},
            "limit": {
                "type": "integer",
                "description": "Maximo de itens em transactions/bills/pending_list.",
            },
        },
        "required": ["operation"],
    },
}

# operation -> (capability_id, chaves aceitas, chaves obrigatorias)
_OPS: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "summary": ("finance.summary.read", ("month", "category"), ()),
    "transactions": ("finance.transactions.read", ("category", "search", "limit"), ()),
    "accounts": ("finance.accounts.read", (), ()),
    "bills": ("finance.bills.read", ("limit",), ()),
    "manual_create": (
        "finance.manual.create",
        ("amount", "direction", "description", "date", "category", "notes"),
        ("amount", "direction", "description"),
    ),
    "category_update": (
        "finance.category.update",
        ("description", "amount", "category"),
        ("category",),
    ),
    "budget_read": ("finance.budget.read", ("month",), ()),
    "budget_write": (
        "finance.budget.write",
        ("month", "limitAmount", "category"),
        ("month", "limitAmount"),
    ),
    "sync_run": ("finance.sync.run", (), ()),
    "sync_status": ("finance.sync.status", (), ()),
    # F2B clarifications — mesma capability; ops distintas para o LLM escolher
    # count vs list sem inventar filesystem/bash.
    "pending_count": (
        "finance.clarification.list",
        ("status", "competenceMonth", "month", "account", "limit"),
        (),
    ),
    "pending_list": (
        "finance.clarification.list",
        ("status", "competenceMonth", "month", "account", "limit"),
        (),
    ),
}


def _strip_transport_spoof(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Remove tentativas de spoof de identidade/transporte vindas do LLM."""
    return {k: v for k, v in kwargs.items() if k not in _TRANSPORT_SPOOF_KEYS}


def _build_params(
    operation: str,
    aceitas: tuple[str, ...],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    params = {k: kwargs[k] for k in aceitas if kwargs.get(k) not in (None, "")}
    if operation in _PENDING_OPS:
        # Default: só pendências abertas (Human Acceptance / fila real).
        params.setdefault("status", "open")
        if "competenceMonth" not in params and "month" in params:
            params["competenceMonth"] = params.pop("month")
        elif "month" in params and "competenceMonth" in params:
            params.pop("month", None)
        # pending_count não precisa de itens — limit baixo evita payload grande.
        if operation == "pending_count" and "limit" not in params:
            params["limit"] = 1
    return params


def _trusted_channel():
    from capability_intelligence.turn_context import (
        get_turn_envelope,
        trusted_channel_from_envelope,
    )

    return trusted_channel_from_envelope(get_turn_envelope())


def _call(capability_id: str, params: dict[str, Any]) -> dict:
    from capability_intelligence.finance_service import FinanceService

    _ensure_cognitive_env_from_dotenv()
    channel = _trusted_channel()
    return asyncio.run(
        FinanceService.from_env().call(capability_id, params, channel=channel)
    )


def finance(operation: str = "summary", **kwargs: Any) -> str:
    """Resolve operation -> monta params -> chama a capability finance.*.

    Retorna JSON string (contrato do registry: handler devolve str, nunca dict).
    Fail-closed: qualquer excecao vira tool_error, nunca sucesso fabricado.
    Resposta de ambiguidade/nao-encontrado chega como data com success=false e
    e repassada integra para o LLM desambiguar.

    kwargs de transporte (channel/chat_id/...) são IGNORADOS — só o envelope
    trusted do turno autoriza body.channel no Cognitive.
    """
    kwargs = _strip_transport_spoof(kwargs)
    spec = _OPS.get(operation)
    if spec is None:
        return tool_error(
            "operation desconhecida: " + str(operation),
            success=False,
            operation=operation,
        )
    capability_id, aceitas, obrigatorias = spec

    params = _build_params(operation, aceitas, kwargs)
    faltando = [k for k in obrigatorias if k not in params]
    if faltando:
        return tool_error(
            "parametro(s) obrigatorio(s) ausente(s) para operation="
            + str(operation)
            + ": "
            + ", ".join(faltando),
            success=False,
            operation=operation,
        )

    try:
        data = _call(capability_id, params)
    except Exception as exc:  # noqa: BLE001 — fail-closed; nunca mascarar
        return tool_error(str(exc)[:400], success=False, operation=operation)

    ok = bool(data.get("success", True)) if isinstance(data, dict) else True
    return json.dumps(
        {"operation": operation, "capability": capability_id, "ok": ok, "data": data},
        ensure_ascii=False,
        default=str,
    )


def check_finance_requirements() -> bool:
    """Disponivel quando o Hermes roda em gateway/mensageria ou interativo
    (mesmo gate de supabase_ops_tools.py e infra_read_tools.py)."""
    from utils import env_var_enabled

    return (
        env_var_enabled("HERMES_INTERACTIVE")
        or env_var_enabled("HERMES_GATEWAY_SESSION")
        or env_var_enabled("HERMES_EXEC_ASK")
    )


# --- Registry ---
registry.register(
    name="finance",
    toolset="finance",
    schema=FINANCE_SCHEMA,
    handler=lambda args, **kw: finance(
        operation=str(args.get("operation", "summary")),
        month=args.get("month"),
        competenceMonth=args.get("competenceMonth"),
        status=args.get("status"),
        account=args.get("account"),
        category=args.get("category"),
        amount=args.get("amount"),
        direction=args.get("direction"),
        description=args.get("description"),
        date=args.get("date"),
        notes=args.get("notes"),
        limitAmount=args.get("limitAmount"),
        search=args.get("search"),
        limit=args.get("limit"),
        # Spoof deliberate: se o LLM injetar estes em args, finance() stripa.
        channel=args.get("channel"),
        chat_id=args.get("chat_id"),
        user_id=args.get("user_id"),
        transport_principal=args.get("transport_principal"),
    ),
    check_fn=check_finance_requirements,
)


def _ensure_cognitive_env_from_dotenv() -> None:
    """Garante COGNITIVE_* no os.environ a partir de HERMES_HOME/.env se ausente.

    O gateway pode descobrir tools antes de exportar o dotenv no process env.
    """
    import os
    from pathlib import Path

    if os.environ.get("COGNITIVE_GATEWAY_CREDENTIAL"):
        return
    home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
    env_path = home / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        if not key.startswith("COGNITIVE_"):
            continue
        if key not in os.environ or not os.environ.get(key):
            os.environ[key] = val.strip().strip('"').strip("'")


class _LazyFinanceCaller:
    """Caller que monta FinanceService só no primeiro uso (env já disponível)."""

    def __init__(self) -> None:
        self._svc = None

    async def call(
        self,
        capability_id: str,
        params: dict[str, Any],
        *,
        channel: Any = None,
    ) -> dict[str, Any]:
        if self._svc is None:
            _ensure_cognitive_env_from_dotenv()
            from capability_intelligence.finance_service import FinanceService

            self._svc = FinanceService.from_env()
        return await self._svc.call(capability_id, params, channel=channel)


def _wire_finance_router_hook() -> None:
    """Eager boot: FinanceReplyBinding disponível antes de qualquer mensagem Finance."""
    from capability_intelligence.finance_quoted_boot import (
        ensure_finance_quoted_binding_ready,
    )

    ensure_finance_quoted_binding_ready()


_wire_finance_router_hook()
