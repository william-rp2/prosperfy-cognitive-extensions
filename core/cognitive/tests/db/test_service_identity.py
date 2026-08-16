"""
tests/db/test_service_identity.py — Testes do ServiceIdentityRepository.

GATE: service identities/workers — credential hash lookup funcional
"""

from __future__ import annotations

import uuid
import pytest
import asyncpg

from cognitive.db.repositories.identity_repo import ServiceIdentityRepository, hash_credential
from .conftest import TESTCONTAINERS_AVAILABLE

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not TESTCONTAINERS_AVAILABLE, reason="testcontainers indisponível"),
]


@pytest.fixture
async def seeded_identity(admin_conn, seeded_tenants):
    """Seed de service identity para tenant-a."""
    tenant_a_id = seeded_tenants["tenant-a"]
    credential = "test-credential-abc123"
    cred_hash = hash_credential(credential)

    await admin_conn.execute(
        """
        INSERT INTO service_identities(tenant_id, actor_id, credential_hash, profile)
        VALUES($1, 'actor-test', $2, 'owner-core')
        ON CONFLICT (credential_hash) DO NOTHING
        """,
        uuid.UUID(tenant_a_id), cred_hash,
    )
    yield credential, tenant_a_id

    await admin_conn.execute(
        "DELETE FROM service_identities WHERE credential_hash = $1", cred_hash
    )


class TestServiceIdentityLookup:
    """ServiceIdentityRepository lookup via credential hash."""

    async def test_lookup_valid_credential(self, migrated_db, seeded_identity, seeded_tenants):
        """Lookup de credencial válida retorna identity correta."""
        from cognitive.db import connection as conn_module
        import asyncpg as apg
        conn_module._admin_pool = await apg.create_pool(migrated_db, min_size=1, max_size=2)

        credential, tenant_a_id = seeded_identity
        repo = ServiceIdentityRepository()
        identity = await repo.lookup(credential)

        assert identity is not None
        assert identity.tenant_id == tenant_a_id
        assert identity.actor_id == "actor-test"
        assert identity.profile == "owner-core"
        assert identity.active is True
        # Nunca retorna o valor original — apenas o hash
        assert identity.credential_hash == hash_credential(credential)
        assert credential not in identity.credential_hash

        await conn_module._admin_pool.close()
        conn_module._admin_pool = None

    async def test_lookup_invalid_credential_returns_none(self, migrated_db):
        """Credencial inválida retorna None — sem erro."""
        from cognitive.db import connection as conn_module
        import asyncpg as apg
        conn_module._admin_pool = await apg.create_pool(migrated_db, min_size=1, max_size=2)

        repo = ServiceIdentityRepository()
        identity = await repo.lookup("definitely-wrong-credential")
        assert identity is None

        await conn_module._admin_pool.close()
        conn_module._admin_pool = None

    async def test_hash_credential_never_stores_plaintext(self, seeded_identity, admin_conn):
        """Verificar que o banco nunca armazena o valor em claro."""
        credential, _ = seeded_identity
        rows = await admin_conn.fetch(
            "SELECT credential_hash FROM service_identities WHERE credential_hash = $1",
            hash_credential(credential),
        )
        assert len(rows) == 1
        stored_hash = rows[0]["credential_hash"]
        # O hash não deve ser igual ao valor original
        assert stored_hash != credential
        # O hash deve ser hexadecimal (sha256)
        assert all(c in "0123456789abcdef" for c in stored_hash)


class TestWorkerIdentity:
    """
    GATE: comportamento de service identities para workers.

    Workers usam credentials próprias e têm profile/scope específico.
    """

    async def test_worker_identity_isolated_from_app_identity(
        self, migrated_db, seeded_tenants, admin_conn
    ):
        """
        Worker credential é distinta da credential de app.
        Cada serviço/worker tem sua própria identity.
        """
        from cognitive.db import connection as conn_module
        import asyncpg as apg
        conn_module._admin_pool = await apg.create_pool(migrated_db, min_size=1, max_size=2)

        tenant_a_id = seeded_tenants["tenant-a"]
        worker_credential = "worker-credential-xyz789"
        worker_hash = hash_credential(worker_credential)

        # Registrar worker identity
        await admin_conn.execute(
            """
            INSERT INTO service_identities(tenant_id, actor_id, credential_hash, profile)
            VALUES($1, 'worker-infra', $2, 'infra-read')
            ON CONFLICT (credential_hash) DO NOTHING
            """,
            uuid.UUID(tenant_a_id), worker_hash,
        )

        repo = ServiceIdentityRepository()
        identity = await repo.lookup(worker_credential)

        assert identity is not None
        assert identity.actor_id == "worker-infra"
        assert identity.profile == "infra-read"
        assert identity.tenant_id == tenant_a_id

        # Cleanup
        await admin_conn.execute(
            "DELETE FROM service_identities WHERE credential_hash = $1", worker_hash
        )
        await conn_module._admin_pool.close()
        conn_module._admin_pool = None
