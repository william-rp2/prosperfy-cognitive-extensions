"""
contracts/audit.py — Contratos de auditoria e rastreamento do Cognitive Core V2.

Toda ação relevante registra: actor, tenant, capability, inputs redigidos,
decisão de policy, resultado, duração, custo e correlation_id. (R13)

Sprint 0.1: persistência in-memory (RAM).
Sprint 0.2+: persistência em Postgres (tabela audit_events).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol


class AuditOutcome(str, Enum):
    COMPLETED = "completed"
    PENDING_CONFIRMATION = "pending_confirmation"
    DENIED = "denied"
    FAILED = "failed"


@dataclass
class AuditEvent:
    """
    Registro append-only de execução.

    inputs_redacted: params do cliente com campos sensíveis substituídos por "***".
    Nunca armazenar secrets em claro. (R14)
    """
    tenant_id: str
    actor_id: str
    capability_id: str
    correlation_id: str
    policy_decision: str                              # "allow" | "confirm" | "deny"
    outcome: AuditOutcome
    inputs_redacted: dict[str, Any] = field(default_factory=dict)
    result_summary: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    cost_estimate: float = 0.0
    audit_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ExecutionTrace:
    """Passo individual em uma capability composta."""
    execution_id: str
    step_index: int
    tool_name: str
    status: str
    duration_ms: int = 0
    error: str | None = None


class AuditPort(Protocol):
    async def record(self, event: AuditEvent) -> str:
        """Persiste o AuditEvent e retorna o audit_id."""
        ...

    async def get(self, audit_id: str, tenant_id: str) -> AuditEvent | None:
        """Recupera um evento — filtrando por tenant (sem cross-tenant). """
        ...
