"""
db/repositories/identity_repo.py — ServiceIdentityRepository.

Substitui credenciais estáticas in-memory (Sprint 0.1).
credential_hash = sha256(Bearer token) — nunca o valor (ADR-V2-006).

SEC-001 (Sprint 0.3): lookup() precisa encontrar o tenant ANTES de existir
contexto RLS — mas isso não exige cognitive_admin/BYPASSRLS.

SEC-002 (revisão de segurança do Gate): a primeira correção do SEC-001
liberou SELECT irrestrito em service_identities para cognitive_app/
cognitive_worker, assumindo que o filtro por credential_hash no SQL da
aplicação bastava como boundary — não basta, é só application-layer, não
enforcement de banco. Corrigido: cognitive_app/cognitive_worker perdem
QUALQUER grant direto na tabela (migration 002). O único acesso é via
`resolve_service_identity_by_credential_hash(credential_hash)`, uma
função SECURITY DEFINER que recebe só o hash, faz o match exato
internamente, atualiza last_used_at atomicamente na mesma operação (sem
função "touch" separada aceitando id arbitrário) e retorna só os 4
campos necessários pro ActorContext — nunca credential_hash, nunca outras
linhas. lookup() roda essa função no pool normal da app
(app_connection_no_tenant), sem precisar do pool admin.

register()/deactivate() continuam em admin_connection(): não são
chamados por nenhuma rota HTTP do Gateway (grep confirma) — são apenas
bootstrap/CLI de provisionamento de credenciais, executados fora do
processo web público.
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


@dataclass
class ResolvedServiceIdentity:
    """
    Retorno de resolve_service_identity_by_credential_hash — só os campos
    necessários pra montar ActorContext. NUNCA inclui credential_hash
    (SEC-002). `active` é sempre True: a função SQL só retorna linhas com
    active = true; o campo existe só por compatibilidade duck-typed com
    IdentityResolver._build_context_from_db (que checa `.active`).
    """
    id: str
    tenant_id: str
    actor_id: str
    profile: str
    active: bool = True


def hash_credential(credential: str) -> str:
    """sha256 hex do Bearer token. Nunca armazenar o valor original."""
    return hashlib.sha256(credential.encode()).hexdigest()


class ServiceIdentityRepository:
    """
    Repositório de identidades de serviço.

    lookup() usa o pool normal da app (least privilege): precisamos
    encontrar tenant_id a partir do credential_hash ANTES de ter o
    contexto RLS, mas isso não exige BYPASSRLS nem SELECT direto na
    tabela. cognitive_app/cognitive_worker não têm nenhum grant em
    service_identities (migration 002, SEC-002) — o único acesso é via
    `resolve_service_identity_by_credential_hash`, uma função SECURITY
    DEFINER que recebe só o hash e nunca devolve credential_hash. Ver
    docstring do módulo para o raciocínio completo.
    """

    async def lookup(self, credential: str) -> ResolvedServiceIdentity | None:
        """
        Resolve credential (Bearer token) → ResolvedServiceIdentity.

        Usa hash para comparação — nunca armazena ou loga o valor original.
        Roda no pool cognitive_app, sem tenant context (SEC-001), chamando
        a função SECURITY DEFINER (SEC-002) que também atualiza
        last_used_at atomicamente na mesma operação, só na linha que bateu.
        """
        cred_hash = hash_credential(credential)

        async with app_connection_no_tenant() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM resolve_service_identity_by_credential_hash($1)",
                cred_hash,
            )

        if not row:
            return None

        return ResolvedServiceIdentity(
            id=str(row["service_identity_id"]),
            tenant_id=str(row["tenant_id"]),
            actor_id=row["actor_id"],
            profile=row["profile"],
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
