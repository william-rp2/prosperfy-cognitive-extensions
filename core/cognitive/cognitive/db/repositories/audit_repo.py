"""
db/repositories/audit_repo.py — PostgresAuditWriter.

Substitui InMemoryAuditWriter quando COGNITIVE_DB_URL está configurado.
Implementa AuditPort com persistência em audit_events (append-only).
RLS enforced via tenant_transaction.
"""

from __future__ import annotations

import logging
import uuid

from ...contracts.audit import AuditEvent, AuditOutcome
from ..connection import admin_connection, tenant_transaction

logger = logging.getLogger(__name__)


class PostgresAuditWriter:
    """
    Implementa AuditPort com persistência em Postgres.

    INSERT via tenant_transaction (RLS enforced → WITH CHECK garante tenant_id correto).
    SELECT via tenant_transaction (RLS enforced → isolamento cross-tenant no banco).
    """

    async def record(self, event: AuditEvent) -> str:
        """Persiste AuditEvent. Retorna audit_id."""
        async with tenant_transaction(event.tenant_id) as conn:
            await conn.execute(
                """
                INSERT INTO audit_events(
                    audit_id, execution_id, tenant_id, actor_id,
                    capability_id, correlation_id, policy_decision, outcome,
                    inputs_redacted, result_summary, duration_ms, cost_estimate
                ) VALUES($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                """,
                uuid.UUID(event.audit_id),
                uuid.UUID(event.execution_id),
                uuid.UUID(event.tenant_id),
                event.actor_id,
                event.capability_id,
                event.correlation_id,
                event.policy_decision,
                event.outcome.value,
                event.inputs_redacted,
                event.result_summary,
                event.duration_ms,
                event.cost_estimate,
            )

        logger.info(
            "AUDIT [postgres] tenant=%s actor=%s cap=%s decision=%s outcome=%s audit_id=%s",
            event.tenant_id, event.actor_id, event.capability_id,
            event.policy_decision, event.outcome.value, event.audit_id,
        )
        return event.audit_id

    async def get(self, audit_id: str, tenant_id: str) -> AuditEvent | None:
        """
        Recupera AuditEvent.

        RLS garante isolamento: se audit_id pertencer a outro tenant,
        retorna None (não é um erro — é invisibilidade garantida pelo banco).
        """
        async with tenant_transaction(tenant_id) as conn:
            row = await conn.fetchrow(
                """
                SELECT audit_id, execution_id, tenant_id, actor_id,
                       capability_id, correlation_id, policy_decision, outcome,
                       inputs_redacted, result_summary, duration_ms, cost_estimate, created_at
                FROM audit_events
                WHERE audit_id = $1
                """,
                uuid.UUID(audit_id),
            )

        if not row:
            return None

        return AuditEvent(
            audit_id=str(row["audit_id"]),
            execution_id=str(row["execution_id"]),
            tenant_id=str(row["tenant_id"]),
            actor_id=row["actor_id"],
            capability_id=row["capability_id"],
            correlation_id=row["correlation_id"],
            policy_decision=row["policy_decision"],
            outcome=AuditOutcome(row["outcome"]),
            inputs_redacted=dict(row["inputs_redacted"]),
            result_summary=dict(row["result_summary"]),
            duration_ms=row["duration_ms"],
            cost_estimate=float(row["cost_estimate"]),
            created_at=row["created_at"],
        )

    async def list_for_tenant(
        self, tenant_id: str, limit: int = 50
    ) -> list[AuditEvent]:
        """Lista últimos N eventos do tenant (RLS enforced)."""
        async with tenant_transaction(tenant_id) as conn:
            rows = await conn.fetch(
                """
                SELECT audit_id, execution_id, tenant_id, actor_id,
                       capability_id, correlation_id, policy_decision, outcome,
                       inputs_redacted, result_summary, duration_ms, cost_estimate, created_at
                FROM audit_events
                ORDER BY created_at DESC
                LIMIT $1
                """,
                limit,
            )

        return [
            AuditEvent(
                audit_id=str(r["audit_id"]),
                execution_id=str(r["execution_id"]),
                tenant_id=str(r["tenant_id"]),
                actor_id=r["actor_id"],
                capability_id=r["capability_id"],
                correlation_id=r["correlation_id"],
                policy_decision=r["policy_decision"],
                outcome=AuditOutcome(r["outcome"]),
                inputs_redacted=dict(r["inputs_redacted"]),
                result_summary=dict(r["result_summary"]),
                duration_ms=r["duration_ms"],
                cost_estimate=float(r["cost_estimate"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]
