"""
registry/grant_resolver.py — Resolução de grants por runtime (in-memory/Postgres).

FIX Sprint 0.3 RETURN_TO_DEV (Item A): em COGNITIVE_MODE=database a resolução de
grant nunca consultava a fonte persistida. O Gateway só chamava
register_grant() no branch in_memory de gateway/app.py, e GrantRepository
(capability_grants com RLS, migration 000) jamais era instanciado — resultado:
todo tenant em database mode recebia DENY [no_grant] mesmo com o grant correto
existindo no Postgres.

Design:
  - Porta GrantResolverPort: resolução ASSÍNCRONA de grant (o orquestrador é
    async; GrantRepository é async).
  - RegistryGrantResolver: delega ao InMemoryCapabilityRegistry.resolve_grant
    (semântica Sprint 0.1 — mantém toda a retrocompat de testes/in-memory).
  - PostgresGrantResolver: delega a GrantRepository. O banco aplica RLS via
    tenant_transaction (SET LOCAL app.current_tenant_id), então um grant de
    outro tenant simplesmente não retorna linha. Qualquer falha de
    DB/transação vira None → DENY (fail-closed), com log sanitizado — nunca
    fail-open.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from ..contracts.tenancy import CapabilityGrant
from ..gate.redaction import sanitize_exception
from ..db.repositories.tenancy_repo import GrantRepository

logger = logging.getLogger(__name__)


@runtime_checkable
class GrantResolverPort(Protocol):
    """Resolve grants de capability para um (tenant, profile, capability)."""

    async def resolve_grant(
        self,
        tenant_id: str,
        profile: str,
        capability_id: str,
    ) -> CapabilityGrant | None: ...

    async def list_for_tenant_profile(
        self,
        tenant_id: str,
        profile: str,
    ) -> list[CapabilityGrant]: ...


class RegistryGrantResolver:
    """
    Resolvedor in-memory: delegado ao InMemoryCapabilityRegistry.

    Usado quando nenhum grant_resolver é injetado no orquestrador (padrão
    Sprint 0.1/in-memory) — mesma semântica de resolve_grant() do registry.
    """

    def __init__(self, registry: object) -> None:
        self._registry = registry

    async def resolve_grant(
        self,
        tenant_id: str,
        profile: str,
        capability_id: str,
    ) -> CapabilityGrant | None:
        return self._registry.resolve_grant(tenant_id, profile, capability_id)

    async def list_for_tenant_profile(
        self,
        tenant_id: str,
        profile: str,
    ) -> list[CapabilityGrant]:
        grants: list[CapabilityGrant] = []
        for capability in self._registry.list_all():
            grant = self._registry.resolve_grant(tenant_id, profile, capability.id)
            if grant is not None:
                grants.append(grant)
        return grants


class PostgresGrantResolver:
    """
    Resolvedor em database mode: delega a GrantRepository (capability_grants
    com RLS). Fail-closed: erro de DB/transação → None (DENY), nunca um grant
    fabricado nem exceção vazando o secret.
    """

    def __init__(self, repo: GrantRepository | None = None) -> None:
        self._repo = repo or GrantRepository()

    async def resolve_grant(
        self,
        tenant_id: str,
        profile: str,
        capability_id: str,
    ) -> CapabilityGrant | None:
        try:
            return await self._repo.get_grant(tenant_id, profile, capability_id)
        except Exception as exc:
            logger.error(
                "Grant resolution failed — fail-closed DENY "
                "tenant=%s profile=%s cap=%s error=%s",
                tenant_id, profile, capability_id, sanitize_exception(exc),
            )
            return None

    async def list_for_tenant_profile(
        self,
        tenant_id: str,
        profile: str,
    ) -> list[CapabilityGrant]:
        try:
            return await self._repo.list_for_tenant_profile(tenant_id, profile)
        except Exception as exc:
            logger.error(
                "Grant listing failed — fail-closed empty "
                "tenant=%s profile=%s error=%s",
                tenant_id, profile, sanitize_exception(exc),
            )
            return []