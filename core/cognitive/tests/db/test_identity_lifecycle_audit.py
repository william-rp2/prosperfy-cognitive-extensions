"""tests/db/test_identity_lifecycle_audit.py — identity_events audit trail
(Sprint 0.4, migrations/003_identity_lifecycle_audit.sql).

Prova contra Postgres real (homolog remoto ou testcontainers, mesmo padrão
honest-skip de test_service_identity.py): register()/deactivate()/rotate()
gravam a linha certa em identity_events, RLS restringe leitura por tenant
pra cognitive_app/cognitive_worker, e nenhuma das duas roles consegue
INSERT nesta tabela (grant ausente, não só RLS silenciosamente bloqueando).
"""

from __future__ import annotations

import uuid

import pytest

from cognitive.db.repositories.identity_repo import ServiceIdentityRepository, hash_credential

from .conftest import db_integration_available, set_tenant_local, skip_reason

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not db_integration_available(), reason=skip_reason()),
]


async def _events_for_identity(admin_conn, service_identity_id: str) -> list:
    return await admin_conn.fetch(
        "SELECT * FROM identity_events WHERE service_identity_id = $1 ORDER BY created_at",
        uuid.UUID(service_identity_id),
    )


class TestRegisterWritesRegisteredEvent:
    async def test_register_writes_one_registered_event(self, db_pools, seeded_tenants, admin_conn):
        tenant_a_id = seeded_tenants["tenant-a"]
        credential = "audit-register-credential"
        repo = ServiceIdentityRepository()
        try:
            identity = await repo.register(tenant_a_id, "actor-audit", credential)

            events = await _events_for_identity(admin_conn, identity.id)
            assert len(events) == 1
            assert events[0]["event_type"] == "registered"
            assert str(events[0]["tenant_id"]) == tenant_a_id
            assert events[0]["actor_id"] == "actor-audit"
            assert events[0]["profile"] == "owner-core"
        finally:
            await repo.deactivate(credential)
            await admin_conn.execute(
                "DELETE FROM identity_events WHERE service_identity_id = "
                "(SELECT id FROM service_identities WHERE credential_hash = $1)",
                hash_credential(credential),
            )
            await admin_conn.execute(
                "DELETE FROM service_identities WHERE credential_hash = $1",
                hash_credential(credential),
            )


class TestDeactivateWritesDeactivatedEvent:
    async def test_deactivate_adds_one_more_event(self, db_pools, seeded_tenants, admin_conn):
        tenant_a_id = seeded_tenants["tenant-a"]
        credential = "audit-deactivate-credential"
        repo = ServiceIdentityRepository()
        try:
            identity = await repo.register(tenant_a_id, "actor-audit-2", credential)
            await repo.deactivate(credential)

            events = await _events_for_identity(admin_conn, identity.id)
            assert len(events) == 2
            assert [e["event_type"] for e in events] == ["registered", "deactivated"]
        finally:
            await admin_conn.execute(
                "DELETE FROM identity_events WHERE service_identity_id = "
                "(SELECT id FROM service_identities WHERE credential_hash = $1)",
                hash_credential(credential),
            )
            await admin_conn.execute(
                "DELETE FROM service_identities WHERE credential_hash = $1",
                hash_credential(credential),
            )


class TestRotateEndToEnd:
    async def test_rotate_old_lookup_fails_new_lookup_succeeds_two_events(
        self, db_pools, seeded_tenants, admin_conn
    ):
        tenant_a_id = seeded_tenants["tenant-a"]
        old_credential = "audit-rotate-old-credential"
        new_credential = "audit-rotate-new-credential"
        repo = ServiceIdentityRepository()
        old_identity = await repo.register(tenant_a_id, "actor-rotate", old_credential)
        try:
            new_identity = await repo.rotate(old_credential, new_credential)

            # old credential no longer resolves, new one does.
            assert await repo.lookup(old_credential) is None
            resolved_new = await repo.lookup(new_credential)
            assert resolved_new is not None
            assert resolved_new.tenant_id == tenant_a_id

            # different credentials -> different credential_hash -> the
            # register() ON CONFLICT upsert inserts a fresh row, never
            # reuses the old identity's id.
            assert old_identity.id != new_identity.id

            # exactly 2 new identity_events rows total: one 'deactivated'
            # tied to the old identity, one 'registered' tied to the new one.
            old_events = await _events_for_identity(admin_conn, old_identity.id)
            new_events = await _events_for_identity(admin_conn, new_identity.id)

            assert [e["event_type"] for e in old_events] == ["registered", "deactivated"]
            assert [e["event_type"] for e in new_events] == ["registered"]
        finally:
            await admin_conn.execute(
                "DELETE FROM identity_events WHERE service_identity_id IN "
                "(SELECT id FROM service_identities WHERE credential_hash IN ($1, $2))",
                hash_credential(old_credential), hash_credential(new_credential),
            )
            await admin_conn.execute(
                "DELETE FROM service_identities WHERE credential_hash IN ($1, $2)",
                hash_credential(old_credential), hash_credential(new_credential),
            )

    async def test_rotate_raises_for_unknown_credential(self, db_pools, seeded_tenants):
        repo = ServiceIdentityRepository()
        with pytest.raises(ValueError, match="não encontrada ou já inativa"):
            await repo.rotate("definitely-never-registered", "irrelevant-new-credential")


