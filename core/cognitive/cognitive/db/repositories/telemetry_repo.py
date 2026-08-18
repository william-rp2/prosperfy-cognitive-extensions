"""
db/repositories/telemetry_repo.py — PostgresTelemetryRecorder.

Substitui InMemoryTelemetryRecorder quando COGNITIVE_DB_URL está configurado.
Implementa TelemetryPort com persistência em cost_telemetry.
RLS enforced via tenant_transaction — mesmo padrão de audit_repo.py.

Achado durante a integração do Live MCP E2E Runner (fechamento Sprint 0.3):
gateway/app.py fiava InMemoryTelemetryRecorder() incondicionalmente, mesmo em
COGNITIVE_MODE=database — cost_telemetry nunca recebia linha nenhuma em
produção/Homolog, só audit_events persistia de verdade. Este módulo fecha
essa lacuna, espelhando audit_repo.py.
"""

from __future__ import annotations

import logging
import uuid

from ..connection import tenant_transaction

logger = logging.getLogger(__name__)


class PostgresTelemetryRecorder:
    """
    Implementa TelemetryPort com persistência em Postgres.

    INSERT via tenant_transaction (RLS enforced → WITH CHECK garante
    tenant_id correto, mesmo isolamento cross-tenant do audit_events).
    """

    async def record(self, record) -> None:  # record: TelemetryRecord
        """Persiste TelemetryRecord em cost_telemetry."""
        async with tenant_transaction(record.tenant_id) as conn:
            await conn.execute(
                """
                INSERT INTO cost_telemetry(
                    tenant_id, actor_id, capability_id, correlation_id,
                    latency_ms, tool_calls, tokens_in, tokens_out, cost_estimate
                ) VALUES($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                uuid.UUID(record.tenant_id),
                record.actor_id,
                record.capability_id,
                record.correlation_id,
                record.latency_ms,
                record.tool_calls,
                record.tokens_in,
                record.tokens_out,
                record.cost_estimate,
            )

        logger.info(
            "TELEMETRY [postgres] tenant=%s cap=%s latency_ms=%d tool_calls=%d cost=%.4f",
            record.tenant_id,
            record.capability_id,
            record.latency_ms,
            record.tool_calls,
            record.cost_estimate,
        )

    async def get_all_for_tenant(self, tenant_id: str) -> list:
        """Lista telemetry records do tenant (RLS enforced). Paridade com
        InMemoryTelemetryRecorder.get_all_for_tenant — não usado pelo
        orchestrator hoje, existe para inspeção/testes."""
        from ...telemetry.recorder import TelemetryRecord

        async with tenant_transaction(tenant_id) as conn:
            rows = await conn.fetch(
                """
                SELECT tenant_id, actor_id, capability_id, correlation_id,
                       latency_ms, tool_calls, tokens_in, tokens_out,
                       cost_estimate, recorded_at
                FROM cost_telemetry
                WHERE tenant_id = $1
                ORDER BY recorded_at DESC
                """,
                uuid.UUID(tenant_id),
            )
        return [
            TelemetryRecord(
                tenant_id=str(r["tenant_id"]),
                actor_id=r["actor_id"],
                capability_id=r["capability_id"],
                correlation_id=r["correlation_id"],
                latency_ms=r["latency_ms"],
                tool_calls=r["tool_calls"],
                tokens_in=r["tokens_in"],
                tokens_out=r["tokens_out"],
                cost_estimate=float(r["cost_estimate"]),
                recorded_at=r["recorded_at"],
            )
            for r in rows
        ]
