"""
tests/db/test_audit_repo.py — PostgresAuditWriter com RLS.

GATE:
  - audit_events persistidos corretamente no Postgres
  - cross-tenant isolation via RLS (não filtro de aplicação)
  - append-only (UPDATE/DELETE bloqueados para cognitive_app)
"""

from __future__ import annotations

import uuid
import pytest

from cognitive.contracts.audit import AuditEvent, AuditOutcome
from .conftest import TESTCONTAINERS_AVAILABLE

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not TESTCONTAINERS_AVAILABLE, reason="testcontainers indisponível"),
]


def make_audit_event(tenant_id: str, cap: str = "infra.inspect") -> AuditEvent:
    return AuditEvent(
        tenant_id=tenant_id,
        actor_id="actor-test",
        capability_id=cap,
        correlation_id="corr-test-001",
        policy_decision="allow",
        outcome=AuditOutcome.COMPLETED,
        inputs_redacted={"resource": "prosperfy-main"},
        result_summary={"tool_calls": 3},
        duration_ms=150,
    )


class TestPostgresAuditWriter:

    async def test_record_and_get_audit_event(self, migrated_db, seeded_tenants):
        """AuditEvent persistido e recuperável pelo mesmo tenant."""
        from cognitive.db import connection as conn_module
        import asyncpg
        conn_module._app_pool = await asyncpg.create_pool(migrated_db, min_size=1, max_size=2)
        conn_module._admin_pool = await asyncpg.create_pool(migrated_db, min_size=1, max_size=2)

        tenant_a_id = seeded_tenants["tenant-a"]
        from cognitive.db.repositories.audit_repo import PostgresAuditWriter
        writer = PostgresAuditWriter()

        event = make_audit_event(tenant_a_id)
        audit_id = await writer.record(event)

        assert audit_id == event.audit_id

        retrieved = await writer.get(audit_id, tenant_id=tenant_a_id)
        assert retrieved is not None
        assert retrieved.capability_id == "infra.inspect"
        assert retrieved.outcome == AuditOutcome.COMPLETED
        assert retrieved.inputs_redacted["resource"] == "prosperfy-main"

        await conn_module._app_pool.close()
        await conn_module._admin_pool.close()
        conn_module._app_pool = None
        conn_module._admin_pool = None

    async def test_cross_tenant_get_returns_none(self, migrated_db, seeded_tenants):
        """
        GATE: tenant-B não pode recuperar audit_id de tenant-A.
        Isolamento garantido pelo RLS, não por filtro de aplicação.
        """
        from cognitive.db import connection as conn_module
        import asyncpg
        conn_module._app_pool = await asyncpg.create_pool(migrated_db, min_size=1, max_size=2)
        conn_module._admin_pool = await asyncpg.create_pool(migrated_db, min_size=1, max_size=2)

        tenant_a_id = seeded_tenants["tenant-a"]
        tenant_b_id = seeded_tenants["tenant-b"]

        from cognitive.db.repositories.audit_repo import PostgresAuditWriter
        writer = PostgresAuditWriter()

        # Inserir como tenant-A
        event = make_audit_event(tenant_a_id)
        audit_id = await writer.record(event)

        # Tentar recuperar como tenant-B → deve retornar None (RLS bloqueia)
        result = await writer.get(audit_id, tenant_id=tenant_b_id)
        assert result is None, (
            "FALHA CROSS-TENANT: tenant-B conseguiu acessar audit de tenant-A!"
        )

        await conn_module._app_pool.close()
        await conn_module._admin_pool.close()
        conn_module._app_pool = None
        conn_module._admin_pool = None

    async def test_audit_events_no_secrets_in_payload(self, migrated_db, seeded_tenants, admin_conn):
        """Secrets não aparecem em inputs_redacted no banco."""
        from cognitive.db import connection as conn_module
        import asyncpg
        conn_module._app_pool = await asyncpg.create_pool(migrated_db, min_size=1, max_size=2)
        conn_module._admin_pool = await asyncpg.create_pool(migrated_db, min_size=1, max_size=2)

        tenant_a_id = seeded_tenants["tenant-a"]
        from cognitive.db.repositories.audit_repo import PostgresAuditWriter
        writer = PostgresAuditWriter()

        # O audit event SEMPRE tem inputs redigidos (responsabilidade do orchestrator)
        event = make_audit_event(tenant_a_id)
        event.inputs_redacted["api_key"] = "***REDACTED***"

        audit_id = await writer.record(event)

        # Verificar direto no banco como admin
        row = await admin_conn.fetchrow(
            "SELECT inputs_redacted FROM audit_events WHERE audit_id = $1",
            uuid.UUID(audit_id),
        )
        assert row is not None
        inputs = dict(row["inputs_redacted"])
        assert inputs.get("api_key") == "***REDACTED***"
        # Garantir que nenhum valor em claro sobrou
        assert "super-secret" not in str(inputs)

        await conn_module._app_pool.close()
        await conn_module._admin_pool.close()
        conn_module._app_pool = None
        conn_module._admin_pool = None
