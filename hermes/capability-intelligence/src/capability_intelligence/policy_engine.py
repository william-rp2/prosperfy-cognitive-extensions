"""
policy_engine.py — Valida políticas antes da execucão.

Genérico: aplica-se a qualquer domínio (Infraestrutura, Marketing,
CRM, Financeiro, IA, etc.). Cada política é uma funcão independente
que pode ser ativada/desativada seletivamente.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable


class PolicyResult(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass
class PolicyVerdict:
    """Resultado da avaliacão de uma política."""
    policy: str
    result: PolicyResult
    reason: str | None = None


@dataclass
class PolicyEngine:
    """
    Avalia políticas antes da execucão de uma Capability.

    Cada política é uma funcão que recebe contexto e retorna um veredito.
    """

    # Políticas ativas (podem ser configuradas externamente)
    policies: list[Callable[..., PolicyVerdict]] = field(default_factory=list)

    async def evaluate(self, capability_id: str,
                       user: str,
                       environment: str,
                       domain: str,
                       authorization_result: dict | None = None,
                       cognitive_state: dict | None = None) -> list[PolicyVerdict]:
        """Executa todas as políticas ativas e retorna a lista de vereditos."""
        verdicts: list[PolicyVerdict] = []

        for policy in self.policies:
            verdict = policy(
                capability_id=capability_id,
                user=user,
                environment=environment,
                domain=domain,
                authorization=authorization_result,
                cognitive_state=cognitive_state or {},
            )
            verdicts.append(verdict)

        return verdicts

    def requires_approval(self, verdicts: list[PolicyVerdict]) -> bool:
        return any(v.result == PolicyResult.REQUIRE_APPROVAL for v in verdicts)

    def is_denied(self, verdicts: list[PolicyVerdict]) -> bool:
        return any(v.result == PolicyResult.DENY for v in verdicts)


# ─── Políticas built-in (exemplos) ────────────────────────────────────

def policy_requires_approval(capability_id: str, environment: str,
                             authorization: dict | None = None,
                             **kwargs) -> PolicyVerdict:
    """Se a Capability exige aprovacão, retorna REQUIRE_APPROVAL."""
    if authorization and authorization.get("requires_approval"):
        return PolicyVerdict(
            policy="requires_approval",
            result=PolicyResult.REQUIRE_APPROVAL,
            reason="Capability requer aprovacão do usuário",
        )
    return PolicyVerdict(policy="requires_approval", result=PolicyResult.ALLOW)


def policy_environment_allowed(capability_id: str, environment: str,
                               cognitive_state: dict | None = None,
                               **kwargs) -> PolicyVerdict:
    """Verifica se o ambiente é permitido para a Capability."""
    allowed = ["staging", "production"]  # poderia vir de metadata
    if environment not in allowed:
        return PolicyVerdict(
            policy="environment_allowed",
            result=PolicyResult.DENY,
            reason=f"Ambiente '{environment}' não permitido",
        )
    return PolicyVerdict(policy="environment_allowed", result=PolicyResult.ALLOW)


def policy_maintenance_window(**kwargs) -> PolicyVerdict:
    """Verifica se há janela de manutencão ativa (placeholder)."""
    return PolicyVerdict(policy="maintenance_window", result=PolicyResult.ALLOW)


def policy_concurrent_operation(**kwargs) -> PolicyVerdict:
    """Verifica se há operacão concorrente no mesmo recurso (placeholder)."""
    return PolicyVerdict(policy="concurrent_operation", result=PolicyResult.ALLOW)


def policy_daily_quota(**kwargs) -> PolicyVerdict:
    """Verifica limite diário de execucões (placeholder)."""
    return PolicyVerdict(policy="daily_quota", result=PolicyResult.ALLOW)