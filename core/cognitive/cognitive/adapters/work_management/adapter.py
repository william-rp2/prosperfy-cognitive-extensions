"""
adapters/work_management/adapter.py — WorkManagementAdapter (Track P1).

Implementa SkillsAdapterPort (mesmo contrato de ProsperfySkillsAdapter) mas
dispatcha localmente para WorkService em vez de falar MCP com um servidor
externo — não existe "tool remota" aqui, o Cognitive Gateway É o dono do
domínio Work Management (Supabase = source of truth).

tool_name == capability_id (work.idea.create, work.task.update, ...) —
todas as capabilities work.* são declaradas SEM `tools:` no YAML, então o
ExecutionOrchestrator (_run_capability_tools, branch "sem steps") invoca
`adapter.invoke_tool(tool_name=capability_id, arguments=client_args, ...)`
diretamente — exatamente o dispatch que este adapter espera.

actor_id: SkillsAdapterPort.invoke_tool não recebe actor_id (só
tool_name/arguments/tenant_id/correlation_id) — mas WorkEvent precisa do
actor real para o histórico. O orchestrator (ver execution/orchestrator.py,
extensão "adapters" registry) injeta `_ctx_actor_id` em `arguments` ANTES de
chamar adapters fora do path prosperfy_skills — nunca um valor
client-controlled (o cliente não pode declarar seu próprio actor_id no
body; ADR-V2-002). Se a chave não vier, falha fechado (RuntimeError) em vez
de gravar um WorkEvent com actor_id fabricado/errado.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from ...services.work_service import WorkService

logger = logging.getLogger(__name__)


class WorkManagementAdapter:
    """Adapter local (sem transporte de rede) para as capabilities work.*."""

    def __init__(self, service: WorkService) -> None:
        self._service = service
        self._dispatch: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {
            "work.idea.create": service.idea_create,
            "work.idea.list": service.idea_list,
            "work.idea.get": service.idea_get,
            "work.idea.update": service.idea_update,
            "work.project.create": service.project_create,
            "work.project.list": service.project_list,
            "work.project.get": service.project_get,
            "work.project.update": service.project_update,
            "work.task.create": service.task_create,
            "work.task.list": service.task_list,
            "work.task.get": service.task_get,
            "work.task.update": service.task_update,
            "work.task.link": service.task_link,
            "work.summary": service.summary,
            "work.sync.status": service.sync_status,
        }

    async def invoke_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        tenant_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        handler = self._dispatch.get(tool_name)
        if handler is None:
            raise RuntimeError(
                f"WorkManagementAdapter: capability '{tool_name}' desconhecida "
                f"(esperado uma de {sorted(self._dispatch)})"
            )

        params = dict(arguments)
        actor_id = params.pop("_ctx_actor_id", None)
        params.pop("_ctx_profile", None)
        if not actor_id or not isinstance(actor_id, str):
            # Fail-closed: sem actor_id real não gravamos WorkEvent nenhum —
            # nunca inventa "system"/"unknown" silenciosamente.
            raise RuntimeError(
                "WorkManagementAdapter: actor_id não propagado pelo orchestrator "
                "(_ctx_actor_id ausente) — verificar wiring do adapters registry."
            )

        logger.debug(
            "WorkManagementAdapter.invoke_tool cap=%s tenant=%s actor=%s correlation=%s",
            tool_name, tenant_id, actor_id, correlation_id,
        )

        try:
            data = await handler(
                tenant_id=tenant_id,
                actor_id=actor_id,
                correlation_id=correlation_id,
                params=params,
            )
        except ValueError as exc:
            # Erro de validação de input (campo obrigatório ausente, enum
            # inválido, id inexistente) — nunca finge sucesso.
            raise RuntimeError(f"work_management [{tool_name}]: {exc}") from None

        return {"success": True, "data": data}

    async def health(self) -> bool:
        """Sem transporte externo — sempre disponível se o processo está de pé."""
        return True
