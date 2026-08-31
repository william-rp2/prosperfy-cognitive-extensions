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
from .finance_acl import DENY_USER_MESSAGE as FINANCE_DENY_USER_MESSAGE
from .finance_acl import FinanceAcl, FinanceChannelContext

logger = logging.getLogger(__name__)


class PolicyEngine:
    """
    Avalia policy para uma capability dado um ActorContext e um grant.

    Implementa PolicyPort.
    Lógica Sprint 0.1:
    - Sem grant → DENY
    - Grant com policy_override → usa override
    - Sem override → usa default_policy da capability (do YAML)

    F2B: quando um FinanceAcl é injetado, capabilities finance.* passam
    ANTES por uma ACL determinística e fail-closed (PLAN.md D8). A ACL roda
    como PRIMEIRO passo — antes do grant check e, por construção, antes de
    qualquer chamada ao adapter e de qualquer interpretação por LLM.
    """

    def __init__(self, finance_acl: FinanceAcl | None = None) -> None:
        """
        finance_acl: quando None, capabilities finance.* são NEGADAS em
                     bloco (fail-closed) — a ausência de ACL nunca vira
                     permissão. Capabilities não-finance seguem exatamente
                     o comportamento pré-F2B (só grants), com ou sem ACL.
                     A wiring de produção DEVE injetar um FinanceAcl — ver
                     policy/finance_acl.py. Um FinanceAcl sem configuração
                     também nega tudo em finance.*, então injetá-lo nunca
                     abre acesso por acidente.
        """
        self._finance_acl = finance_acl

    async def evaluate(
        self,
        ctx: ActorContext,
        capability: RegisteredCapability,
        params: dict,
        grant: CapabilityGrant | None = None,
        *,
        channel: FinanceChannelContext | None = None,
    ) -> PolicyVerdict:
        """
        Avalia a policy e retorna um PolicyVerdict.

        Args:
            ctx:        ActorContext imutável do request.
            capability: Capability registrada (lida do YAML).
            params:     Parâmetros do request (usados por regras específicas).
            grant:      Grant resolvido do registry. None → sem autorização.
            channel:    Contexto de canal do transporte (WhatsApp). Metadado
                        de envelope, nunca texto de prompt. Obrigatório para
                        finance.* quando a ACL está ativa — ausência é DENY.
        """
        # 0. Guard de finance — pré-LLM, pré-grant, pré-adapter, fail-closed.
        #    `params` NÃO é passado adiante: a decisão não depende, e não
        #    pode depender, de nada interpretado a partir da mensagem.
        #
        #    O guard é ESPECÍFICO de finance: capabilities não-finance nem
        #    entram neste bloco e mantêm exatamente o comportamento pré-F2B,
        #    com ou sem ACL injetada.
        if FinanceAcl.applies_to(capability.id):
            if self._finance_acl is None:
                # Finance sem ACL configurada não pode "passar por omissão":
                # ausência de configuração é ausência de autorização.
                logger.error(
                    "DENY [finance_guard:acl_absent] tenant=%s cap=%s",
                    ctx.tenant_id, capability.id,
                )
                return PolicyVerdict(
                    decision=PolicyDecision.DENY,
                    reason=FINANCE_DENY_USER_MESSAGE,
                    policy_name="finance_guard:acl_absent",
                )
            acl_verdict = self._finance_acl.evaluate(ctx, capability.id, channel)
            if acl_verdict is None or acl_verdict.decision is PolicyDecision.DENY:
                # `None` aqui seria a ACL declarando que não se aplica a uma
                # capability que o guard classificou como finance: estado
                # incoerente -> fail-closed, nunca ALLOW.
                return acl_verdict or PolicyVerdict(
                    decision=PolicyDecision.DENY,
                    reason=FINANCE_DENY_USER_MESSAGE,
                    policy_name="finance_guard:no_verdict",
                )

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
