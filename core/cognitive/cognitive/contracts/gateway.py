"""
contracts/gateway.py — DTOs estáveis da API do Cognitive Gateway.

Contratos congelados em ADR-V2-005.
Independentes do Hermes — clientes são Hermes, Finance App, bots, workers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class GatewayStatus(str, Enum):
    COMPLETED             = "completed"
    PENDING_CONFIRMATION  = "pending_confirmation"
    FAILED                = "failed"


@dataclass
class CapabilityExecuteRequest:
    """
    Body de POST /v1/capabilities/{id}/execute.

    tenant_id e actor_id vêm exclusivamente de headers (ADR-V2-002).
    Nunca repetir no body.
    """
    params: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None


@dataclass
class CapabilityExecuteResponse:
    """Response de capability.execute."""
    execution_id: str
    correlation_id: str
    status: GatewayStatus
    data: dict[str, Any] = field(default_factory=dict)
    audit_id: str = ""
    error: str | None = None


@dataclass
class StatusResponse:
    """Response de GET /v1/status."""
    healthy: bool
    version: str
    environment: str
    runtime_mode: str
    db_configured: bool
    registry_loaded: bool
    capabilities_count: int
    tenant_id: str
    actor_id: str
    correlation_id: str


@dataclass
class CapabilityDescribeResponse:
    """Response de GET /v1/capabilities/{id}."""
    id: str
    version: str
    domain: str
    description: str
    default_policy: str
    required_scopes: list[str] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
