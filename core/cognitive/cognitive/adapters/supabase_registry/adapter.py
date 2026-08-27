"""
adapters/supabase_registry/adapter.py — SupabaseRegistryAdapter.

Terceiro adapter do orchestrator (ao lado de prosperfy_skills e composio):
zero chamada de rede — só expõe leituras do registry local
(supabase_projects / supabase_keepalive_runs) atrás do MESMO contrato
SkillsAdapterPort, para que supabase.projects.read / keepalive.status /
ops.summary reusem policy/grant/audit do ExecutionOrchestrator sem
duplicar nenhuma dessas camadas (ver execution/orchestrator.py
_select_adapter — roteamento por capability.adapter == "supabase_registry").

tool_name reconhecidos — allowlist fechada, qualquer outro levanta
RuntimeError (nunca um passthrough genérico):
  "supabase_registry.list_projects"
  "supabase_registry.get_project_status"
  "supabase_registry.summary"
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from ...db.repositories.supabase_ops_repo import (
    SupabaseKeepaliveRunRepository,
    SupabaseProjectRepository,
    SupabaseProjectRow,
)

logger = logging.getLogger(__name__)

LIST_PROJECTS = "supabase_registry.list_projects"
GET_PROJECT_STATUS = "supabase_registry.get_project_status"
SUMMARY = "supabase_registry.summary"

_ALLOWED_TOOLS = frozenset({LIST_PROJECTS, GET_PROJECT_STATUS, SUMMARY})


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _project_public_dict(row: SupabaseProjectRow) -> dict[str, Any]:
    """Metadata segura para output de capability (WhatsApp/humano) — nunca
    inclui composio_account (identificador interno de roteamento, não
    secret, mas irrelevante fora do Cognitive) nem tenant_id (redundante,
    já é o escopo da própria chamada)."""
    return {
        "project_ref": row.project_ref,
        "display_name": row.display_name,
        "region": row.region,
        "plan": row.plan,
        "plan_source": row.plan_source,
        "keepalive_enabled": row.keepalive_enabled,
        "status": row.status,
        "last_success_at": _iso(row.last_success_at),
        "last_latency_ms": row.last_latency_ms,
        "consecutive_failures": row.consecutive_failures,
        "last_error_code": row.last_error_code,
        "next_run_at": _iso(row.next_run_at),
    }


class SupabaseRegistryAdapter:
    """Adapter read-only sobre o registry local. Implementa SkillsAdapterPort."""

    def __init__(
        self,
        project_repo: SupabaseProjectRepository | None = None,
        run_repo: SupabaseKeepaliveRunRepository | None = None,
    ) -> None:
        self._projects = project_repo or SupabaseProjectRepository()
        self._runs = run_repo or SupabaseKeepaliveRunRepository()

    async def invoke_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        tenant_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        if tool_name not in _ALLOWED_TOOLS:
            raise RuntimeError(
                f"SupabaseRegistryAdapter: tool '{tool_name}' não reconhecida "
                f"(allowlist: {sorted(_ALLOWED_TOOLS)})."
            )

        if tool_name == LIST_PROJECTS:
            return await self._list_projects(arguments, tenant_id)
        if tool_name == GET_PROJECT_STATUS:
            return await self._get_project_status(arguments, tenant_id)
        return await self._summary(tenant_id)

    async def _list_projects(self, arguments: dict[str, Any], tenant_id: str) -> dict[str, Any]:
        plan_filter = arguments.get("plan")
        rows = await self._projects.list_all(tenant_id)
        if plan_filter:
            rows = [r for r in rows if r.plan == plan_filter]
        return {"success": True, "data": {"projects": [_project_public_dict(r) for r in rows]}}

    async def _get_project_status(self, arguments: dict[str, Any], tenant_id: str) -> dict[str, Any]:
        project_ref = arguments.get("project_ref")
        name_query = arguments.get("name_query")
        if project_ref:
            row = await self._projects.get_by_ref(tenant_id, project_ref)
            matches = [row] if row else []
        elif name_query:
            matches = await self._projects.find_by_name(tenant_id, name_query)
        else:
            raise RuntimeError(
                "SupabaseRegistryAdapter.get_project_status requer "
                "'project_ref' ou 'name_query'."
            )

        projects_out = []
        for row in matches:
            recent_runs = await self._runs.list_recent_for_project(tenant_id, row.id, limit=3)
            projects_out.append({
                **_project_public_dict(row),
                "recent_runs": [
                    {
                        "status": rr.status,
                        "latency_ms": rr.latency_ms,
                        "error_code": rr.error_code,
                        "created_at": _iso(rr.created_at),
                    }
                    for rr in recent_runs
                ],
            })
        return {"success": True, "data": {"projects": projects_out}}

    async def _summary(self, tenant_id: str) -> dict[str, Any]:
        summary = await self._projects.summary(tenant_id)
        summary_out = {
            k: (_iso(v) if isinstance(v, datetime) else v) for k, v in summary.items()
        }
        rows = await self._projects.list_all(tenant_id)
        return {
            "success": True,
            "data": {
                "summary": summary_out,
                "projects": [_project_public_dict(r) for r in rows],
            },
        }

    async def health(self) -> bool:
        return True
