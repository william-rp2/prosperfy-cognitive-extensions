"""
tests/db/test_rls_gate.py — Gate tests: connection reuse, worker, grants, escape attempts.
"""

from __future__ import annotations

import uuid

import asyncpg
import pytest

from .conftest import db_integration_available, set_tenant_local, skip_reason

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not db_integration_available(), reason=skip_reason()),
    pytest.mark.safe_remote,
]


async def _discover_privileged_roles(admin_conn: asyncpg.Connection) -> list[str]:
    """Catalog-based discovery of roles with elevated privilege.

    Doesn't assume a fixed role name (e.g. `postgres`) exists on managed
    Postgres like Supabase — instead asks the catalog which roles actually
    have BYPASSRLS or SUPERUSER, whatever they happen to be named on this
    environment.
    """
    rows = await admin_conn.fetch(
        "SELECT rolname FROM pg_roles WHERE rolbypassrls = true OR rolsuper = true"
    )
    return [row["rolname"] for row in rows]


class TestConnectionReuse:
    async def test_tenant_context_does_not_leak_between_transactions(
        self, app_conn, admin_conn, seeded_tenants
    ):
        tenant_a_id = seeded_tenants["tenant-a"]
        tenant_b_id = seeded_tenants["tenant-b"]
        audit_id = str(uuid.uuid4())
        exec_id = str(uuid.uuid4())

        await admin_conn.execute(
            """
            INSERT INTO audit_events(
                audit_id, execution_id, tenant_id, actor_id,
                capability_id, correlation_id, policy_decision, outcome
            ) VALUES($1, $2, $3, 'actor-test', 'infra.inspect', 'corr', 'allow', 'completed')
            """,
            uuid.UUID(audit_id),
            uuid.UUID(exec_id),
            uuid.UUID(tenant_a_id),
        )

        async with app_conn.transaction():
            await set_tenant_local(app_conn, tenant_a_id)
            rows_a = await app_conn.fetch("SELECT audit_id FROM audit_events")
        assert len(rows_a) == 1

        rows_no_ctx = await app_conn.fetch("SELECT audit_id FROM audit_events")
        assert len(rows_no_ctx) == 0, "Tenant context leaked after COMMIT"

        async with app_conn.transaction():
            await set_tenant_local(app_conn, tenant_b_id)
            rows_b = await app_conn.fetch("SELECT audit_id FROM audit_events")
        assert len(rows_b) == 0, "Tenant A data visible under tenant B context"

        await admin_conn.execute(
            "DELETE FROM audit_events WHERE audit_id = $1", uuid.UUID(audit_id)
        )


class TestWorkerRLS:
    async def test_worker_tenant_isolation(self, worker_conn, admin_conn, seeded_tenants):
        tenant_a_id = seeded_tenants["tenant-a"]
        tenant_b_id = seeded_tenants["tenant-b"]

        await admin_conn.execute(
            """
            INSERT INTO tenant_resources(tenant_id, resource_key, resource_type, resolved_params)
            VALUES($1, 'worker-res-a', 'vps', '{}')
            ON CONFLICT DO NOTHING
            """,
            uuid.UUID(tenant_a_id),
        )

        async with worker_conn.transaction():
            await set_tenant_local(worker_conn, tenant_a_id)
            rows_a = await worker_conn.fetch(
                "SELECT resource_key FROM tenant_resources WHERE resource_key = 'worker-res-a'"
            )
        assert len(rows_a) == 1

        async with worker_conn.transaction():
            await set_tenant_local(worker_conn, tenant_b_id)
            rows_b = await worker_conn.fetch(
                "SELECT resource_key FROM tenant_resources WHERE resource_key = 'worker-res-a'"
            )
        assert len(rows_b) == 0

        rows_no_ctx = await worker_conn.fetch(
            "SELECT resource_key FROM tenant_resources WHERE resource_key = 'worker-res-a'"
        )
        assert len(rows_no_ctx) == 0

        await admin_conn.execute(
            "DELETE FROM tenant_resources WHERE tenant_id = $1 AND resource_key = 'worker-res-a'",
            uuid.UUID(tenant_a_id),
        )


