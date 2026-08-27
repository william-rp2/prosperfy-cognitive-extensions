"""
supabase_ops_service.py — Serviço fino do Hermes para a vertical Supabase Ops (P0).

Ponto único do Hermes para as perguntas operacionais de Supabase
("Como estão meus Supabases?", "Quais são Free?", "Algum com problema?",
"Quando foi o último keepalive do X?", "Teste agora o Supabase X"),
delegando TUDO ao Cognitive (mesmo padrão de infra_service.py):

    Hermes → CognitiveApiAdapter → Cognitive API → Policy/Registry
    → adapter (supabase_registry local ou Compose MCP) → resultado → Hermes

O Hermes NÃO duplica aqui policy / tenant authorization / SQL allowlist —
tudo isso vive no Cognitive e é alcançado via as capabilities supabase.*.

Determinístico, sem LLM escolhendo QUAL capability chamar (a tool
supabase_ops_tools.py já resolve isso por `operation`). Falha fechada:
qualquer erro do Cognitive/transporte propaga como exceção — o handler da
tool (supabase_ops_tools.py) é quem converte isso em tool_error, nunca há
fallback silencioso para MCP direto.
"""

from __future__ import annotations

from typing import Any

from .transport.cognitive_api_adapter import CognitiveApiAdapter

CAP_PROJECTS_READ = "supabase.projects.read"
CAP_KEEPALIVE_STATUS = "supabase.keepalive.status"
CAP_KEEPALIVE_RUN = "supabase.keepalive.run"
CAP_OPS_SUMMARY = "supabase.ops.summary"

_PROBLEM_STATUSES = ("warning", "failed", "paused")


class SupabaseOpsService:
    """Responde as perguntas operacionais de Supabase via Cognitive."""

    def __init__(self, adapter: CognitiveApiAdapter) -> None:
        self._adapter = adapter

    @classmethod
    def from_env(cls) -> "SupabaseOpsService":
        """Monta a partir de env vars do CognitiveApiAdapter
        (COGNITIVE_GATEWAY_URL / CREDENTIAL / TENANT_ID / ACTOR_ID)."""
        return cls(CognitiveApiAdapter())

    async def _execute(self, capability_id: str, params: dict[str, Any]) -> dict[str, Any]:
        from .models import ExecutionRequest

        ref = await self._adapter.execute(
            ExecutionRequest(capability_id=capability_id, params=params),
        )
        result = await self._adapter.get_result(ref)
        if not result.success:
            raise RuntimeError(result.error or f"Execução de {capability_id} falhou")
        return result.data or {}

    async def summary(self) -> dict[str, Any]:
        """'Como estão meus Supabases?' — contagem por plano/status + última rodada."""
        return await self._execute(CAP_OPS_SUMMARY, {})

    async def list_projects(self, plan: str | None = None) -> dict[str, Any]:
        """'Quais Supabases são Free?' — plan='free' filtra no Cognitive."""
        params: dict[str, Any] = {"plan": plan} if plan else {}
        return await self._execute(CAP_PROJECTS_READ, params)

    async def problems(self) -> dict[str, Any]:
        """'Algum Supabase está com problema?' — só warning/failed/paused,
        com motivo seguro (last_error_code já sanitizado pelo Cognitive)."""
        data = await self._execute(CAP_OPS_SUMMARY, {})
        projects = data.get("projects", [])
        problem_projects = [p for p in projects if p.get("status") in _PROBLEM_STATUSES]
        return {"summary": data.get("summary", {}), "projects": problem_projects}

    async def status_of(self, name_query: str) -> dict[str, Any]:
        """'Quando foi o último keepalive do X?' — timestamp/latência/resultado."""
        return await self._execute(CAP_KEEPALIVE_STATUS, {"name_query": name_query})

    async def test_now(self, name_query: str) -> dict[str, Any]:
        """'Teste agora o Supabase X' — resolve nome -> (ref, account) via
        keepalive.status (registry local, nunca rede) e então executa
        supabase.keepalive.run de verdade (read-only, query fixa) contra
        ESSE projeto exato. Ambíguo (>1 match) ou não encontrado (0 match)
        NUNCA executa — devolve a lista/():'found': False para o LLM
        desambiguar com o usuário em vez de adivinhar o alvo."""
        status = await self._execute(CAP_KEEPALIVE_STATUS, {"name_query": name_query})
        projects = status.get("projects", [])
        if not projects:
            return {"found": False, "name_query": name_query}
        if len(projects) > 1:
            return {"found": True, "ambiguous": True, "matches": projects}

        project = projects[0]
        run_result = await self._execute(
            CAP_KEEPALIVE_RUN,
            {
                "ref": project["project_ref"],
                "account": project["composio_account"],
                "query": "SELECT now()",
            },
        )
        return {
            "found": True,
            "ambiguous": False,
            "project": project,
            "result": run_result,
        }
