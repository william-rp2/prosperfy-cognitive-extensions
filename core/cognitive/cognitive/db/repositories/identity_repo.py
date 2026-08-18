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

Sprint 0.4 (identity_events — trilha de auditoria de lifecycle): register()
e deactivate() gravam, na MESMA transação admin_connection() do
INSERT/UPDATE em service_identities, uma linha em identity_events
('registered'/'deactivated' respectivamente) — nunca dois round trips que
poderiam divergir (ex.: identity registrada mas evento perdido por crash
entre as duas chamadas). rotate(old, new) é a composição das duas: dentro
de UMA transação, desativa old_credential e registra new_credential para o
mesmo tenant_id/actor_id/profile, produzindo naturalmente duas linhas em
identity_events. A lógica compartilhada vive em _do_register()/
_do_deactivate() (recebem a `conn` já aberta, não abrem transação própria)
para que register()/deactivate()/rotate() nunca aninhem transações — só o
método público (register, deactivate ou rotate) abre `conn.transaction()`,
uma vez, por chamada. Ver migrations/003_identity_lifecycle_audit.sql para
o schema e o raciocínio de RLS/grants da tabela.
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

    async def _do_register(
        self,
        conn,
        tenant_id: str,
        actor_id: str,
        credential: str,
        profile: str,
    ) -> ServiceIdentityRow:
        """
        Lógica compartilhada de INSERT (service_identities) + audit trail
        (identity_events, event_type='registered'). Recebe `conn` já aberta
        — NUNCA abre transação própria. Chamada por register() (que abre a
        transação) e por rotate() (que reusa a transação já aberta por
        _do_deactivate na mesma chamada) — nunca pelas duas ao mesmo tempo.
        """
        cred_hash = hash_credential(credential)

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

        await conn.execute(
            """
            INSERT INTO identity_events(event_type, service_identity_id, tenant_id, actor_id, profile)
            VALUES('registered', $1, $2, $3, $4)
            """,
            row["id"], row["tenant_id"], row["actor_id"], row["profile"],
        )

        return ServiceIdentityRow(
            id=str(row["id"]),
            tenant_id=str(row["tenant_id"]),
            actor_id=row["actor_id"],
            credential_hash=row["credential_hash"],
            profile=row["profile"],
            active=row["active"],
        )

    async def _do_deactivate(self, conn, credential: str) -> ServiceIdentityRow | None:
        """
        Lógica compartilhada de UPDATE (service_identities.active=false) +
        audit trail (identity_events, event_type='deactivated'). Recebe
        `conn` já aberta — NUNCA abre transação própria. Retorna None se a
        credential não existe ou já estava inativa (WHERE ... AND active =
        true não bate nenhuma linha) — nesse caso nenhum evento é gravado,
        evitando linhas 'deactivated' duplicadas em chamadas repetidas.
        """
        cred_hash = hash_credential(credential)

        row = await conn.fetchrow(
            """
            UPDATE service_identities
            SET active = false
            WHERE credential_hash = $1 AND active = true
            RETURNING id, tenant_id, actor_id, credential_hash, profile, active
            """,
            cred_hash,
        )
        if row is None:
            return None

        await conn.execute(
            """
            INSERT INTO identity_events(event_type, service_identity_id, tenant_id, actor_id, profile)
            VALUES('deactivated', $1, $2, $3, $4)
            """,
            row["id"], row["tenant_id"], row["actor_id"], row["profile"],
        )

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
        Armazena apenas o hash — nunca o valor em claro. Grava também uma
        linha 'registered' em identity_events, na MESMA transação (Sprint
        0.4) — nunca dois round trips que poderiam divergir.

        Bootstrap/CLI apenas — nenhuma rota HTTP do Gateway chama isto em
        runtime, então continuar em admin_connection() não reintroduz
        SEC-001 (pool admin não precisa ficar vivo no processo web).
        """
        async with admin_connection() as conn:
            async with conn.transaction():
                return await self._do_register(conn, tenant_id, actor_id, credential, profile)

    async def deactivate(self, credential: str) -> None:
        """
        Desativa uma credential (revogação). Grava também uma linha
        'deactivated' em identity_events, na MESMA transação (Sprint 0.4) —
        exceto se a credential já estava inativa/não existia, caso em que
        nada muda e nenhum evento é gravado (comportamento silencioso
        preservado do original: nunca levanta erro aqui — use rotate() se
        precisar de um ValueError explícito em cima de "não encontrada").

        Bootstrap/CLI apenas — mesma justificativa de register().
        """
        async with admin_connection() as conn:
            async with conn.transaction():
                await self._do_deactivate(conn, credential)

    async def rotate(self, old_credential: str, new_credential: str) -> ServiceIdentityRow:
        """
        Rotaciona uma credential: desativa old_credential e registra
        new_credential para o MESMO tenant_id/actor_id/profile, em UMA
        única transação admin_connection(). Produz duas linhas em
        identity_events (uma 'deactivated', uma 'registered') como efeito
        natural de reusar _do_deactivate()/_do_register() — nunca chama os
        métodos públicos register()/deactivate() (isso abriria uma segunda
        transação cada, quebrando a atomicidade).

        Levanta ValueError se old_credential não existe ou já está
        inativa — nunca um no-op silencioso (diferente de deactivate()):
        rotacionar uma credential que não pode ser desativada é um erro do
        chamador, não um estado válido a ignorar.
        """
        async with admin_connection() as conn:
            async with conn.transaction():
                deactivated = await self._do_deactivate(conn, old_credential)
                if deactivated is None:
                    raise ValueError(
                        "rotate(): old_credential não encontrada ou já inativa "
                        "— nada para rotacionar."
                    )
                return await self._do_register(
                    conn,
                    deactivated.tenant_id,
                    deactivated.actor_id,
                    new_credential,
                    deactivated.profile,
                )
