"""
db/repositories/identity_repo.py — ServiceIdentityRepository.

Substitui credenciais estáticas in-memory (Sprint 0.1).
credential_hash = sha256(Bearer token) — nunca o valor (ADR-V2-006).

Lookup usa admin_connection: precisamos encontrar o tenant ANTES
de setar o contexto RLS — o que é correto e intencional.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass

from ..connection import admin_connection

logger = logging.getLogger(__name__)


@dataclass
class ServiceIdentityRow:
    id: str
    tenant_id: str
    actor_id: str
    credential_hash: str
    profile: str
    active: bool


def hash_credential(credential: str) -> str:
    """sha256 hex do Bearer token. Nunca armazenar o valor original."""
    return hashlib.sha256(credential.encode()).hexdigest()


class ServiceIdentityRepository:
    """
    Repositório de identidades de serviço.

    O lookup é feito como cognitive_admin porque precisamos encontrar
    tenant_id a partir do credential_hash ANTES de ter o contexto RLS.
    Isso é explicitamente permitido e documentado (ADR-V2-002 §4).
    """

    async def lookup(self, credential: str) -> ServiceIdentityRow | None:
        """
        Resolve credential (Bearer token) → ServiceIdentityRow.

        Usa hash para comparação — nunca armazena ou loga o valor original.
        """
        cred_hash = hash_credential(credential)

        async with admin_connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, tenant_id, actor_id, credential_hash, profile, active
                FROM service_identities
                WHERE credential_hash = $1 AND active = true
                """,
                cred_hash,
            )

            if row:
                # Atualizar last_used_at sem bloqueio
                await conn.execute(
                    "UPDATE service_identities SET last_used_at = NOW() WHERE id = $1",
                    row["id"],
                )

        if not row:
            return None

        return ServiceIdentityRow(
            id=str(row["id"]),
            tenant_id=str(row["tenant_id"]),
            actor_id=row["actor_id"],
            credential_hash=row["credential_hash"],
            profile=row["profile"],
            active=row["active"],
        )

    async def register(
        self,
        tenant_id: str,
        actor_id: str,
        credential: str,
        profile: str = "owner-core",
    ) -> ServiceIdentityRow:
        """
        Registra uma nova service identity (credential → tenant + actor).
        Armazena apenas o hash — nunca o valor em claro.
        """
        cred_hash = hash_credential(credential)

        async with admin_connection() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO service_identities(tenant_id, actor_id, credential_hash, profile)
                VALUES($1, $2, $3, $4)
                ON CONFLICT (credential_hash)
                DO UPDATE SET actor_id = EXCLUDED.actor_id,
                              profile = EXCLUDED.profile,
                              active = true
                RETURNING id, tenant_id, actor_id, credential_hash, profile, active
                """,
                uuid.UUID(tenant_id), actor_id, cred_hash, profile,
            )

        return ServiceIdentityRow(
            id=str(row["id"]),
            tenant_id=str(row["tenant_id"]),
            actor_id=row["actor_id"],
            credential_hash=row["credential_hash"],
            profile=row["profile"],
            active=row["active"],
        )

    async def deactivate(self, credential: str) -> None:
        """Desativa uma credential (revogação)."""
        cred_hash = hash_credential(credential)
        async with admin_connection() as conn:
            await conn.execute(
                "UPDATE service_identities SET active = false WHERE credential_hash = $1",
                cred_hash,
            )