class TestCapabilityGrants:
    async def test_grant_visible_only_to_own_tenant(
        self, app_conn, admin_conn, seeded_tenants
    ):
        tenant_a_id = seeded_tenants["tenant-a"]
        tenant_b_id = seeded_tenants["tenant-b"]

        await admin_conn.execute(
            """
            INSERT INTO capability_grants(tenant_id, profile, capability_id)
            VALUES($1, 'owner-core', 'infra.inspect')
            ON CONFLICT DO NOTHING
            """,
            uuid.UUID(tenant_a_id),
        )

        async with app_conn.transaction():
            await set_tenant_local(app_conn, tenant_a_id)
            rows_a = await app_conn.fetch(
                "SELECT capability_id FROM capability_grants WHERE capability_id = 'infra.inspect'"
            )
        assert len(rows_a) == 1

        async with app_conn.transaction():
            await set_tenant_local(app_conn, tenant_b_id)
            rows_b = await app_conn.fetch(
                "SELECT capability_id FROM capability_grants WHERE capability_id = 'infra.inspect'"
            )
        assert len(rows_b) == 0

        await admin_conn.execute(
            "DELETE FROM capability_grants WHERE tenant_id = $1 AND capability_id = 'infra.inspect'",
            uuid.UUID(tenant_a_id),
        )


class TestRolePrivileges:
    async def test_app_role_has_no_bypassrls(self, app_conn):
        row = await app_conn.fetchrow(
            "SELECT rolname, rolbypassrls, rolsuper FROM pg_roles WHERE rolname = current_user"
        )
        assert row is not None
        assert row["rolbypassrls"] is False
        assert row["rolsuper"] is False

    async def test_worker_role_has_no_bypassrls(self, worker_conn):
        row = await worker_conn.fetchrow(
            "SELECT rolname, rolbypassrls, rolsuper FROM pg_roles WHERE rolname = current_user"
        )
        assert row is not None
        assert row["rolbypassrls"] is False
        assert row["rolsuper"] is False

    async def test_app_cannot_set_role_admin(self, app_conn):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app_conn.execute("SET ROLE cognitive_admin")

    async def test_app_is_not_member_of_any_privileged_role(self, app_conn, admin_conn):
        """Fixed for Homolog: the old version hardcoded `SET ROLE postgres`
        and caught the exception — Supabase's managed Postgres doesn't
        necessarily expose a role literally named `postgres` to escalate
        into, so the test never proved anything there.

        The PRIMARY, definitive assertion here is catalog-based and doesn't
        depend on attempting-and-catching an exception: discover every role
        that actually has elevated privilege (BYPASSRLS or SUPERUSER) via
        pg_roles, then confirm cognitive_app has MEMBER membership in none
        of them. That holds regardless of what those roles are named.

        The SET ROLE attempt against the first discovered privileged role is
        kept as a SECONDARY, defense-in-depth check — bonus evidence, not
        the test's only evidence. If no privileged role is discovered
        (shouldn't happen, since migration 000 always creates
        cognitive_admin with BYPASSRLS), the attempt is skipped rather than
        failing artificially against an empty list.
        """
        privileged_roles = await _discover_privileged_roles(admin_conn)

        for rolname in privileged_roles:
            is_member = await admin_conn.fetchval(
                "SELECT pg_has_role('cognitive_app', $1, 'MEMBER')", rolname
            )
            assert is_member is False, (
                f"cognitive_app must not be a member of privileged role {rolname!r}"
            )

        if not privileged_roles:
            pytest.skip(
                "no BYPASSRLS/SUPERUSER role discovered in pg_roles — "
                "nothing to defensively attempt SET ROLE against"
            )

        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app_conn.execute(f"SET ROLE {privileged_roles[0]}")

    async def test_worker_is_not_member_of_any_privileged_role(self, worker_conn, admin_conn):
        """Same as test_app_is_not_member_of_any_privileged_role, for
        cognitive_worker — see that test's docstring for the rationale."""
        privileged_roles = await _discover_privileged_roles(admin_conn)

        for rolname in privileged_roles:
            is_member = await admin_conn.fetchval(
                "SELECT pg_has_role('cognitive_worker', $1, 'MEMBER')", rolname
            )
            assert is_member is False, (
                f"cognitive_worker must not be a member of privileged role {rolname!r}"
            )

        if not privileged_roles:
            pytest.skip(
                "no BYPASSRLS/SUPERUSER role discovered in pg_roles — "
                "nothing to defensively attempt SET ROLE against"
            )

        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await worker_conn.execute(f"SET ROLE {privileged_roles[0]}")
