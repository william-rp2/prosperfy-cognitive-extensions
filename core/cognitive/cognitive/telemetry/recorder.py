"""
telemetry/recorder.py — TelemetryPort in-memory (Sprint 0.1).

Registra métricas por request: rota, latência, tool calls, estimativa de custo.
Sprint 0.1: in-memory. Sprint 0.3 (fechamento E2E): cost_telemetry no Postgres
via db/repositories/telemetry_repo.py::PostgresTelemetryRecorder — achado
durante a integração do Live MCP E2E Runner: gateway/app.py fiava
InMemoryTelemetryRecorder() incondicionalmente, mesmo em COGNITIVE_MODE=
database, então telemetry nunca persistia de verdade (só audit persistia).
`record()` é `async` desde este hotfix — único call site é
execution/orchestrator.py::_record_telemetry, que já é `await`ado; nenhum
teste chama `.record()` diretamente (só constroem o recorder e leem
`.get_all_for_tenant()`, que continua síncrono), então esta mudança de
assinatura não quebra nenhum teste existente.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class TelemetryRecord:
    tenant_id: str
    actor_id: str
    capability_id: str
    correlation_id: str
    latency_ms: int
    tool_calls: int = 0
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_estimate: float = 0.0
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class InMemoryTelemetryRecorder:
    """
    Registra telemetria de execuções em memória.

    Sprint 0.1: in-memory. Sprint 0.2+: Postgres cost_telemetry.
    """

    def __init__(self) -> None:
        self._records: list[TelemetryRecord] = []

    async def record(self, record: TelemetryRecord) -> None:
        self._records.append(record)
        logger.info(
            "TELEMETRY tenant=%s cap=%s latency_ms=%d tool_calls=%d cost=%.4f",
            record.tenant_id,
            record.capability_id,
            record.latency_ms,
            record.tool_calls,
            record.cost_estimate,
        )

    def get_all_for_tenant(self, tenant_id: str) -> list[TelemetryRecord]:
        return [r for r in self._records if r.tenant_id == tenant_id]

    def clear(self) -> None:
        self._records.clear()
