"""
models.py — Contrato abstrato entre o Hermes e a plataforma Prosperfy Skills.

Este é o ÚNICO lugar que define o que o Hermes conhece sobre a plataforma.
Tudo que está aqui é público e independente de protocolo (MCP, REST, gRPC...).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


# ─── Enums ────────────────────────────────────────────────────────────

class Domain(str, Enum):
    """Domínios de Capabilities. Apenas os conhecidos até o momento."""
    INFRASTRUCTURE = "infrastructure"
    MARKETING = "marketing"
    AI = "ai"
    DATA = "data"
    FINANCE = "finance"
    CRM = "crm"
    COMMUNICATION = "communication"
    DOCUMENT_PROCESSING = "document_processing"
    OTHER = "other"


class CapabilityStatus(str, Enum):
    """Status operacional de uma Capability no Catálogo."""
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class CapabilityMaturity(str, Enum):
    """Nível de maturidade de uma Capability."""
    EXPERIMENTAL = "experimental"
    BETA = "beta"
    STABLE = "stable"
    DEPRECATED = "deprecated"


class ExecutionStatus(str, Enum):
    """Status de uma execução."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ─── Contrato: Catalog ────────────────────────────────────────────────

@dataclass
class IntentQuery:
    """Consulta de intencão enviada ao Catálogo.

    O Hermes monta esta query a partir da necessidade identificada
    pelo Motor Cognitivo. O Catálogo retorna as melhores Capabilities
    para atender à intencão.
    """
    intent: str
    domain: Domain | str
    context: dict[str, Any] = field(default_factory=dict)
    preferences: dict[str, Any] = field(default_factory=dict)


@dataclass
class CapabilityMetadata:
    """Metadados públicos de uma Capability."""
    capability_id: str
    display_name: str = ""
    description: str = ""
    domain: str = ""
    maturity: CapabilityMaturity = CapabilityMaturity.STABLE
    environments: list[str] = field(default_factory=list)
    cost_estimate: str = "medium"
    aliases: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    avg_duration_seconds: int | None = None
    required_role: str = "observer"


@dataclass
class CatalogMatch:
    """Candidato retornado pelo Catálogo com score de relevância."""
    capability_id: str
    score: float
    reason: str
    metadata: CapabilityMetadata | dict = field(default_factory=dict)


@dataclass
class CatalogResult:
    """Resposta do Catálogo a uma IntentQuery."""
    matches: list[CatalogMatch]
    disambiguation: bool = False
    no_match_fallback: str | None = None


# ─── Contrato: Authorization ───────────────────────────────────────────

@dataclass
class AuthorizationRequest:
    """Pedido de autorizacão para executar uma Capability."""
    capability_id: str
    identity: str = "hermes/default"
    user: str = ""
    environment: str = ""


@dataclass
class AuthorizationResult:
    """Resultado da autorizacão."""
    authorized: bool
    requires_approval: bool = False
    reason: str | None = None


# ─── Contrato: Execution ──────────────────────────────────────────────

@dataclass
class ExecutionRequest:
    """Pedido de execucão de uma Capability."""
    capability_id: str
    params: dict[str, Any]
    identity: str = "hermes/default"


@dataclass
class ExecutionReference:
    """Handle opaco de execucão.

    O Hermes armazena esta string no Cognitive Register mas
    nunca tenta interpretar seu formato interno.
    """
    ref: str


@dataclass
class CapabilityResult:
    """Resultado estruturado de uma execucão.

    Toda Capability retorna este envelope. Nunca texto livre.
    """
    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    metadata: ResultMetadata | None = None


@dataclass
class ResultMetadata:
    """Metadados operacionais do resultado."""
    duration_ms: int = 0
    execution_ref: ExecutionReference | None = None
    entities_impacted: list[str] = field(default_factory=list)
    rollback_executed: bool = False
    warnings: list[str] = field(default_factory=list)


# ─── Contrato: Status / Health ────────────────────────────────────────

@dataclass
class StatusResult:
    """Status da plataforma de Capabilities."""
    healthy: bool
    capabilities_total: int = 0
    capabilities_available: int = 0
    capabilities_degraded: int = 0


# ─── Modelos internos do Hermes (não trafegam na plataforma) ──────────

@dataclass
class CapabilityFeedback:
    """Feedback local do Hermes sobre uma execucão.

    NUNCA é enviado ao Prosperfy Skills.
    Usado exclusivamente pelo Negotiator para melhorar escolhas futuras.
    """
    capability_id: str
    intent_query: IntentQuery
    execution_ref: ExecutionReference | str
    success: bool
    duration_ms: int = 0
    rollback_executed: bool = False
    user_intervention_required: bool = False
    fallback_used: bool = False
    user_satisfaction: int | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Métricas derivadas (calculadas, não persistidas)
    _success_rate: float = 0.0
    _avg_duration_ms: float = 0.0
    _frequency: int = 0


@dataclass
class GapProposal:
    """Registro de lacuna: intencão sem Capability correspondente."""
    intent: str
    domain: str
    context: dict[str, Any] = field(default_factory=dict)
    requested_by: str = "hermes"
    timestamp: datetime = field(default_factory=datetime.utcnow)