"""
supabase_ops_tools.py — Supabase Ops V1 (P0).

Tool Hermes NARROW que consulta/testa projetos Supabase via Cognitive
(capabilities supabase.*), preservando authorization/registry/audit do
caminho canônico. NUNCA acessa Compose MCP/Supabase diretamente — mesmo
contrato de hermes/phase1-infra-read/infra_read_tools.py.

  User → Hermes → supabase_ops → CognitiveApiAdapter → Cognitive
  → supabase.* → registry local / Compose MCP → dados → LLM fraseia.

Read-only para o projeto monitorado em TODAS as operações, inclusive
operation=test (query fixa SELECT now(), nunca SQL arbitrário — enforced no
Cognitive por adapters/composio/guard.py, não só aqui).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from tools.registry import registry, tool_error

SUPABASE_OPS_SCHEMA = {
    "name": "supabase_ops",
    "description": (
        "Consulta ou testa projetos Supabase conectados (anti-hibernação/keepalive). "
        "Usa o Cognitive com autorização do tenant — nunca acessa Supabase/MCP direto. "
        "operation=test executa uma query read-only real (SELECT now()) no projeto "
        "indicado; nunca aceita SQL arbitrário e nunca escreve no projeto monitorado."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["summary", "list_free", "problems", "status", "test"],
                "description": (
                    "summary = visão geral (total, Free/Paid, healthy/warning/última rodada); "
                    "list_free = só os projetos Free; "
                    "problems = só warning/failed/paused, com motivo seguro; "
                    "status = último keepalive de UM projeto (usa target); "
                    "test = roda keepalive agora em UM projeto (usa target)."
                ),
            },
            "target": {
                "type": "string",
                "description": (
                    "Nome (ou parte do nome) do projeto — ex.: 'Hermes', 'TimerProsper'. "
                    "Obrigatório para operation=status e operation=test."
                ),
            },
        },
        "required": ["operation"],
    },
}


def _run_summary() -> dict:
    from capability_intelligence.supabase_ops_service import SupabaseOpsService
    return asyncio.run(SupabaseOpsService.from_env().summary())


def _run_list_free() -> dict:
    from capability_intelligence.supabase_ops_service import SupabaseOpsService
    return asyncio.run(SupabaseOpsService.from_env().list_projects(plan="free"))


def _run_problems() -> dict:
    from capability_intelligence.supabase_ops_service import SupabaseOpsService
    return asyncio.run(SupabaseOpsService.from_env().problems())


def _run_status(target: str) -> dict:
    from capability_intelligence.supabase_ops_service import SupabaseOpsService
    return asyncio.run(SupabaseOpsService.from_env().status_of(target))


def _run_test(target: str) -> dict:
    from capability_intelligence.supabase_ops_service import SupabaseOpsService
    return asyncio.run(SupabaseOpsService.from_env().test_now(target))


def supabase_ops(operation: str = "summary", target: str = "", **kwargs: Any) -> str:
    """Handler da tool: resolve operation -> chama o service certo -> retorna
    JSON string (contrato do registry: handlers devem retornar str/JSON —
    dict é rejeitado). Fail-closed: qualquer exceção vira tool_error, nunca
    um sucesso fabricado."""
    try:
        if operation == "summary":
            data = _run_summary()
        elif operation == "list_free":
            data = _run_list_free()
        elif operation == "problems":
            data = _run_problems()
        elif operation == "status":
            if not target:
                return tool_error(
                    "target é obrigatório para operation=status",
                    success=False, operation=operation, target=target,
                )
            data = _run_status(target)
        elif operation == "test":
            if not target:
                return tool_error(
                    "target é obrigatório para operation=test",
                    success=False, operation=operation, target=target,
                )
            data = _run_test(target)
        else:
            return tool_error(
                f"operation desconhecida: {operation}",
                success=False, operation=operation, target=target,
            )
        return json.dumps(
            {"operation": operation, "target": target or "all", "ok": True, "data": data},
            ensure_ascii=False, default=str,
        )
    except Exception as exc:  # noqa: BLE001 — fail-closed; nunca mascarar
        return tool_error(
            str(exc)[:400], success=False, operation=operation, target=target or "",
        )


def check_supabase_ops_requirements() -> bool:
    """Disponível quando o Hermes roda em gateway/mensageria ou interativo
    (mesmo gate de hermes/phase1-infra-read/infra_read_tools.py)."""
    from utils import env_var_enabled
    return (
        env_var_enabled("HERMES_INTERACTIVE")
        or env_var_enabled("HERMES_GATEWAY_SESSION")
        or env_var_enabled("HERMES_EXEC_ASK")
    )


# --- Registry ---
registry.register(
    name="supabase_ops",
    toolset="supabase_ops",
    schema=SUPABASE_OPS_SCHEMA,
    handler=lambda args, **kw: supabase_ops(
        operation=str(args.get("operation", "summary")),
        target=str(args.get("target", "") or ""),
    ),
    check_fn=check_supabase_ops_requirements,
)
