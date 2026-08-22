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

import asyncio
import os
from typing import Any

from .server_views import (
    CONTAINERS,
    PANORAMA,
    build_server_status_view,
    build_servidores_view,
)
from .transport.cognitive_api_adapter import CognitiveApiAdapter

DEFAULT_CAPABILITY = "infra.inspect"
# Resource lógico do slice. Em DEV/in-memory o gateway registra "prosperfy-main"
# automaticamente (gateway/app.py). Em Homolog o resource é provisionado pelo
# bootstrap (ex.: "homolog-synthetic-vps" — Sprint 0.3) — por isso o selector
# é configurável via env COGNITIVE_RESOURCE_KEY, nunca hardcoded. O Hermes NÃO
# resolve resource (isso é do Cognitive) — apenas escolhe QUAL recurso lógico
# pedir. Default preserva o DEV; Homolog aponta o resource provisionado.
_ENV_RESOURCE_KEY = "COGNITIVE_RESOURCE_KEY"
_DEV_DEFAULT_RESOURCE = "prosperfy-main"


def _resolve_default_resource() -> str:
    return os.getenv(_ENV_RESOURCE_KEY, _DEV_DEFAULT_RESOURCE)


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
        resource: str | None = None,
        capability: str = DEFAULT_CAPABILITY,
    ) -> dict[str, Any]:
        """Executa `infra.inspect` via Cognitive e consolida em uma visão.

        Retorna a saída de `build_server_status_view`:
        {capability_id, raw, normalized, summary}.

        `resource` opcional: se omitido, usa `COGNITIVE_RESOURCE_KEY` (env) ou
        o default de DEV "prosperfy-main". O selector é só o resource lógico
        pedido ao Cognitive — a resolução dele (→ host) acontece no Cognitive.

        Falha fechada: se a execução falhar no Cognitive (DENY, 401, erro de
        transporte, resource não resolvido, status failed) OU retornar sucesso
        sem os dados das tools obrigatórias (empty-success), levanta exceção —
        nunca reporta success vazio; não há fallback para caminho legado.
        """
        selector = resource or _resolve_default_resource()
        ref = await self._adapter.execute(
            self._execution_request(capability, selector),
        )
        result = await self._adapter.get_result(ref)
        if not result.success:
            raise RuntimeError(result.error or "Execução de infra.inspect falhou")

        data = result.data or {}
        if not self._has_required_tools(data):
            raise RuntimeError(
                "infra.inspect retornou success sem as tools obrigatórias "
                f"({PANORAMA}, {CONTAINERS}) — fail-closed: nenhum resultado "
                "válido para reportar como sucesso"
            )
        view = build_server_status_view(data, capability_id=capability)
        view["resource_key"] = selector
        return view

    async def servidores_status(self) -> dict[str, Any]:
        """Consolida 'Como estão meus servidores?' — TODOS os resources VPS
        autorizados do tenant (Sprint 0.6 FASE 4).

        Hermes NÃO possui lista de servidores: descobre via Cognitive
        (GET /v1/resources?capability=infra.inspect — resources elegíveis
        para a identidade) e executa infra.inspect POR resource. Cada
        execução passa novamente pela autorização normal do Cognitive
        (LIST/DISCOVERY autorizado + EXECUTION authorization por resource).

        Determinístico, sem LLM. Partial failure: erro de UM resource não
        produz falso OK e não impede mostrar os demais resultados válidos
        (fail-closed por resource, consolidação com seção de ERRO).
        """
        resource_meta = await self._adapter.list_resources()
        if not resource_meta:
            return build_servidores_view([], [])
        resource_keys = [r["resource_key"] for r in resource_meta]
        display_by_key = {r["resource_key"]: r.get("display_name") or r["resource_key"] for r in resource_meta}
        views: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []

        async def _inspect(resource_key: str) -> tuple[str, dict[str, Any] | None]:
            try:
                view = await self.servers_status(resource=resource_key)
                view["display_name"] = display_by_key.get(resource_key, resource_key)
                return "ok", view
            except Exception as exc:  # noqa: BLE001 — fail-closed por resource
                return "err", {
                    "resource_key": resource_key,
                    "display_name": display_by_key.get(resource_key, resource_key),
                    "error": str(exc)[:300],
                }

        # Paralelo (Sprint 0.7.6.2 perf): execução SERIAL de 4 resources era a
        # soma das latências (≈40s); cada infra.inspect faz 3 MCP calls. Gather
        # reduz o total para ~max(resource) (≈10s) sem alterar semantics nem o
        # número de MCP calls (12). Fail-closed por resource é preservado.
        results = await asyncio.gather(*[_inspect(k) for k in resource_keys])
        for outcome, payload in results:
            if outcome == "ok":
                views.append(payload)
            else:
                failures.append(payload)
        return build_servidores_view(views, failures)

    @staticmethod
    def _has_required_tools(data: dict[str, Any]) -> bool:
        """Contrato de infra.inspect: panorama e containers são obrigatórias
        (required: true no YAML); portas é opcional (required: false). Sem as
        obrigatórias, não há resultado válido — empty-success é rejeitado."""
        return PANORAMA in data and CONTAINERS in data

    @staticmethod
    def _execution_request(capability: str, resource: str):
        from .models import ExecutionRequest

        return ExecutionRequest(
            capability_id=capability,
            params={"resource": resource},
        )