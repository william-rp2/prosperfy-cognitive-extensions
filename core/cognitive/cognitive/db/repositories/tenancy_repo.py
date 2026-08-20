"""
db/repositories/tenancy_repo.py — Repositórios de Tenant, Member e Grant.

Todos os métodos que não são admin usam tenant_transaction (RLS enforced).
Métodos admin (seed, lookup cross-tenant) usam admin_connection (BYPASSRLS).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

import asyncpg

from ..connection import admin_connection, tenant_transaction
from ...contracts.tenancy import CapabilityGrant

logger = logging.getLogger(__name__)


@dataclass
class TenantRow:
    id: str
    slug: str
    name: str
    active: bool


@dataclass
class MemberRow:
    id: str
    tenant_id: str
    principal_id: str
    principal_type: str
    profile: str
    active: bool


class TenantRepository:
    """Operações CRUD para Tenants — usa cognitive_admin (BYPASSRLS)."""

    async def get_by_slug(self, slug: str) -> TenantRow | None:
        async with admin_connection() as conn:
            row = await conn.fetchrow(
                "SELECT id, slug, name, active FROM tenants WHERE slug = $1 AND active = true",
                slug,
            )
        if not row:
            return None
        return TenantRow(**dict(row))

    async def get_by_id(self, tenant_id: str) -> TenantRow | None:
        async with admin_connection() as conn:
            row = await conn.fetchrow(
                "SELECT id, slug, name, active FROM tenants WHERE id = $1",
                uuid.UUID(tenant_id),
            )
        if not row:
            return None
        return TenantRow(
            id=str(row["id"]),
            slug=row["slug"],
            name=row["name"],
            active=row["active"],
        )

    async def create(self, slug: str, name: str) -> TenantRow:
        async with admin_connection() as conn:
            row = await conn.fetchrow(
                "INSERT INTO tenants(slug, name) VALUES($1, $2) "
                "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name "
                "RETURNING id, slug, name, active",
                slug, name,
            )
        return TenantRow(id=str(row["id"]), slug=row["slug"], name=row["name"], active=row["active"])


class MemberRepository:
    """Vínculos principal ↔ tenant."""

    async def upsert(
        self,
        tenant_id: str,
        principal_id: str,
        principal_type: str,
        profile: str,
    ) -> MemberRow:
        async with admin_connection() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO tenant_members(tenant_id, principal_id, principal_type, profile)
                VALUES($1, $2, $3, $4)
                ON CONFLICT (tenant_id, principal_id)
                DO UPDATE SET profile = EXCLUDED.profile, active = true
                RETURNING id, tenant_id, principal_id, principal_type, profile, active
                """,
                uuid.UUID(tenant_id), principal_id, principal_type, profile,
            )
        return MemberRow(
            id=str(row["id"]),
            tenant_id=str(row["tenant_id"]),
            principal_id=row["principal_id"],
            principal_type=row["principal_type"],
            profile=row["profile"],
            active=row["active"],
        )

    async def get_profile(self, tenant_id: str, principal_id: str) -> str | None:
        async with admin_connection() as conn:
            row = await conn.fetchrow(
                "SELECT profile FROM tenant_members "
                "WHERE tenant_id = $1 AND principal_id = $2 AND active = true",
                uuid.UUID(tenant_id), principal_id,
            )
        return row["profile"] if row else None


class GrantRepository:
    """Capability Grants — RLS enforced via tenant_transaction."""

    async def get_grant(
        self,
        tenant_id: str,
        profile: str,
        capability_id: str,
    ) -> CapabilityGrant | None:
        """Resolve grant. RLS é o controle primário de cross-tenant isolation;
        a cláusula tenant_id = $3 é belt-and-braces (defense-in-depth) caso a
        policy RLS falte/desabilite num deploy — rejeição via DB, não só na
        Policy."""
        async with tenant_transaction(tenant_id) as conn:
            row = await conn.fetchrow(
                """
                SELECT tenant_id, profile, capability_id, policy_override
                FROM capability_grants
                WHERE tenant_id = $3
                  AND profile = $1
                  AND capability_id = $2
                  AND active = true
                """,
                profile, capability_id, uuid.UUID(tenant_id),
            )
        if not row:
            return None
        return CapabilityGrant(
            tenant_id=str(row["tenant_id"]),
            profile=row["profile"],
            capability_id=row["capability_id"],
            policy_override=row["policy_override"],
        )

    async def upsert(
        self,
        tenant_id: str,
        profile: str,
        capability_id: str,
        policy_override: str | None = None,
    ) -> None:
        async with admin_connection() as conn:
            await conn.execute(
                """
                INSERT INTO capability_grants(tenant_id, profile, capability_id, policy_override)
                VALUES($1, $2, $3, $4)
                ON CONFLICT (tenant_id, profile, capability_id)
                DO UPDATE SET policy_override = EXCLUDED.policy_override, active = true
                """,
                uuid.UUID(tenant_id), profile, capability_id, policy_override,
            )

    async def list_for_tenant_profile(
        self, tenant_id: str, profile: str
    ) -> list[CapabilityGrant]:
        async with tenant_transaction(tenant_id) as conn:
            rows = await conn.fetch(
                "SELECT tenant_id, profile, capability_id, policy_override "
                "FROM capability_grants WHERE profile = $1 AND active = true",
                profile,
            )
        return [
            CapabilityGrant(
                tenant_id=str(r["tenant_id"]),
                profile=r["profile"],
                capability_id=r["capability_id"],
                policy_override=r["policy_override"],
            )
            for r in rows
        ]
