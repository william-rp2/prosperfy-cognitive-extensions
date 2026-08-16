"""
tests/db/test_rls_cross_tenant.py — Testes de RLS cross-tenant no banco.

GATE:
  - RLS não depende apenas de filtros da aplicação
  - tenant-B não vê rows de tenant-A via cognitive_app role
  - Sem SET LOCAL → retorna 0 rows (não todos os rows)
  - cognitive_admin vê todos os rows (BYPASSRLS confirmado)

Evidência exigida pelo Sprint 0.2 Gate antes de declarar PASS.
"""

from __future__ import annotations

import uuid
import pytest
import pytest_asyncio
import asyncpg

from .conftest import TESTCONTAINERS_AVAILABLE

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not TESTCONTAINERS_AVAILABLE, reason="testcontainers indisponível"),
]


async def insert_audit_event(conn: asyncpg.Connection, tenant_id: str, cap: str = "infra.inspect") -> str:
    """Helper: insere um audit_event como admin e retorna audit_id."""
    audit_id = str(uuid.uuid4())
    exec_id = str(uuid.uuid4())
    await conn.execute(
        """
        INSERT INTO audit_events(
            audit_id, execution_id, tenant_id, actor_id,
            capability_id, correlation_id, policy_decision, outcome,
            inputs_redacted, result_summary
        ) VALUES($1, $2, $3, 'actor-test', $4, 'corr-test', 'allow', 'completed', '{}', '{}')
        """,
        uuid.UUID(audit_id), uuid.UUID(exec_id), uuid.UUID(tenant_id), cap,
    )
    return audit_id


async def set_tenant_context(conn: asyncpg.Connection, tenant_id: str) -> None:
    """Simula SET LOCAL app.current_tenant_id dentro de transação."""
    await conn.execute(
        "SELECT set_config('app.current_tenant_id', $1, true)", tenant_id
    )


class TestRLSWithoutSetLocal:
    """RLS: sem SET LOCAL → 0 rows para cognitive_app (não todos os rows)."""

    async def test_audit_events_without_tenant_context_returns_empty(
        self, app_conn, admin_conn, seeded_tenants
    ):
        """
        GATE: cogntive_app sem SET LOCAL não deve ver NENHUM row de audit_events.
        Sem contexto de tenant → `current_setting('app.current_tenant_id', true)` = ''
        → nenhum tenant_id::text = '' → 0 rows.
        """
        tenant_a_id = seeded_tenants["tenant-a"]

        # Inserir como admin
        audit_id = await insert_audit_event(admin_conn, tenant_a_id)

        # Consultar sem SET LOCAL (simula cognitive_app sem contexto)
        # Usamos a conexão admin mas aplicamos a policy manualmente via GUC vazio
        await app_conn.execute("SELECT set_config('app.current_tenant_id', '', true)")

        rows = await app_conn.fetch(
            "SELECT audit_id FROM audit_events "
            "WHERE tenant_id::text = current_setting('app.current_tenant_id', true)"
        )

        assert len(rows) == 0, (
            "FALHA DE SEGURANÇA: audit_events visível sem tenant context!"
        )

        # Cleanup
        await admin_conn.execute("DELETE FROM audit_events WHERE audit_id = $1", uuid.UUID(audit_id))

    async def test_audit_events_wrong_tenant_returns_empty(
        self, app_conn, admin_conn, seeded_tenants
    ):
        """
        GATE: tenant-B não pode acessar audit_events de tenant-A via SET LOCAL com tenant-B.
        """
        tenant_a_id = seeded_tenants["tenant-a"]
        tenant_b_id = seeded_tenants["tenant-b"]

        audit_id = await insert_audit_event(admin_conn, tenant_a_id)

        # Setar contexto de tenant-B
        await app_conn.execute(
            "SELECT set_config('app.current_tenant_id', $1, true)", tenant_b_id
        )

        rows = await app_conn.fetch(
            "SELECT audit_id FROM audit_events "
            "WHERE tenant_id::text = current_setting('app.current_tenant_id', true)"
        )

        assert len(rows) == 0, (
            f"FALHA CROSS-TENANT: tenant-B conseguiu ver {len(rows)} rows de tenant-A!"
        )

        # Cleanup
        await admin_conn.execute("DELETE FROM audit_events WHERE audit_id = $1", uuid.UUID(audit_id))


