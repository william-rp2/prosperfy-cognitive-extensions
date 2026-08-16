"""
contracts/capability.py — Ports e DTOs de capability para o Cognitive Core V2.

Portado e adaptado de hermes/capability-intelligence/src/capability_intelligence/models.py.
O legado Hermes permanece intocado; este módulo é a fonte canônica do Core V2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


# ─── Enums ─────────────────────────────────────────────────────────────

class Domain(str, Enum):
    """Domínios de Capability."""
    INFRASTRUCTURE = "infrastructure"
    FINANCE = "finance"
    CRM = "crm"
    COMMUNICATION = "communication"
    DOCUMENT_PROCESSING = "document_processing"
    MARKETING = "marketing"
    AI = "ai"
    DATA = "data"
    OTHER = "other"


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PENDING_CONFIRMATION = "pending_confirmation"
    FAILED = "failed"
    CANCELLED = "cancelled"


class IdempotencyBehavior(str, Enum):
    NONE = "none"
    RETURN_CACHED = "return_cached"
    REJECT = "reject"


# ─── Capability definition (vem do YAML/Registry) ──────────────────────

@dataclass
class RegisteredCapability:
    """Capability registrada no Registry (lida do YAML)."""
    id: str
    version: str
    domain: Domain | str
    description: str
    adapter: str                              # ex: "prosperfy_skills"
    default_policy: str                       # "allow" | "confirm" | "deny"
    required_scopes: list[str] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    idempotency_behavior: IdempotencyBehavior = IdempotencyBehavior.RETURN_CACHED
    timeout_seconds: int = 30
    cost_class: str = "low"                   # "low" | "medium" | "high"
    audit_rules: dict[str, Any] = field(default_factory=dict)
    redaction_rules: list[str] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)  # steps da capability composta


# ─── Ports internos (Protocol) ──────────────────────────────────────────

@dataclass
class ExecutionRequest:
    """Pedido de execução de uma Capability."""
    capability_id: str
    params: dict[str, Any]
    tenant_id: str
    actor_id: str
    correlation_id: str
    idempotency_key: str | None = None


@dataclass
class ExecutionReference:
    """Handle opaco de execução."""
    execution_id: str
    correlation_id: str


@dataclass
class CapabilityResult:
    """Resultado estruturado de uma execução."""
    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: int = 0


class CapabilityRegistryPort(Protocol):
    def get(self, capability_id: str) -> RegisteredCapability | None: ...
    def list_all(self) -> list[RegisteredCapability]: ...


class SkillsAdapterPort(Protocol):
    async def invoke_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        tenant_id: str,
        correlation_id: str,
    ) -> dict[str, Any]: ...

    async def health(self) -> bool: ...
