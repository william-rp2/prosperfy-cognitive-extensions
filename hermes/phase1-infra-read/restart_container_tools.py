"""
restart_container_tools.py — Infra Actions V1 (Phase 1B, Slice 1).

Tool Hermes NARROW de restart de container. NUNCA SSH/Docker/MCP direto —
toda execução passa pelo Cognitive (capability infra.action), preservando
tenant/actor/policy/audit/resource resolution via ProsperfySkillAdapter.

Confirmação em 2 turnos (obrigatória — mutação):
  1º turno: resolve resource+container → retorna pedido de confirmação (NÃO executa)
  2º turno: "Sim" com confirmed=true + MESMO actor/resource/container/action → executa

Fail-closed: container inexistente → erro claro (sem autocompletar nome).
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

from tools.registry import registry, tool_error

RESTART_CONTAINER_SCHEMA = {
    "name": "restart_container",
    "description": (
        "Reinicia um container em um servidor, via Cognitive (infra.action). "
        "MUTAÇÃO: requer confirmação explícita (confirmed=true) no segundo turno, "
        "vinculada ao mesmo actor/resource/container/action. NUNCA executa na primeira chamada."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "resource": {
                "type": "string",
                "description": "Servidor (display name: Prosperfy, Black, Manager1, Hostinger One) "
                               "ou resource_key.",
            },
            "container": {
                "type": "string",
                "description": "Nome do container a reiniciar (ex.: omniroute, traefik).",
            },
            "confirmed": {
                "type": "boolean",
                "description": "Confirmação explícita do usuário (2º turno). Requer que o "
                               "pending action do MESMO actor/resource/container/action exista.",
            },
        },
        "required": ["resource", "container"],
    },
}

# Pending actions por actor (in-process, sem persistir) — vincula confirmação.
_lock = threading.Lock()
_pending: dict[str, dict[str, Any]] = {}


def _pending_key(actor: str, resource: str, container: str) -> str:
    return f"{actor}|{resource}|{container}|restart_container"


def has_pending_restart_for_actor(actor: str) -> bool:
    """Read-only: existe pending restart para este actor? Não remove nem cria pending."""
    if not actor:
        return False
    with _lock:
        return any(entry.get("actor") == actor for entry in _pending.values())


def _resolve_resource(meta: list[dict], name: str) -> str | None:
    low = (name or "").strip().lower()
    for r in meta:
        if r["resource_key"].lower() == low or (r.get("display_name") or "").lower() == low:
            return r["resource_key"]
    for r in meta:
        if low in r["resource_key"].lower() or low in (r.get("display_name") or "").lower():
            return r["resource_key"]
    return None


def _cognitive_restart(resource_key: str, container: str, actor: str, tenant: str) -> dict:
    """Executa infra.action via Cognitive (capability a provisionar). Fail-closed."""
    from capability_intelligence.transport.cognitive_api_adapter import CognitiveApiAdapter, ExecutionRequest
    adapter = CognitiveApiAdapter()
    req = ExecutionRequest(
        capability_id="infra.action",
        params={
            "resource": resource_key,
            "action": "restart",
            "target_type": "container",
            "target": container,
        },
    )
    try:
        ref = asyncio.run(adapter.execute(req))
        result = asyncio.run(adapter.get_result(ref))
        if not result.success:
            return {"ok": False, "error": result.error or "infra.action falhou"}
        return {"ok": True, "data": result.data}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}


def restart_container(resource: str = "", container: str = "", confirmed: bool = False, **kwargs: Any) -> str:
    """Handler: resolve → confirmação (2 turnos) → executa via Cognitive."""
    from capability_intelligence.infra_service import InfraService
    svc = InfraService.from_env()
    actor = svc._adapter._actor_id or "unknown"

    try:
        meta = asyncio.run(svc._adapter.list_resources())
    except Exception:
        meta = []
    resource_key = _resolve_resource(meta, resource)

    if not resource_key:
        return tool_error(
            f"Resource '{resource or '?'}' não resolvido entre os servidores autorizados.",
            success=False,
        )
    if not container or not container.strip():
        return tool_error("Container não informado.", success=False)

    pkey = _pending_key(actor, resource_key, container)
    if not confirmed:
        # 1º turno: registra pending + pede confirmação (NUNCA executa)
        with _lock:
            _pending[pkey] = {
                "actor": actor,
                "resource": resource_key,
                "container": container,
                "action": "restart_container",
                "created_at": time.time(),
            }
        return json.dumps({
            "action": "restart_container",
            "resource": resource_key,
            "container": container,
            "confirmed": False,
            "message": f"Confirma reiniciar o container '{container}' no servidor '{resource}'? "
                       f"Responda 'Sim' para executar.",
        }, ensure_ascii=False)

    # 2º turno: só executa se o pending do MESMO actor/resource/container existir
    with _lock:
        pending = _pending.pop(pkey, None)
    if pending is None or pending["actor"] != actor:
        return tool_error(
            "Nenhuma ação pendente de restart válida para este actor/resource/container. "
            "Peça o restart novamente.",
            success=False,
        )

    result = _cognitive_restart(resource_key, container, actor, svc._adapter._tenant_id)
    if not result["ok"]:
        return tool_error(result["error"], success=False)

    # Post-condition: re-lê containers do resource (leitura real nova)
    try:
        view = asyncio.run(svc.servers_status(resource=resource_key))
        containers = view.get("normalized", {}).get("containers", [])
    except Exception:
        containers = []
    return json.dumps({
        "action": "restart_container",
        "resource": resource_key,
        "container": container,
        "confirmed": True,
        "result": result.get("data"),
        "post_containers": containers,
    }, ensure_ascii=False)


def check_restart_container_requirements() -> bool:
    from utils import env_var_enabled
    return (
        env_var_enabled("HERMES_INTERACTIVE")
        or env_var_enabled("HERMES_GATEWAY_SESSION")
        or env_var_enabled("HERMES_EXEC_ASK")
    )


registry.register(
    name="restart_container",
    toolset="restart_container",
    schema=RESTART_CONTAINER_SCHEMA,
    handler=lambda args, **kw: restart_container(
        resource=str(args.get("resource", "") or ""),
        container=str(args.get("container", "") or ""),
        confirmed=bool(args.get("confirmed", False)),
    ),
    check_fn=check_restart_container_requirements,
)


def _wire_routing_continuation() -> None:
    try:
        from capability_intelligence.capability_router import set_pending_restart_checker
        set_pending_restart_checker(has_pending_restart_for_actor)
    except ImportError:
        pass


_wire_routing_continuation()