"""
tests/db/test_resource_resolver.py — TenantResourceRepository e cross-tenant isolation.

GATE: resource resolution funcional + tenant B não pode resolver resource de tenant A
"""

from __future__ import annotations

import uuid
import pytest

from .conftest import TESTCONTAINERS_AVAILABLE

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not TESTCONTAINERS_AVAILABLE, reason="testcontainers indisponível"),
]


class TestTenantResourceRepository:

    async def test_resolve_existing_resource(self, migrated_db, seeded_tenants, admin_conn):
        """Resolve resource_key para tenant correto → retorna resolved_params."""
        from cognitive.db import connection as conn_module
        import asyncpg
        conn_module._app_pool = await asyncpg.create_pool(migrated_db, min_size=1, max_size=2)
        conn_module._admin_pool = await asyncpg.create_pool(migrated_db, min_size=1, max_size=2)

        tenant_a_id = seeded_tenants["tenant-a"]

        # Seed resource
        await admin_conn.execute(
            """
            INSERT INTO tenant_resources(tenant_id, resource_key, resource_type, resolved_params)
            VALUES($1, 'prosperfy-main', 'vps', '{"host": "vps.prosperfy.com.br", "port": 22}')
            ON CONFLICT (tenant_id, resource_key) DO NOTHING
            """,
            uuid.UUID(tenant_a_id),
        )

        from cognitive.db.repositories.resource_repo import TenantResourceRepository
        repo = TenantResourceRepository()
        resource = await repo.resolve(tenant_a_id, "prosperfy-main")

        assert resource is not None
        assert resource.resource_key == "prosperfy-main"
        assert resource.resource_type == "vps"
        assert resource.resolved_params["host"] == "vps.prosperfy.com.br"

        # Cleanup
        await admin_conn.execute(
            "DELETE FROM tenant_resources WHERE tenant_id = $1 AND resource_key = 'prosperfy-main'",
            uuid.UUID(tenant_a_id),
        )
        await conn_module._app_pool.close()
        await conn_module._admin_pool.close()
        conn_module._app_pool = None
        conn_module._admin_pool = None

    async def test_cross_tenant_resource_invisible(self, migrated_db, seeded_tenants, admin_conn):
        """
        GATE: tenant-B não pode resolver resource registrado para tenant-A.
        RLS bloqueia no banco — não apenas na aplicação.
        """
        from cognitive.db import connection as conn_module
        import asyncpg
        conn_module._app_pool = await asyncpg.create_pool(migrated_db, min_size=1, max_size=2)
        conn_module._admin_pool = await asyncpg.create_pool(migrated_db, min_size=1, max_size=2)

        tenant_a_id = seeded_tenants["tenant-a"]
        tenant_b_id = seeded_tenants["tenant-b"]

        await admin_conn.execute(
            """
            INSERT INTO tenant_resources(tenant_id, resource_key, resource_type, resolved_params)
            VALUES($1, 'secret-vps', 'vps', '{"host": "private-host.prosperfy.com.br"}')
            ON CONFLICT (tenant_id, resource_key) DO NOTHING
            """,
            uuid.UUID(tenant_a_id),
        )

        from cognitive.db.repositories.resource_repo import TenantResourceRepository
        repo = TenantResourceRepository()

        # tenant-B tenta resolver resource de tenant-A
        result = await repo.resolve(tenant_b_id, "secret-vps")
        assert result is None, (
            "FALHA: tenant-B conseguiu resolver resource de tenant-A!"
        )

        # Cleanup
        await admin_conn.execute(
            "DELETE FROM tenant_resources WHERE tenant_id = $1 AND resource_key = 'secret-vps'",
            uuid.UUID(tenant_a_id),
        )
        await conn_module._app_pool.close()
        await conn_module._admin_pool.close()
        conn_module._app_pool = None
        conn_module._admin_pool = None

    async def test_resolve_nonexistent_resource_returns_none(self, migrated_db, seeded_tenants):
        """Resolve de resource inexistente retorna None."""
        from cognitive.db import connection as conn_module
        import asyncpg
        conn_module._app_pool = await asyncpg.create_pool(migrated_db, min_size=1, max_size=2)
        conn_module._admin_pool = await asyncpg.create_pool(migrated_db, min_size=1, max_size=2)

        tenant_a_id = seeded_tenants["tenant-a"]

        from cognitive.db.repositories.resource_repo import TenantResourceRepository
        repo = TenantResourceRepository()
        result = await repo.resolve(tenant_a_id, "nonexistent-resource")
        assert result is None

        await conn_module._app_pool.close()
        await conn_module._admin_pool.close()
        conn_module._app_pool = None
        conn_module._admin_pool = None
