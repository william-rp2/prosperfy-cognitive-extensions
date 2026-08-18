"""
db/repositories/identity_repo.py — ServiceIdentityRepository.

Substitui credenciais estáticas in-memory (Sprint 0.1).
credential_hash = sha256(Bearer token) — nunca o valor (ADR-V2-006).

SEC-001 (Sprint 0.3): lookup() precisa encontrar o tenant ANTES de existir
contexto RLS — mas isso não exige mais cognitive_admin/BYPASSRLS. A tabela
service_identities é estruturalmente uma tabela de login/auth: o
credential_hash exato É o boundary de autorização (só quem tem o Bearer
token original calcula o hash igual), não o tenant_id. A migration 002
troca a policy tenant-scoped em service_identities por SELECT irrestrito
para cognitive_app/cognitive_worker, então lookup() usa o pool normal da
app (app_connection_no_tenant), sem precisar do pool admin.

O touch de last_used_at (também antes do tenant context existir) usa a
função SECURITY DEFINER touch_service_identity_last_used — atualiza
apenas essa coluna, apenas por id, sem exigir UPDATE irrestrito nem admin.

register()/deactivate() continuam em admin_connection(): não são
chamados por nenhuma rota HTTP do Gateway (grep confirma) — são apenas
bootstrap/CLI de provisionamento de credenciais, executados fora do
processo web público. Não fazem parte do problema do SEC-001.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass

from ..connection import admin_connection, app_connection_no_tenant

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

    O lookup usa o pool normal da app (least privilege): precisamos
    encontrar tenant_id a partir do credential_hash ANTES de ter o
    contexto RLS, mas isso não exige BYPASSRLS — a migration 002 dá a
    cognitive_app/cognitive_worker SELECT irrestrito em service_identities
    (o credential_hash é o boundary real, não o tenant_id). Ver docstring
    do módulo para o raciocínio completo.
    """

    async def lookup(self, credential: str) -> ServiceIdentityRow | None:
        """
        Resolve credential (Bearer token) → ServiceIdentityRow.

        Usa hash para comparação — nunca armazena ou loga o valor original.
        Roda no pool cognitive_app, sem tenant context (SEC-001).
        """
        cred_hash = hash_credential(credential)

        async with app_connection_no_tenant() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, tenant_id, actor_id, credential_hash, profile, active
                FROM service_identities
                WHERE credential_hash = $1 AND active = true
                """,
                cred_hash,
            )

            if row:
                # Atualizar last_used_at via função SECURITY DEFINER
                # (id-scoped, single-column) — não precisa de admin nem de
                # tenant context.
                await conn.execute(
                    "SELECT touch_service_identity_last_used($1)",
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

        Bootstrap/CLI apenas — nenhuma rota HTTP do Gateway chama isto em
        runtime, então continuar em admin_connection() não reintroduz
        SEC-001 (pool admin não precisa ficar vivo no processo web).
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
        """
        Desativa uma credential (revogação).

        Bootstrap/CLI apenas — mesma justificativa de register().
        """
        cred_hash = hash_credential(credential)
        async with admin_connection() as conn:
            await conn.execute(
                "UPDATE service_identities SET active = false WHERE credential_hash = $1",
                cred_hash,
            )
