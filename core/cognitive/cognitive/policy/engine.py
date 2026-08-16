"""
policy/engine.py — PolicyEngine V2 do Cognitive Core.

ADR-V2-004: ALLOW / CONFIRM / DENY.
Ordem: Policy avalia ANTES do adapter — nunca depois.
Portado e adaptado de hermes/capability-intelligence/.../policy_engine.py.
Legado intocado; este módulo usa nomenclatura V2.
"""

from __future__ import annotations

import logging

from ..contracts.capability import RegisteredCapability
from ..contracts.policy import PolicyDecision, PolicyPort, PolicyVerdict
from ..contracts.tenancy import ActorContext, CapabilityGrant

logger = logging.getLogger(__name__)


class PolicyEngine:
    """
    Avalia policy para uma capability dado um ActorContext e um grant.

    Implementa PolicyPort.
    Lógica Sprint 0.1:
    - Sem grant → DENY
    - Grant com policy_override → usa override
    - Sem override → usa default_policy da capability (do YAML)
    """

    async def evaluate(
        self,
        ctx: ActorContext,
        capability: RegisteredCapability,
        params: dict,
        grant: CapabilityGrant | None = None,
    ) -> PolicyVerdict:
        """
        Avalia a policy e retorna um PolicyVerdict.

        Args:
            ctx:        ActorContext imutável do request.
            capability: Capability registrada (lida do YAML).
            params:     Parâmetros do request (usados por regras específicas).
            grant:      Grant resolvido do registry. None → sem autorização.
        """
        # 1. Sem grant → sempre DENY
        if grant is None:
            logger.warning(
                "DENY [no_grant] tenant=%s actor=%s cap=%s",
                ctx.tenant_id, ctx.actor_id, capability.id,
            )
            return PolicyVerdict(
                decision=PolicyDecision.DENY,
                reason=f"Tenant '{ctx.tenant_id}' não possui grant para '{capability.id}'",
                policy_name="grant_check",
            )

        # 2. Validar que o grant pertence ao tenant correto (cross-tenant guard)
        if grant.tenant_id != ctx.tenant_id:
            logger.error(
                "DENY [cross_tenant] grant_tenant=%s ctx_tenant=%s cap=%s",
                grant.tenant_id, ctx.tenant_id, capability.id,
            )
            return PolicyVerdict(
                decision=PolicyDecision.DENY,
                reason="Cross-tenant grant inválido",
                policy_name="cross_tenant_guard",
            )

        # 3. Determinar decisão efetiva
        effective_policy = (grant.policy_override or capability.default_policy).lower()

        decision_map = {
            "allow":   PolicyDecision.ALLOW,
            "confirm": PolicyDecision.CONFIRM,
            "deny":    PolicyDecision.DENY,
        }
        decision = decision_map.get(effective_policy, PolicyDecision.DENY)

        logger.info(
            "%s [policy=%s] tenant=%s actor=%s cap=%s",
            decision.value.upper(), effective_policy,
            ctx.tenant_id, ctx.actor_id, capability.id,
        )

        reason_map = {
            PolicyDecision.ALLOW:   "Capability autorizada",
            PolicyDecision.CONFIRM: "Capability requer confirmação explícita antes de executar",
            PolicyDecision.DENY:    "Capability negada por policy",
        }

        return PolicyVerdict(
            decision=decision,
            reason=reason_map[decision],
            policy_name=f"grant_policy:{effective_policy}",
        )
