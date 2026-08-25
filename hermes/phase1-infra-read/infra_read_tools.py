"""
infra_read_tools.py — Infra Read V1 (Phase 1A).

Tool Hermes NARROW que consulta infraestrutura via Cognitive (infra.inspect),
preservando authorization/resource resolution/fail-closed do caminho canônico
(/servidores). NUNCA acessa MCP/SSH/Docker diretamente.

  User → Hermes → infra_read → CognitiveApiAdapter → Cognitive → infra.inspect
  → ProsperfySkillAdapter → MCP → servidor real → dados → LLM fraseia.

Read-only: NÃO executa restart/stop/start/delete/prune (Phase 1B).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from tools.registry import registry, tool_error

INFRA_READ_SCHEMA = {
    "name": "infra_read",
    "description": (
        "Consulta read-only de infraestrutura (servidores/containers/portas). "
        "Usa o Cognitive com autorização e resource resolution do tenant. "
        "NÃO executa nenhuma ação de escrita."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["all", "panorama", "containers", "ports"],
                "description": "all = status completo dos servidores; panorama = visão geral; "
                               "containers = lista de containers; ports = portas abertas.",
            },
            "resource": {
                "type": "string",
                "description": "Servidor específico (nome de exibição: Prosperfy, Black, "
                               "Manager1, Hostinger One) ou resource_key. Omitir = todos.",
            },
        },
        "required": ["operation"],
    },
}


def _resource_by_name(resources: list[dict], name: str) -> str | None:
    """Resolve nome de exibição ou resource_key para a chave canônica."""
    if not name:
        return None
    low = name.strip().lower()
    for r in resources:
        if r["resource_key"].lower() == low:
            return r["resource_key"]
    for r in resources:
        if (r.get("display_name") or "").lower() == low:
            return r["resource_key"]
    # Prefixo: "prosperfy" -> "prosperfy-vps-homolog"; "manager1" -> key manager1...
    for r in resources:
        if low in r["resource_key"].lower() or low in (r.get("display_name") or "").lower():
            return r["resource_key"]
    return None


def _run_servidores() -> dict:
    from capability_intelligence.infra_service import InfraService
    return asyncio.run(InfraService.from_env().servidores_status())


def _run_one_impl(resource: str) -> dict:
    from capability_intelligence.infra_service import InfraService
    svc = InfraService.from_env()
    return asyncio.run(svc.servers_status(resource=resource))


def infra_read(operation: str = "all", resource: str = "", **kwargs: Any) -> dict:
    """Handler da tool: resolve resource → executa via Cognitive → retorna visão."""
    from capability_intelligence.infra_service import InfraService
    svc = InfraService.from_env()

    try:
        meta = asyncio.run(svc._adapter.list_resources())
    except Exception:
        meta = []

    resource_key = _resource_by_name(meta, resource) if resource else None

    try:
        if resource_key:
            view = asyncio.run(svc.servers_status(resource=resource_key))
            view["display_name"] = resource_key
            return {
                "operation": operation,
                "resource": resource,
                "resource_key": resource_key,
                "ok": True,
                "summary": view.get("summary", ""),
                "normalized": view.get("normalized", {}),
            }
        view = asyncio.run(svc.servidores_status())
        return {
            "operation": operation,
            "resource": "all",
            "ok": True,
            "summary": view.get("summary", ""),
            "normalized": view.get("normalized", {}),
        }
    except Exception as exc:  # noqa: BLE001 — fail-closed por resource; nunca mascarar
        return {
            "operation": operation,
            "resource": resource or "all",
            "resource_key": resource_key,
            "ok": False,
            "error": str(exc)[:400],
        }


def check_infra_read_requirements() -> bool:
    """Disponível quando o Hermes roda em gateway/mensageria ou interativo."""
    from utils import env_var_enabled
    return (
        env_var_enabled("HERMES_INTERACTIVE")
        or env_var_enabled("HERMES_GATEWAY_SESSION")
        or env_var_enabled("HERMES_EXEC_ASK")
    )


# --- Registry ---
registry.register(
    name="infra_read",
    toolset="infra_read",
    schema=INFRA_READ_SCHEMA,
    handler=lambda args, **kw: infra_read(
        operation=str(args.get("operation", "all")),
        resource=str(args.get("resource", "") or ""),
    ),
    check_fn=check_infra_read_requirements,
)