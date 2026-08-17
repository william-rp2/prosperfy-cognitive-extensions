"""
db/repositories/resource_repo.py — Repositórios de Tenant Resources e Credential Refs.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from ..connection import admin_connection, tenant_transaction
from ..jsonb_codec import deserialize_jsonb_object, serialize_jsonb

logger = logging.getLogger(__name__)


@dataclass
class TenantResourceRow:
    id: str
    tenant_id: str
    resource_key: str
    resource_type: str
    resolved_params: dict[str, Any]
    active: bool


@dataclass
class CredentialRefRow:
    id: str
    tenant_id: str
    provider: str
    secret_ref: str


def _row_to_tenant_resource(row) -> TenantResourceRow:
    return TenantResourceRow(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        resource_key=row["resource_key"],
        resource_type=row["resource_type"],
        resolved_params=deserialize_jsonb_object(row["resolved_params"]),
        active=row["active"],
    )


class TenantResourceRepository:
    """Resolve resource_key → parâmetros concretos via banco (RLS enforced)."""

    async def resolve(
        self,
        tenant_id: str,
        resource_key: str,
    ) -> TenantResourceRow | None:
        async with tenant_transaction(tenant_id) as conn:
            row = await conn.fetchrow(
                """
                SELECT id, tenant_id, resource_key, resource_type, resolved_params, active
                FROM tenant_resources
                WHERE resource_key = $1 AND active = true
                """,
                resource_key,
            )
        if not row:
            return None
        return _row_to_tenant_resource(row)

    async def upsert(
        self,
        tenant_id: str,
        resource_key: str,
        resource_type: str,
        resolved_params: dict[str, Any],
    ) -> TenantResourceRow:
        async with admin_connection() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO tenant_resources(tenant_id, resource_key, resource_type, resolved_params)
                VALUES($1, $2, $3, $4::jsonb)
                ON CONFLICT (tenant_id, resource_key)
                DO UPDATE SET resource_type = EXCLUDED.resource_type,
                              resolved_params = EXCLUDED.resolved_params,
                              active = true
                RETURNING id, tenant_id, resource_key, resource_type, resolved_params, active
                """,
                uuid.UUID(tenant_id),
                resource_key,
                resource_type,
                serialize_jsonb(resolved_params),
            )
        return _row_to_tenant_resource(row)


class CredentialRefRepository:
    """Acesso a credential_refs — retorna apenas secret_ref, nunca o valor."""

    async def get_by_provider(
        self, tenant_id: str, provider: str
    ) -> CredentialRefRow | None:
        async with tenant_transaction(tenant_id) as conn:
            row = await conn.fetchrow(
                "SELECT id, tenant_id, provider, secret_ref FROM credential_refs "
                "WHERE provider = $1",
                provider,
            )
        if not row:
            return None
        return CredentialRefRow(
            id=str(row["id"]),
            tenant_id=str(row["tenant_id"]),
            provider=row["provider"],
            secret_ref=row["secret_ref"],
        )

    async def upsert(
        self,
        tenant_id: str,
        provider: str,
        secret_ref: str,
    ) -> str:
        async with admin_connection() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO credential_refs(tenant_id, provider, secret_ref)
                VALUES($1, $2, $3)
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                uuid.UUID(tenant_id), provider, secret_ref,
            )
        return str(row["id"]) if row else ""
