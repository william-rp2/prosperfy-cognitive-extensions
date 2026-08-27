"""
work_management_service.py — Serviço fino do Hermes para a vertical
Work Management (Track P1 — Ideias, Projetos, Tarefas).

Mesmo espírito de infra_service.py: o Hermes NÃO duplica policy/tenancy/
persistência/Trello aqui — tudo isso vive no Cognitive (work.* capabilities)
e é alcançado via CognitiveApiAdapter (reuso total, zero mudança nele).

    Hermes → WorkManagementService → CognitiveApiAdapter → Cognitive API
    → Policy/Grant → WorkManagementAdapter → WorkService → Supabase
    (+ outbox → TrelloAdapter, assíncrono)

Determinístico, sem LLM aqui. Falha fechada: qualquer erro do Cognitive/
transporte propaga como exceção — as tools (work_management_tools.py)
convertem em `tool_error(...)`, nunca em sucesso fabricado.
"""

from __future__ import annotations

from typing import Any

from .transport.cognitive_api_adapter import CognitiveApiAdapter


class WorkManagementService:
    """Chama qualquer capability `work.*` do Cognitive via CognitiveApiAdapter."""

    def __init__(self, adapter: CognitiveApiAdapter) -> None:
        self._adapter = adapter

    @classmethod
    def from_env(cls) -> "WorkManagementService":
        """Monta a partir de env vars do CognitiveApiAdapter
        (COGNITIVE_GATEWAY_URL / CREDENTIAL / TENANT_ID / ACTOR_ID)."""
        return cls(CognitiveApiAdapter())

    async def call(self, capability_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """Executa uma capability work.* e retorna `data` em caso de sucesso.

        Levanta RuntimeError (via CognitiveApiAdapter) em DENY/CONFIRM/erro de
        transporte/validação — nunca retorna sucesso vazio/fabricado.
        """
        from .models import ExecutionRequest

        ref = await self._adapter.execute(
            ExecutionRequest(capability_id=capability_id, params=params)
        )
        result = await self._adapter.get_result(ref)
        if not result.success:
            raise RuntimeError(result.error or f"Execução de '{capability_id}' falhou")
        return result.data or {}
