"""
infra_service.py — Serviço fino do Hermes para a vertical Infra/Servidores.

Ponto único do Hermes que responde "Como estão meus servidores?" delegando
TUDO ao Cognitive (ADR-V2-005, 27-HERMES-INTEGRATION.md):

    Hermes → CognitiveApiAdapter → Cognitive API → Policy/Resource Resolver
    → ProsperfySkill Adapter → MCP → VPS → resultado → Hermes

O Hermes NÃO duplica aqui:
- policy / tenant authorization / resource resolution / MCP / VPS logic
  (tudo isso vive no Cognitive e é alcançado via a capability `infra.inspect`).

Este serviço só:
  1. monta o client (CognitiveApiAdapter) a partir de env vars;
  2. executa `infra.inspect` com o resource lógico;
  3. consolida o resultado com `build_server_status_view` (raw→normalized→summary).

Determinístico, sem LLM. Falha fechada: qualquer erro do Cognitive/transporte
propaga como exceção — nunca há fallback silencioso para o caminho legado MCP
direto (o que garantiria LEGACY_INFRA_PATH_USED=NO).
"""

from __future__ import annotations

from typing import Any

from .server_views import build_server_status_view
from .transport.cognitive_api_adapter import CognitiveApiAdapter

DEFAULT_CAPABILITY = "infra.inspect"
DEFAULT_RESOURCE = "prosperfy-main"


class InfraService:
    """Responde o status consolidado dos servidores via Cognitive."""

    def __init__(self, adapter: CognitiveApiAdapter) -> None:
        self._adapter = adapter

    @classmethod
    def from_env(cls) -> "InfraService":
        """Monta a partir de env vars do CognitiveApiAdapter
        (COGNITIVE_GATEWAY_URL / CREDENTIAL / TENANT_ID / ACTOR_ID)."""
        return cls(CognitiveApiAdapter())

    async def servers_status(
        self,
        resource: str = DEFAULT_RESOURCE,
        capability: str = DEFAULT_CAPABILITY,
    ) -> dict[str, Any]:
        """Executa `infra.inspect` via Cognitive e consolida em uma visão.

        Retorna a saída de `build_server_status_view`:
        {capability_id, raw, normalized, summary}.

        Falha fechada: se a execução falhar no Cognitive (DENY, 401, erro de
        transporte, status failed), levanta exceção — não há fallback para
        caminho legado.
        """
        ref = await self._adapter.execute(
            # ExecutionRequest é tipado em models; usamos o atributo direto
            # para manter o serviço fino e sem acoplar ao Pipeline legado.
            self._execution_request(capability, resource),
        )
        result = await self._adapter.get_result(ref)
        if not result.success:
            raise RuntimeError(result.error or "Execução de infra.inspect falhou")
        return build_server_status_view(result.data or {})

    @staticmethod
    def _execution_request(capability: str, resource: str):
        from .models import ExecutionRequest

        return ExecutionRequest(
            capability_id=capability,
            params={"resource": resource},
        )