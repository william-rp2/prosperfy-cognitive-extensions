"""
execution/resource_resolver.py — Resolver de Resource Lógico → Parâmetros Concretos.

ADR-V2-002 §3: o cliente passa resource_key lógico (ex: "prosperfy-main").
O Cognitive resolve para host/port/project_ref via tenant_resources no banco.

Bloqueio: se resource_key não existir ou não pertencer ao tenant → erro (não bypass).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ResourceResolver:
    """
    Resolve resource_key lógico → parâmetros concretos para o adapter.

    Injeta parâmetros resolvidos nos params da execução antes de chamar o adapter.
    RLS garante: um tenant não pode resolver resources de outro tenant.
    """

    def __init__(self, resource_repo) -> None:
        self._repo = resource_repo  # TenantResourceRepository

    async def resolve(
        self,
        tenant_id: str,
        resource_key: str,
    ) -> dict[str, Any]:
        """
        Resolve resource_key → resolved_params.

        Levanta ValueError se resource_key não existir para o tenant.
        O adapter receberá os parâmetros concretos — nunca o resource_key diretamente.
        """
        resource = await self._repo.resolve(tenant_id, resource_key)

        if resource is None:
            raise ValueError(
                f"Resource '{resource_key}' não encontrado para tenant '{tenant_id}'. "
                "Cadastrar em tenant_resources antes de usar."
            )

        logger.debug(
            "ResourceResolver: tenant=%s resource_key=%s → type=%s",
            tenant_id, resource_key, resource.resource_type,
        )

        return resource.resolved_params

    async def inject_resource_params(
        self,
        tenant_id: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Verifica se params contém 'resource' e injeta os parâmetros resolvidos.

        Se 'resource' não estiver em params, retorna params sem modificação
        (capabilities sem resource lógico).
        """
        resource_key = params.get("resource")
        if not resource_key:
            return params

        resolved = await self.resolve(tenant_id, resource_key)
        enriched = dict(params)
        enriched["_resolved_resource"] = resolved
        # Manter resource_key para audit/telemetry mas não expor ao adapter
        return enriched


class InMemoryResourceResolver:
    """
    Resolver in-memory para Sprint 0.1 retrocompatibilidade e testes sem DB.

    Recursos registrados estaticamente para dev/CI.
    """

    def __init__(self) -> None:
        self._resources: dict[tuple[str, str], dict[str, Any]] = {}

    def register(self, tenant_id: str, resource_key: str, resolved_params: dict[str, Any]) -> None:
        self._resources[(tenant_id, resource_key)] = resolved_params

    async def resolve(self, tenant_id: str, resource_key: str) -> dict[str, Any]:
        key = (tenant_id, resource_key)
        if key not in self._resources:
            raise ValueError(
                f"Resource '{resource_key}' não cadastrado para tenant '{tenant_id}' (in-memory)"
            )
        return self._resources[key]

    async def inject_resource_params(
        self, tenant_id: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        resource_key = params.get("resource")
        if not resource_key:
            return params
        resolved = await self.resolve(tenant_id, resource_key)
        enriched = dict(params)
        enriched["_resolved_resource"] = resolved
        return enriched