class TestCrossTenantReadIsolation:
    async def test_app_role_sees_only_own_tenant_identity_events(
        self, db_pools, seeded_tenants, admin_conn, app_conn
    ):
        tenant_a_id = seeded_tenants["tenant-a"]
        tenant_b_id = seeded_tenants["tenant-b"]
        cred_a = "audit-crosstenant-a"
        cred_b = "audit-crosstenant-b"
        repo = ServiceIdentityRepository()
        try:
            await repo.register(tenant_a_id, "actor-a", cred_a)
            await repo.register(tenant_b_id, "actor-b", cred_b)

            # set_config(..., is_local=true) só tem efeito dentro de uma
            # transação; fora dela é no-op silencioso (mesmo padrão de
            # test_rls_cross_tenant.py / test_rls_gate.py).
            async with app_conn.transaction():
                await set_tenant_local(app_conn, tenant_a_id)
                rows = await app_conn.fetch("SELECT * FROM identity_events")
            seen_tenants = {str(r["tenant_id"]) for r in rows}
            assert seen_tenants == {tenant_a_id}
            assert tenant_b_id not in seen_tenants
        finally:
            for cred in (cred_a, cred_b):
                await admin_conn.execute(
                    "DELETE FROM identity_events WHERE service_identity_id = "
                    "(SELECT id FROM service_identities WHERE credential_hash = $1)",
                    hash_credential(cred),
                )
            await admin_conn.execute(
                "DELETE FROM service_identities WHERE credential_hash IN ($1, $2)",
                hash_credential(cred_a), hash_credential(cred_b),
            )

    async def test_worker_role_sees_only_own_tenant_identity_events(
        self, db_pools, seeded_tenants, admin_conn, worker_conn
    ):
        tenant_a_id = seeded_tenants["tenant-a"]
        tenant_b_id = seeded_tenants["tenant-b"]
        cred_a = "audit-crosstenant-worker-a"
        cred_b = "audit-crosstenant-worker-b"
        repo = ServiceIdentityRepository()
        try:
            await repo.register(tenant_a_id, "actor-a", cred_a)
            await repo.register(tenant_b_id, "actor-b", cred_b)

            async with worker_conn.transaction():
                await set_tenant_local(worker_conn, tenant_b_id)
                rows = await worker_conn.fetch("SELECT * FROM identity_events")
            seen_tenants = {str(r["tenant_id"]) for r in rows}
            assert seen_tenants == {tenant_b_id}
            assert tenant_a_id not in seen_tenants
        finally:
            for cred in (cred_a, cred_b):
                await admin_conn.execute(
                    "DELETE FROM identity_events WHERE service_identity_id = "
                    "(SELECT id FROM service_identities WHERE credential_hash = $1)",
                    hash_credential(cred),
                )
            await admin_conn.execute(
                "DELETE FROM service_identities WHERE credential_hash IN ($1, $2)",
                hash_credential(cred_a), hash_credential(cred_b),
            )


class TestAppWorkerCannotInsert:
    """Grant ausente é a barreira primária (mesma filosofia de 002/SEC-002)
    — o INSERT deve falhar por privilégio, não só ser silenciosamente
    bloqueado por RLS."""

    async def test_app_role_cannot_insert_identity_events(
        self, db_pools, seeded_tenants, app_conn
    ):
        tenant_a_id = seeded_tenants["tenant-a"]
        await set_tenant_local(app_conn, tenant_a_id)
        with pytest.raises(Exception):
            await app_conn.execute(
                """
                INSERT INTO identity_events(event_type, service_identity_id, tenant_id, actor_id, profile)
                VALUES('registered', gen_random_uuid(), $1, 'probe-actor', 'owner-core')
                """,
                uuid.UUID(tenant_a_id),
            )

    async def test_worker_role_cannot_insert_identity_events(
        self, db_pools, seeded_tenants, worker_conn
    ):
        tenant_a_id = seeded_tenants["tenant-a"]
        await set_tenant_local(worker_conn, tenant_a_id)
        with pytest.raises(Exception):
            await worker_conn.execute(
                """
                INSERT INTO identity_events(event_type, service_identity_id, tenant_id, actor_id, profile)
                VALUES('registered', gen_random_uuid(), $1, 'probe-actor', 'owner-core')
                """,
                uuid.UUID(tenant_a_id),
            )

    async def test_app_role_insert_permission_denied_not_rls(
        self, db_pools, seeded_tenants, app_conn
    ):
        """Confirma no catálogo que o grant de INSERT está ausente pra
        cognitive_app — não confia só em capturar a exceção do INSERT."""
        row = await app_conn.fetchrow(
            "SELECT has_table_privilege('cognitive_app', 'identity_events', 'INSERT') AS can_insert"
        )
        assert row["can_insert"] is False

    async def test_worker_role_insert_permission_denied_not_rls(
        self, db_pools, seeded_tenants, worker_conn
    ):
        row = await worker_conn.fetchrow(
            "SELECT has_table_privilege('cognitive_worker', 'identity_events', 'INSERT') AS can_insert"
        )
        assert row["can_insert"] is False

    async def test_app_and_worker_have_select_privilege(self, db_pools, admin_conn):
        row = await admin_conn.fetchrow(
            "SELECT "
            "has_table_privilege('cognitive_app', 'identity_events', 'SELECT') AS app_can, "
            "has_table_privilege('cognitive_worker', 'identity_events', 'SELECT') AS worker_can"
        )
        assert row["app_can"] is True
        assert row["worker_can"] is True
