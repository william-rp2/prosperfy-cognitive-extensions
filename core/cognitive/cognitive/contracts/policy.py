"""
contracts/policy.py — Modelo de policy do Cognitive Core V2.

Decisões congeladas em ADR-V2-004:
- ALLOW: executa o adapter após grants + resource resolution
- CONFIRM: NÃO executa adapter; retorna pending_confirmation + audit_id
- DENY: NÃO executa adapter; retorna 403
- Ordem obrigatória: Policy ANTES de Adapter, sempre
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .capability import RegisteredCapability
from .tenancy import ActorContext


class PolicyDecision(str, Enum):
    """
    Veredito de policy — nomenclatura V2 (ADR-V2-004).

    Mapeamento do legado CI:
    - ALLOW           → ALLOW
    - REQUIRE_APPROVAL → CONFIRM
    - DENY            → DENY
    """
    ALLOW   = "allow"
    CONFIRM = "confirm"
    DENY    = "deny"


@dataclass
class PolicyVerdict:
    """Resultado completo da avaliação de policy."""
    decision: PolicyDecision
    reason: str
    policy_name: str = "default"


class PolicyPort(Protocol):
    async def evaluate(
        self,
        ctx: ActorContext,
        capability: RegisteredCapability,
        params: dict,
    ) -> PolicyVerdict: ...
