"""tests/db/test_resource_resolver.py — TenantResourceRepository + RLS."""

from __future__ import annotations

import uuid

import pytest

from .conftest import db_integration_available, skip_reason

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not db_integration_available(), reason=skip_reason()),
]


class TestTenantResourceRepository:
    async def test_resolve_existing_resource(self, db_pools, seeded_tenants, admin_conn):
        tenant_a_id = seeded_tenants["tenant-a"]
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
        assert resource.resolved_params["host"] == "vps.prosperfy.com.br"

        await admin_conn.execute(
            "DELETE FROM tenant_resources WHERE tenant_id = $1 AND resource_key = 'prosperfy-main'",
            uuid.UUID(tenant_a_id),
        )

    async def test_cross_tenant_resource_invisible(self, db_pools, seeded_tenants, admin_conn):
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
        assert await repo.resolve(tenant_b_id, "secret-vps") is None

        await admin_conn.execute(
            "DELETE FROM tenant_resources WHERE tenant_id = $1 AND resource_key = 'secret-vps'",
            uuid.UUID(tenant_a_id),
        )

    async def test_resolve_nonexistent_resource_returns_none(self, db_pools, seeded_tenants):
        from cognitive.db.repositories.resource_repo import TenantResourceRepository

        repo = TenantResourceRepository()
        assert await repo.resolve(seeded_tenants["tenant-a"], "nonexistent-resource") is None
