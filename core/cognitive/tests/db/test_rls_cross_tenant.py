"""
tests/db/test_rls_cross_tenant.py — RLS cross-tenant com roles reais.

Usa cognitive_app / cognitive_admin reais — não simulação admin+filter manual.
"""

from __future__ import annotations

import uuid

import asyncpg
import pytest

from .conftest import db_integration_available, set_tenant_local, skip_reason

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not db_integration_available(), reason=skip_reason()),
]


async def insert_audit_event(conn: asyncpg.Connection, tenant_id: str) -> str:
    audit_id = str(uuid.uuid4())
    exec_id = str(uuid.uuid4())
    await conn.execute(
        """
        INSERT INTO audit_events(
            audit_id, execution_id, tenant_id, actor_id,
            capability_id, correlation_id, policy_decision, outcome,
            inputs_redacted, result_summary
        ) VALUES($1, $2, $3, 'actor-test', 'infra.inspect', 'corr-test', 'allow', 'completed', '{}', '{}')
        """,
        uuid.UUID(audit_id),
        uuid.UUID(exec_id),
        uuid.UUID(tenant_id),
    )
    return audit_id


class TestRLSWithoutSetLocal:
    async def test_audit_events_without_tenant_context_returns_empty(
        self, app_conn, admin_conn, seeded_tenants
    ):
        tenant_a_id = seeded_tenants["tenant-a"]
        audit_id = await insert_audit_event(admin_conn, tenant_a_id)

        rows = await app_conn.fetch("SELECT audit_id FROM audit_events")
        assert len(rows) == 0, "RLS leak: rows visible without tenant context"

        await admin_conn.execute(
            "DELETE FROM audit_events WHERE audit_id = $1", uuid.UUID(audit_id)
        )

    async def test_audit_events_wrong_tenant_returns_empty(
        self, app_conn, admin_conn, seeded_tenants
    ):
        tenant_a_id = seeded_tenants["tenant-a"]
        tenant_b_id = seeded_tenants["tenant-b"]
        audit_id = await insert_audit_event(admin_conn, tenant_a_id)

        async with app_conn.transaction():
            await set_tenant_local(app_conn, tenant_b_id)
            rows = await app_conn.fetch("SELECT audit_id FROM audit_events")

        assert len(rows) == 0, f"Cross-tenant leak: tenant-B saw {len(rows)} rows"

        await admin_conn.execute(
            "DELETE FROM audit_events WHERE audit_id = $1", uuid.UUID(audit_id)
        )


class TestRLSWithCorrectTenantContext:
    async def test_audit_events_with_correct_tenant_context_returns_rows(
        self, app_conn, admin_conn, seeded_tenants
    ):
        tenant_a_id = seeded_tenants["tenant-a"]
        audit_id = await insert_audit_event(admin_conn, tenant_a_id)

        async with app_conn.transaction():
            await set_tenant_local(app_conn, tenant_a_id)
            rows = await app_conn.fetch("SELECT audit_id FROM audit_events")

        assert len(rows) == 1
        assert str(rows[0]["audit_id"]) == audit_id

        await admin_conn.execute(
            "DELETE FROM audit_events WHERE audit_id = $1", uuid.UUID(audit_id)
        )


class TestRLSAdminBypassRLS:
    async def test_admin_sees_all_tenants(self, admin_conn, seeded_tenants):
        tenant_a_id = seeded_tenants["tenant-a"]
        tenant_b_id = seeded_tenants["tenant-b"]
        audit_a = await insert_audit_event(admin_conn, tenant_a_id)
        audit_b = await insert_audit_event(admin_conn, tenant_b_id)

        rows = await admin_conn.fetch(
            "SELECT audit_id FROM audit_events WHERE audit_id = ANY($1)",
            [uuid.UUID(audit_a), uuid.UUID(audit_b)],
        )
        assert len(rows) == 2

        await admin_conn.execute(
            "DELETE FROM audit_events WHERE audit_id = ANY($1)",
            [uuid.UUID(audit_a), uuid.UUID(audit_b)],
        )


class TestRLSTenantResources:
    async def test_resource_cross_tenant_invisible(
        self, app_conn, admin_conn, seeded_tenants
    ):
        tenant_a_id = seeded_tenants["tenant-a"]
        tenant_b_id = seeded_tenants["tenant-b"]

        await admin_conn.execute(
            """
            INSERT INTO tenant_resources(tenant_id, resource_key, resource_type, resolved_params)
            VALUES($1, 'prosperfy-main', 'vps', '{"host": "secret-host"}')
            ON CONFLICT (tenant_id, resource_key) DO NOTHING
            """,
            uuid.UUID(tenant_a_id),
        )

        async with app_conn.transaction():
            await set_tenant_local(app_conn, tenant_b_id)
            rows = await app_conn.fetch(
                "SELECT resource_key FROM tenant_resources WHERE resource_key = 'prosperfy-main'"
            )

        assert len(rows) == 0

        await admin_conn.execute(
            "DELETE FROM tenant_resources WHERE tenant_id = $1 AND resource_key = 'prosperfy-main'",
            uuid.UUID(tenant_a_id),
        )
