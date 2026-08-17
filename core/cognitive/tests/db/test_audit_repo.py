"""tests/db/test_audit_repo.py — PostgresAuditWriter com RLS real."""

from __future__ import annotations

import uuid

import pytest

from cognitive.contracts.audit import AuditEvent, AuditOutcome
from .conftest import db_integration_available, skip_reason

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not db_integration_available(), reason=skip_reason()),
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
    async def test_record_and_get_audit_event(
        self, db_pools, seeded_tenants, admin_conn
    ):
        tenant_a_id = seeded_tenants["tenant-a"]
        from cognitive.db.repositories.audit_repo import PostgresAuditWriter

        writer = PostgresAuditWriter()
        event = make_audit_event(tenant_a_id)
        audit_id = await writer.record(event)

        retrieved = await writer.get(audit_id, tenant_id=tenant_a_id)
        assert retrieved is not None
        assert retrieved.capability_id == "infra.inspect"

        await admin_conn.execute(
            "DELETE FROM audit_events WHERE audit_id = $1", uuid.UUID(audit_id)
        )

    async def test_cross_tenant_get_returns_none(self, db_pools, seeded_tenants, admin_conn):
        tenant_a_id = seeded_tenants["tenant-a"]
        tenant_b_id = seeded_tenants["tenant-b"]
        from cognitive.db.repositories.audit_repo import PostgresAuditWriter

        writer = PostgresAuditWriter()
        audit_id = await writer.record(make_audit_event(tenant_a_id))

        result = await writer.get(audit_id, tenant_id=tenant_b_id)
        assert result is None

        await admin_conn.execute(
            "DELETE FROM audit_events WHERE audit_id = $1", uuid.UUID(audit_id)
        )

    async def test_audit_events_no_secrets_in_payload(
        self, db_pools, seeded_tenants, admin_conn
    ):
        tenant_a_id = seeded_tenants["tenant-a"]
        from cognitive.db.repositories.audit_repo import PostgresAuditWriter

        writer = PostgresAuditWriter()
        event = make_audit_event(tenant_a_id)
        event.inputs_redacted["api_key"] = "***REDACTED***"
        audit_id = await writer.record(event)

        row = await admin_conn.fetchrow(
            "SELECT inputs_redacted FROM audit_events WHERE audit_id = $1",
            uuid.UUID(audit_id),
        )
        assert row is not None
        assert dict(row["inputs_redacted"]).get("api_key") == "***REDACTED***"

        await admin_conn.execute(
            "DELETE FROM audit_events WHERE audit_id = $1", uuid.UUID(audit_id)
        )
