"""
work_management_tools.py — Work Management V1 (Track P1).

Tools Hermes NARROW que falam com o Cognitive (work.* capabilities),
preservando authorization/tenancy/persistência/outbox do caminho canônico.
NUNCA acessa Supabase/Trello diretamente — sempre via
capability_intelligence.work_management_service.WorkManagementService.

  User → Hermes (rota WORK_MANAGEMENT) → work_idea/work_project/work_task/
  work_summary/work_sync_status → CognitiveApiAdapter → Cognitive
  → work.* capability → WorkManagementAdapter → WorkService → Supabase
  (+ outbox → TrelloAdapter, assíncrono)

Só registrado no toolset "work_management" — mesmo padrão de
infra_read_tools.py (toolset "infra_read"). NORMAL_CHAT_TOOLS continua 0:
estas tools só entram no schema do turno quando capability_router.py
resolve a rota WORK_MANAGEMENT (ver _ROUTE_TOOLSETS).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from tools.registry import registry, tool_error

_IDEA_ACTIONS = ("create", "list", "get", "update")
_PROJECT_ACTIONS = ("create", "list", "get", "update")
_TASK_ACTIONS = ("create", "list", "get", "update", "link")

_IDEA_CAP = {
    "create": "work.idea.create", "list": "work.idea.list",
    "get": "work.idea.get", "update": "work.idea.update",
}
_PROJECT_CAP = {
    "create": "work.project.create", "list": "work.project.list",
    "get": "work.project.get", "update": "work.project.update",
}
_TASK_CAP = {
    "create": "work.task.create", "list": "work.task.list",
    "get": "work.task.get", "update": "work.task.update",
    "link": "work.task.link",
}


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    """Remove chaves None/''/[]/action — nunca manda ruído pro input_schema
    da capability (a maioria dos campos é opcional por ação)."""
    return {
        k: v for k, v in d.items()
        if k != "action" and v is not None and v != "" and v != []
    }


def _run(capability_id: str, params: dict[str, Any]) -> dict[str, Any]:
    from capability_intelligence.work_management_service import WorkManagementService
    svc = WorkManagementService.from_env()
    return asyncio.run(svc.call(capability_id, params))


# ─── work_idea ──────────────────────────────────────────────────────────

WORK_IDEA_SCHEMA = {
    "name": "work_idea",
    "description": (
        "Cria, lista, busca ou atualiza Ideias no Cognitive (Supabase canônico). "
        "'Anote uma ideia: X' -> action=create. 'Vincule essa ideia ao projeto Y' -> "
        "action=update com project_ids. 'Transforme essa ideia em projeto' -> use work_project "
        "action=create com from_idea_id."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(_IDEA_ACTIONS)},
            "idea_id": {"type": "string", "description": "Obrigatório para get/update."},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "status": {
                "type": "string",
                "enum": ["inbox", "evaluating", "approved", "rejected", "converted", "archived"],
            },
            "source": {"type": "string"},
            "impact": {"type": "string", "enum": ["low", "medium", "high"]},
            "value_notes": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "project_ids": {
                "type": "array", "items": {"type": "string"},
                "description": "Projects para vincular (create ou update, aditivo).",
            },
            "include_archived": {"type": "boolean"},
            "limit": {"type": "integer"},
        },
        "required": ["action"],
    },
}


def work_idea(**args: Any) -> str:
    action = str(args.get("action", ""))
    if action not in _IDEA_ACTIONS:
        return tool_error(f"action inválida: '{action}' (use {_IDEA_ACTIONS})", success=False)
    try:
        data = _run(_IDEA_CAP[action], _clean(dict(args)))
        return json.dumps({"ok": True, "action": action, "data": data}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 — fail-closed, nunca mascarar
        return tool_error(str(exc)[:400], success=False, action=action)


# ─── work_project ───────────────────────────────────────────────────────

WORK_PROJECT_SCHEMA = {
    "name": "work_project",
    "description": (
        "Cria, lista, busca ou atualiza Projetos no Cognitive. Use from_idea_id em "
        "action=create para 'transforme essa ideia em um projeto' (a Idea vira "
        "status=converted e fica vinculada ao Project criado)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(_PROJECT_ACTIONS)},
            "project_id": {"type": "string", "description": "Obrigatório para get/update."},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "status": {
                "type": "string",
                "enum": ["planned", "active", "on_hold", "completed", "cancelled", "archived"],
            },
            "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
            "owner": {"type": "string"},
            "start_date": {"type": "string", "description": "ISO date (YYYY-MM-DD)."},
            "due_date": {"type": "string", "description": "ISO date (YYYY-MM-DD)."},
            "tags": {"type": "array", "items": {"type": "string"}},
            "idea_ids": {"type": "array", "items": {"type": "string"}},
            "from_idea_id": {"type": "string", "description": "Converte esta Idea em Project."},
            "include_archived": {"type": "boolean"},
            "limit": {"type": "integer"},
        },
        "required": ["action"],
    },
}


def work_project(**args: Any) -> str:
    action = str(args.get("action", ""))
    if action not in _PROJECT_ACTIONS:
        return tool_error(f"action inválida: '{action}' (use {_PROJECT_ACTIONS})", success=False)
    try:
        data = _run(_PROJECT_CAP[action], _clean(dict(args)))
        return json.dumps({"ok": True, "action": action, "data": data}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return tool_error(str(exc)[:400], success=False, action=action)


# ─── work_task ──────────────────────────────────────────────────────────

WORK_TASK_SCHEMA = {
    "name": "work_task",
    "description": (
        "Cria, lista, busca, atualiza ou vincula Tarefas no Cognitive. "
        "'Mova a tarefa X para concluído' -> action=update status=done. "
        "'Quais tarefas estão bloqueadas?' -> action=list blocked_only=true. "
        "'Essa tarefa depende da tarefa Y' -> action=link link_type=depends_on target_id=Y."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(_TASK_ACTIONS)},
            "task_id": {"type": "string", "description": "Obrigatório para get/update/link."},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "status": {
                "type": "string",
                "enum": ["todo", "in_progress", "blocked", "waiting", "done", "cancelled", "archived"],
            },
            "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
            "assignee": {"type": "string"},
            "due_at": {"type": "string", "description": "ISO datetime."},
            "source": {"type": "string"},
            "project_ids": {"type": "array", "items": {"type": "string"}},
            "idea_ids": {"type": "array", "items": {"type": "string"}},
            "depends_on_task_id": {"type": "string", "description": "Só em action=create."},
            "link_type": {
                "type": "string", "enum": ["project", "idea", "depends_on"],
                "description": "Obrigatório em action=link.",
            },
            "target_id": {"type": "string", "description": "Obrigatório em action=link."},
            "assignee_filter": {"type": "string", "description": "Filtro de assignee em action=list."},
            "project_id": {"type": "string", "description": "Filtro de project em action=list."},
            "blocked_only": {"type": "boolean"},
            "include_archived": {"type": "boolean"},
            "limit": {"type": "integer"},
        },
        "required": ["action"],
    },
}


def work_task(**args: Any) -> str:
    action = str(args.get("action", ""))
    if action not in _TASK_ACTIONS:
        return tool_error(f"action inválida: '{action}' (use {_TASK_ACTIONS})", success=False)
    payload = dict(args)
    # assignee_filter -> assignee só no modo list (evita colidir com o campo
    # 'assignee' de create/update, que tem semântica de "definir responsável").
    if action == "list" and payload.get("assignee_filter"):
        payload["assignee"] = payload.pop("assignee_filter")
    else:
        payload.pop("assignee_filter", None)
    try:
        data = _run(_TASK_CAP[action], _clean(payload))
        return json.dumps({"ok": True, "action": action, "data": data}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return tool_error(str(exc)[:400], success=False, action=action)


# ─── work_summary / work_sync_status ────────────────────────────────────

WORK_SUMMARY_SCHEMA = {
    "name": "work_summary",
    "description": (
        "Resumo de tarefas por status (tenant-wide ou de um Project), contagem de "
        "bloqueadas e totais de projects/ideas. 'O que falta para terminar o "
        "projeto X?' -> project_id=X."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
        },
        "required": [],
    },
}


def work_summary(**args: Any) -> str:
    try:
        data = _run("work.summary", _clean(dict(args)))
        return json.dumps({"ok": True, "data": data}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return tool_error(str(exc)[:400], success=False)


WORK_SYNC_STATUS_SCHEMA = {
    "name": "work_sync_status",
    "description": "Status de sincronização com o Trello — outbox pendente/falhado e board/listas vinculados.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}


def work_sync_status(**_args: Any) -> str:
    try:
        data = _run("work.sync.status", {})
        return json.dumps({"ok": True, "data": data}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return tool_error(str(exc)[:400], success=False)


def check_work_management_requirements() -> bool:
    """Disponível quando o Hermes roda em gateway/mensageria ou interativo —
    mesmo gate de infra_read_tools.py."""
    from utils import env_var_enabled
    return (
        env_var_enabled("HERMES_INTERACTIVE")
        or env_var_enabled("HERMES_GATEWAY_SESSION")
        or env_var_enabled("HERMES_EXEC_ASK")
    )


# --- Registry ---
registry.register(
    name="work_idea",
    toolset="work_management",
    schema=WORK_IDEA_SCHEMA,
    handler=lambda args, **kw: work_idea(**args),
    check_fn=check_work_management_requirements,
)
registry.register(
    name="work_project",
    toolset="work_management",
    schema=WORK_PROJECT_SCHEMA,
    handler=lambda args, **kw: work_project(**args),
    check_fn=check_work_management_requirements,
)
registry.register(
    name="work_task",
    toolset="work_management",
    schema=WORK_TASK_SCHEMA,
    handler=lambda args, **kw: work_task(**args),
    check_fn=check_work_management_requirements,
)
registry.register(
    name="work_summary",
    toolset="work_management",
    schema=WORK_SUMMARY_SCHEMA,
    handler=lambda args, **kw: work_summary(**args),
    check_fn=check_work_management_requirements,
)
registry.register(
    name="work_sync_status",
    toolset="work_management",
    schema=WORK_SYNC_STATUS_SCHEMA,
    handler=lambda args, **kw: work_sync_status(**args),
    check_fn=check_work_management_requirements,
)
