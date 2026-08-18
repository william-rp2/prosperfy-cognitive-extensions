"""tests/db/test_service_identity.py — ServiceIdentityRepository + identity resolver DB."""

from __future__ import annotations

import uuid

import pytest

from cognitive.db.repositories.identity_repo import ServiceIdentityRepository, hash_credential
from cognitive.tenancy.identity_resolver import IdentityResolver
from .conftest import db_integration_available, skip_reason

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not db_integration_available(), reason=skip_reason()),
]


@pytest.fixture
async def seeded_identity(admin_conn, seeded_tenants):
    tenant_a_id = seeded_tenants["tenant-a"]
    credential = "gate-test-credential-abc123"
    cred_hash = hash_credential(credential)
    await admin_conn.execute(
        """
        INSERT INTO service_identities(tenant_id, actor_id, credential_hash, profile)
        VALUES($1, 'actor-test', $2, 'owner-core')
        ON CONFLICT (credential_hash) DO NOTHING
        """,
        uuid.UUID(tenant_a_id),
        cred_hash,
    )
    yield credential, tenant_a_id
    await admin_conn.execute(
        "DELETE FROM service_identities WHERE credential_hash = $1", cred_hash
    )


class TestServiceIdentityLookup:
    async def test_lookup_valid_credential(self, db_pools, seeded_identity):
        credential, tenant_a_id = seeded_identity
        repo = ServiceIdentityRepository()
        identity = await repo.lookup(credential)
        assert identity is not None
        assert identity.tenant_id == tenant_a_id
        assert identity.credential_hash == hash_credential(credential)

    async def test_lookup_invalid_credential_returns_none(self, db_pools):
        repo = ServiceIdentityRepository()
        assert await repo.lookup("definitely-wrong-credential") is None

    async def test_hash_credential_never_stores_plaintext(self, seeded_identity, admin_conn):
        credential, _ = seeded_identity
        rows = await admin_conn.fetch(
            "SELECT credential_hash FROM service_identities WHERE credential_hash = $1",
            hash_credential(credential),
        )
        assert rows[0]["credential_hash"] != credential


class TestIdentityResolverDatabaseMode:
    async def test_valid_identity_resolves(self, db_pools, seeded_identity):
        credential, tenant_a_id = seeded_identity
        resolver = IdentityResolver(
            identity_repo=ServiceIdentityRepository(),
            database_mode=True,
        )
        ctx = await resolver.resolve(
            f"Bearer {credential}",
            tenant_a_id,
            "actor-test",
            "corr-1",
        )
        assert ctx.tenant_id == tenant_a_id

    async def test_invalid_credential_denied(self, db_pools):
        resolver = IdentityResolver(
            identity_repo=ServiceIdentityRepository(),
            database_mode=True,
        )
        with pytest.raises(ValueError, match="Credencial inválida"):
            await resolver.resolve(
                "Bearer wrong-token",
                "any-tenant",
                "any-actor",
                None,
            )

    async def test_wrong_tenant_header_denied(self, db_pools, seeded_identity):
        credential, _ = seeded_identity
        resolver = IdentityResolver(
            identity_repo=ServiceIdentityRepository(),
            database_mode=True,
        )
        with pytest.raises(ValueError, match="X-Tenant-Id"):
            await resolver.resolve(
                f"Bearer {credential}",
                "wrong-tenant-id",
                "actor-test",
                None,
            )


class TestLookupLeastPrivilege:
    """SEC-001 (Sprint 0.3): lookup via pool cognitive_app (least privilege),
    sem admin_connection/BYPASSRLS. Confirma comportamento pretendido pela
    migration 002 num Postgres real."""

    async def test_lookup_updates_last_used_at(self, db_pools, seeded_identity, admin_conn):
        credential, _ = seeded_identity
        repo = ServiceIdentityRepository()
        identity = await repo.lookup(credential)
        assert identity is not None

        row = await admin_conn.fetchrow(
            "SELECT last_used_at FROM service_identities WHERE id = $1",
            uuid.UUID(identity.id),
        )
        assert row["last_used_at"] is not None

    async def test_app_role_insert_into_other_tenant_denied(
        self, db_pools, seeded_tenants, app_conn
    ):
        """RLS INSERT continua tenant-scoped mesmo com SELECT irrestrito."""
        from .conftest import set_tenant_local

        tenant_a_id = seeded_tenants["tenant-a"]
        tenant_b_id = seeded_tenants["tenant-b"]

        await set_tenant_local(app_conn, tenant_a_id)
        with pytest.raises(Exception):
            await app_conn.execute(
                """
                INSERT INTO service_identities(tenant_id, actor_id, credential_hash, profile)
                VALUES($1, 'cross-tenant-actor', 'cross-tenant-hash-xyz', 'owner-core')
                """,
                uuid.UUID(tenant_b_id),
            )

    async def test_app_role_select_is_unrestricted_by_tenant(
        self, db_pools, seeded_tenants, app_conn, admin_conn
    ):
        """Documenta o comportamento pretendido: SELECT em service_identities
        não é mais filtrado por tenant context — o credential_hash exato é
        o boundary (ver migration 002). Isolamento cross-tenant de outras
        tabelas (audit_events, tenant_resources, ...) permanece intocado —
        ver tests/db/test_rls_cross_tenant.py."""
        from .conftest import set_tenant_local

        tenant_b_id = seeded_tenants["tenant-b"]
        cred_hash = hash_credential("least-privilege-select-probe")
        await admin_conn.execute(
            """
            INSERT INTO service_identities(tenant_id, actor_id, credential_hash, profile)
            VALUES($1, 'actor-b-probe', $2, 'owner-core')
            ON CONFLICT (credential_hash) DO NOTHING
            """,
            uuid.UUID(tenant_b_id),
            cred_hash,
        )
        try:
            # app_conn nunca teve set_config para tenant_b — mesmo assim
            # o SELECT enxerga a linha (é isso que torna o lookup possível
            # antes do tenant context existir).
            await set_tenant_local(app_conn, seeded_tenants["tenant-a"])
            row = await app_conn.fetchrow(
                "SELECT tenant_id FROM service_identities WHERE credential_hash = $1",
                cred_hash,
            )
            assert row is not None
            assert str(row["tenant_id"]) == tenant_b_id
        finally:
            await admin_conn.execute(
                "DELETE FROM service_identities WHERE credential_hash = $1", cred_hash
            )


class TestWorkerIdentity:
    async def test_worker_identity_isolated_from_app_identity(
        self, db_pools, seeded_tenants, admin_conn
    ):
        tenant_a_id = seeded_tenants["tenant-a"]
        worker_credential = "gate-worker-credential-xyz789"
        worker_hash = hash_credential(worker_credential)
        await admin_conn.execute(
            """
            INSERT INTO service_identities(tenant_id, actor_id, credential_hash, profile)
            VALUES($1, 'worker-infra', $2, 'infra-read')
            ON CONFLICT (credential_hash) DO NOTHING
            """,
            uuid.UUID(tenant_a_id),
            worker_hash,
        )
        repo = ServiceIdentityRepository()
        identity = await repo.lookup(worker_credential)
        assert identity is not None
        assert identity.actor_id == "worker-infra"
        await admin_conn.execute(
            "DELETE FROM service_identities WHERE credential_hash = $1", worker_hash
        )
