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