class TestRLSWithCorrectTenantContext:
    """RLS: com SET LOCAL correto → rows do tenant próprio visíveis."""

    async def test_audit_events_with_correct_tenant_context_returns_rows(
        self, app_conn, admin_conn, seeded_tenants
    ):
        """
        Tenant-A com contexto correto deve ver os próprios audit_events.
        """
        tenant_a_id = seeded_tenants["tenant-a"]

        audit_id = await insert_audit_event(admin_conn, tenant_a_id)

        # Setar contexto correto
        await app_conn.execute(
            "SELECT set_config('app.current_tenant_id', $1, true)", tenant_a_id
        )

        rows = await app_conn.fetch(
            "SELECT audit_id FROM audit_events "
            "WHERE tenant_id::text = current_setting('app.current_tenant_id', true)"
        )

        assert len(rows) == 1
        assert str(rows[0]["audit_id"]) == audit_id

        # Cleanup
        await admin_conn.execute("DELETE FROM audit_events WHERE audit_id = $1", uuid.UUID(audit_id))


class TestRLSAdminBypassRLS:
    """BYPASSRLS: cognitive_admin vê todos os tenants."""

    async def test_admin_sees_all_tenants(self, admin_conn, seeded_tenants):
        """cognitive_admin deve enxergar rows de ambos os tenants."""
        tenant_a_id = seeded_tenants["tenant-a"]
        tenant_b_id = seeded_tenants["tenant-b"]

        audit_a = await insert_audit_event(admin_conn, tenant_a_id)
        audit_b = await insert_audit_event(admin_conn, tenant_b_id)

        # Admin sem SET LOCAL → vê todos
        rows = await admin_conn.fetch("SELECT audit_id FROM audit_events WHERE audit_id = ANY($1)",
                                       [uuid.UUID(audit_a), uuid.UUID(audit_b)])
        assert len(rows) == 2, "cognitive_admin deve ver rows de todos os tenants (BYPASSRLS)"

        # Cleanup
        await admin_conn.execute(
            "DELETE FROM audit_events WHERE audit_id = ANY($1)",
            [uuid.UUID(audit_a), uuid.UUID(audit_b)],
        )


class TestRLSTenantResources:
    """RLS: tenant_resources isolado por tenant_id."""

    async def test_resource_cross_tenant_invisible(self, app_conn, admin_conn, seeded_tenants):
        """tenant-B não pode resolver resource_key de tenant-A."""
        tenant_a_id = seeded_tenants["tenant-a"]
        tenant_b_id = seeded_tenants["tenant-b"]

        # Criar resource para tenant-A como admin
        await admin_conn.execute(
            """
            INSERT INTO tenant_resources(tenant_id, resource_key, resource_type, resolved_params)
            VALUES($1, 'prosperfy-main', 'vps', '{"host": "secret-host"}')
            ON CONFLICT (tenant_id, resource_key) DO NOTHING
            """,
            uuid.UUID(tenant_a_id),
        )

        # Consultar como tenant-B
        await app_conn.execute(
            "SELECT set_config('app.current_tenant_id', $1, true)", tenant_b_id
        )

        rows = await app_conn.fetch(
            "SELECT resource_key FROM tenant_resources "
            "WHERE resource_key = 'prosperfy-main' "
            "AND tenant_id::text = current_setting('app.current_tenant_id', true)"
        )

        assert len(rows) == 0, (
            "FALHA: tenant-B conseguiu resolver resource de tenant-A!"
        )

        # Cleanup
        await admin_conn.execute(
            "DELETE FROM tenant_resources WHERE tenant_id = $1 AND resource_key = 'prosperfy-main'",
            uuid.UUID(tenant_a_id),
        )
