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
class ChannelContextRequest:
    """
    Metadado de envelope do transporte (WhatsApp) — campo TIPADO e de topo.

    F2B/D11. Existe para alimentar a ACL de finance (policy/finance_acl.py) e
    NADA MAIS. Regras que este contrato materializa:

    - É um campo IRMÃO de `params`, nunca uma chave dentro dele. O conteúdo de
      `params` é (ou pode ser) produzido por interpretação de LLM sobre o texto
      da mensagem; este envelope é produzido pelo transporte autenticado. Um
      `channel` colocado dentro de params/arguments não é lido por ninguém —
      segue como parâmetro comum e a ACL continua sem canal (DENY).
    - Só é ACEITO quando o caller apresentou service identity autenticada
      (Bearer credential resolvida pelo IdentityResolver). Ver
      gateway/routes/capabilities.py: sem isso o envelope é DESCARTADO em
      silêncio e a ACL cai em DENY_NO_CHANNEL. Fail-closed.
    """
    chat_id: str = ""
    is_group: bool = False
    transport_principal: str = ""
    incoming_message_id: str = ""
    reply_to_message_id: str = ""


@dataclass
class CapabilityExecuteRequest:
    """
    Body de POST /v1/capabilities/{id}/execute.

    tenant_id e actor_id vêm exclusivamente de headers (ADR-V2-002).
    Nunca repetir no body.
    """
    params: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None
    channel: ChannelContextRequest | None = None


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
