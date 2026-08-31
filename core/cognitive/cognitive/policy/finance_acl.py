"""
policy/finance_acl.py — ACL determinística e fail-closed do domínio finance.

PLAN.md D8: "ACL is enforced in Cognitive policy before LLM, keyed on
canonical actor identity". 03_WHATSAPP_ACL_AND_CLARIFICATIONS.md
§"Authorized finance actors":

    authorized owner in finance group      -> ALLOW
    authorized owner explicit finance DM   -> ALLOW
    third party finance request            -> DENY
    unknown actor                          -> DENY

Invariantes que este módulo garante:

1. A decisão é tomada ANTES de qualquer interpretação por LLM e antes de
   qualquer chamada ao adapter — PolicyEngine.evaluate roda antes do
   adapter por contrato (ADR-V2-004) e chama esta ACL como PRIMEIRO passo
   para capabilities finance.*, antes até do grant check.
2. Autorização NUNCA depende de nome de exibição. O principal de transporte
   (ex.: JID do WhatsApp) é traduzido para um actor canônico por
   FinanceActorDirectory, que é dado de configuração/identidade.
3. O identificador do grupo financeiro e dos DMs autorizados é dado de
   CONFIGURAÇÃO (env/resource), jamais texto de prompt.
4. Fail-closed em todo caminho não explicitamente permitido: canal ausente,
   principal ausente, principal não mapeado, actor não-owner, chat fora das
   allowlists — tudo DENY.
5. Um DENY não vaza payload: PolicyVerdict.reason é texto fixo em pt-BR sem
   nenhum dado financeiro, e nenhum parâmetro do request é logado aqui.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from enum import Enum

from ..contracts.policy import PolicyDecision, PolicyVerdict
from ..contracts.tenancy import ActorContext

logger = logging.getLogger(__name__)

FINANCE_CAPABILITY_PREFIX = "finance."

# Motivos internos (enum-like, inglês) -> mensagem ao usuário (pt-BR).
# A mensagem é deliberadamente idêntica para todos os DENY: um terceiro não
# pode inferir, pela resposta, se o owner existe, se o grupo existe, ou se
# há qualquer dado financeiro. Zero vazamento por canal lateral.
DENY_USER_MESSAGE = "Acesso financeiro não autorizado para este contato/conversa."

DENY_NO_CHANNEL = "no_channel_context"
DENY_NO_PRINCIPAL = "no_transport_principal"
DENY_UNKNOWN_ACTOR = "unknown_actor"
DENY_THIRD_PARTY = "third_party_actor"
DENY_CHAT_NOT_ALLOWED = "chat_not_allowlisted"
DENY_NOT_CONFIGURED = "acl_not_configured"
DENY_UNTRUSTED_INTERNAL = "internal_principal_not_trusted"
DENY_UNKNOWN_CONTEXT = "unknown_context_kind"

ALLOW_GROUP = "owner_in_finance_group"
ALLOW_DM = "owner_in_finance_dm"
ALLOW_INTERNAL = "trusted_internal_principal"


class FinanceContextKind(str, Enum):
    """Classificação EXPLÍCITA do contexto de origem de um request finance.

    A ACL trata cada contexto com o mecanismo de identidade que é próprio
    dele. Web/internal NÃO é tratado como se fosse WhatsApp: exigir chat_id
    de um principal internal seria pedir um dado que aquela arquitetura não
    tem, e a tentação seria inventar um chat_id sintético — um bypass.

    WHATSAPP: transporte de mensageria. Identidade = principal de transporte
              (JID) traduzido por FinanceActorDirectory; exige allowlist de
              chat (grupo financeiro designado ou DM autorizado do dono).
    INTERNAL: caller server-side/interno JÁ AUTENTICADO pela boundary
              apropriada (Bearer credential -> IdentityResolver, que
              preenche ActorContext.credential_ref). Identidade = actor
              canônico do próprio ActorContext; NÃO exige chat_id.

    Qualquer outro valor (contexto desconhecido/não classificado) -> DENY.
    """

    WHATSAPP = "whatsapp"
    INTERNAL = "internal"


def _fingerprint(value: str) -> str:
    """Identificador curto e estável para log — nunca o valor cru.

    Principal de transporte (telefone/JID) é dado pessoal; chat_id de grupo
    é configuração. Nenhum dos dois vai para o log em claro.
    """
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def _split_env(name: str) -> frozenset[str]:
    raw = os.getenv(name, "")
    return frozenset(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class FinanceChannelContext:
    """Contexto de canal do request, resolvido pelo transporte (WhatsApp).

    NUNCA vem do body interpretado por LLM nem do texto da mensagem: é
    metadado do envelope de transporte (ver ContextEnvelope no Hermes:
    channel_id / user_id / incoming_message_id / reply_to_message_id).
    """

    chat_id: str = ""
    is_group: bool = False
    transport_principal: str = ""  # ex.: JID/telefone do remetente
    incoming_message_id: str = ""
    reply_to_message_id: str = ""
    kind: FinanceContextKind = FinanceContextKind.WHATSAPP


class FinanceActorDirectory:
    """Traduz principal de transporte -> actor canônico.

    Mesmo espírito do IdentityResolver.register_static: binding explícito,
    dado de configuração. Não existe caminho por nome de exibição.
    """

    def __init__(self, bindings: dict[str, str] | None = None) -> None:
        self._bindings: dict[str, str] = dict(bindings or {})

    def register(self, transport_principal: str, actor_id: str) -> None:
        self._bindings[transport_principal] = actor_id

    def resolve(self, transport_principal: str) -> str | None:
        """Retorna o actor canônico, ou None quando o principal é desconhecido."""
        if not transport_principal:
            return None
        return self._bindings.get(transport_principal)

    @classmethod
    def from_env(cls, var: str = "FINANCE_ACTOR_BINDINGS") -> "FinanceActorDirectory":
        """FINANCE_ACTOR_BINDINGS=<principal>=<actor_id>,<principal>=<actor_id>"""
        bindings: dict[str, str] = {}
        for pair in os.getenv(var, "").split(","):
            pair = pair.strip()
            if not pair or "=" not in pair:
                continue
            principal, actor_id = pair.split("=", 1)
            principal, actor_id = principal.strip(), actor_id.strip()
            if principal and actor_id:
                bindings[principal] = actor_id
        return cls(bindings)


@dataclass(frozen=True)
class FinanceAclConfig:
    """Allowlists — dado de configuração, nunca prompt.

    owner_actor_ids:  actors canônicos com papel de finance owner.
    group_chat_ids:   grupos financeiros designados.
    direct_chat_ids:  DMs de finanças explicitamente autorizados.

    Config vazia => tudo DENY (fail-closed por construção).
    """

    owner_actor_ids: frozenset[str] = field(default_factory=frozenset)
    group_chat_ids: frozenset[str] = field(default_factory=frozenset)
    direct_chat_ids: frozenset[str] = field(default_factory=frozenset)

    @property
    def configured(self) -> bool:
        """Config suficiente para autorizar no transporte WhatsApp."""
        return bool(self.owner_actor_ids) and bool(self.group_chat_ids or self.direct_chat_ids)

    @property
    def configured_for_internal(self) -> bool:
        """Config suficiente para autorizar um principal internal confiável.

        Não exige chat allowlist: naquele contexto não existe chat. Exige o
        binding de identidade do dono — sem ele, nada é autorizável.
        """
        return bool(self.owner_actor_ids)

    @classmethod
    def from_env(cls) -> "FinanceAclConfig":
        return cls(
            owner_actor_ids=_split_env("FINANCE_OWNER_ACTOR_IDS"),
            group_chat_ids=_split_env("FINANCE_GROUP_CHAT_IDS"),
            direct_chat_ids=_split_env("FINANCE_OWNER_DIRECT_CHAT_IDS"),
        )


class FinanceAcl:
    """ACL pré-LLM, determinística, fail-closed, para capabilities finance.*."""

    def __init__(
        self,
        config: FinanceAclConfig | None = None,
        directory: FinanceActorDirectory | None = None,
    ) -> None:
        self._config = config if config is not None else FinanceAclConfig.from_env()
        self._directory = directory if directory is not None else FinanceActorDirectory.from_env()

    @staticmethod
    def applies_to(capability_id: str) -> bool:
        return capability_id.startswith(FINANCE_CAPABILITY_PREFIX)

    def resolve_actor(self, channel: FinanceChannelContext) -> str | None:
        return self._directory.resolve(channel.transport_principal)

    def evaluate(
        self,
        ctx: ActorContext,
        capability_id: str,
        channel: FinanceChannelContext | None,
    ) -> PolicyVerdict | None:
        """Retorna None quando a ACL não se aplica (capability não-finance).

        Para capabilities finance.*, retorna sempre um veredito explícito:
        ALLOW só nos contextos do contrato; DENY em todo o resto — incluindo
        contexto de finance desconhecido ou não classificado.
        """
        if not self.applies_to(capability_id):
            return None

        # Sem canal nenhum, o contexto é o de transporte por default: cai no
        # ramo WhatsApp e é negado lá por ausência de canal.
        kind = channel.kind if channel is not None else FinanceContextKind.WHATSAPP

        if kind is FinanceContextKind.INTERNAL:
            return self._evaluate_internal(ctx, capability_id, channel)
        if kind is FinanceContextKind.WHATSAPP:
            return self._evaluate_whatsapp(ctx, capability_id, channel)
        # Contexto não classificado (valor fora do enum) -> fail-closed.
        return self._deny(DENY_UNKNOWN_CONTEXT, ctx, capability_id, channel)

    # ---- contexto (A)/(B): grupo de finance e DM do dono no WhatsApp ----

    def _evaluate_whatsapp(
        self,
        ctx: ActorContext,
        capability_id: str,
        channel: FinanceChannelContext | None,
    ) -> PolicyVerdict:
        if not self._config.configured:
            return self._deny(DENY_NOT_CONFIGURED, ctx, capability_id, None)

        if channel is None:
            return self._deny(DENY_NO_CHANNEL, ctx, capability_id, None)

        if not channel.transport_principal:
            return self._deny(DENY_NO_PRINCIPAL, ctx, capability_id, channel)

        actor_id = self._directory.resolve(channel.transport_principal)
        if actor_id is None:
            # Principal nunca visto: actor desconhecido -> DENY.
            return self._deny(DENY_UNKNOWN_ACTOR, ctx, capability_id, channel)

        if actor_id not in self._config.owner_actor_ids:
            # Identidade conhecida, mas não é finance owner -> terceiro.
            return self._deny(DENY_THIRD_PARTY, ctx, capability_id, channel)

        if channel.is_group:
            if channel.chat_id not in self._config.group_chat_ids:
                # Owner autêntico, mas fora do grupo financeiro designado.
                return self._deny(DENY_CHAT_NOT_ALLOWED, ctx, capability_id, channel)
            return self._allow(ALLOW_GROUP, ctx, capability_id, channel, actor_id)

        if channel.chat_id not in self._config.direct_chat_ids:
            return self._deny(DENY_CHAT_NOT_ALLOWED, ctx, capability_id, channel)
        return self._allow(ALLOW_DM, ctx, capability_id, channel, actor_id)

    # ---- contexto (C): principal internal/server confiável ---------------

    def _evaluate_internal(
        self,
        ctx: ActorContext,
        capability_id: str,
        channel: FinanceChannelContext,
    ) -> PolicyVerdict:
        """Caller server-side já autenticado pela boundary — sem chat_id.

        A confiança NÃO é declarada pelo próprio envelope: `kind=INTERNAL`
        apenas diz QUAL mecanismo de identidade aplicar. A prova é
        ActorContext.credential_ref, preenchido só no caminho
        Bearer credential -> IdentityResolver do gateway. Sem essa prova,
        DENY. E mesmo autenticado, o actor precisa estar na allowlist de
        owner (configuração), nunca por nome.
        """
        if not self._config.configured_for_internal:
            return self._deny(DENY_NOT_CONFIGURED, ctx, capability_id, channel)

        if not ctx.credential_ref:
            # Identidade não autenticada por boundary alguma.
            return self._deny(DENY_UNTRUSTED_INTERNAL, ctx, capability_id, channel)

        if channel.transport_principal:
            # Principal explícito ainda passa por binding de configuração.
            actor_id = self._directory.resolve(channel.transport_principal)
        else:
            actor_id = ctx.actor_id

        if not actor_id:
            return self._deny(DENY_UNKNOWN_ACTOR, ctx, capability_id, channel)

        if actor_id not in self._config.owner_actor_ids:
            return self._deny(DENY_THIRD_PARTY, ctx, capability_id, channel)

        return self._allow(ALLOW_INTERNAL, ctx, capability_id, channel, actor_id)

    # ---- internals -----------------------------------------------------

    def _deny(
        self,
        rule: str,
        ctx: ActorContext,
        capability_id: str,
        channel: FinanceChannelContext | None,
    ) -> PolicyVerdict:
        logger.warning(
            "DENY [finance_acl:%s] tenant=%s cap=%s chat=%s principal=%s",
            rule,
            ctx.tenant_id,
            capability_id,
            _fingerprint(channel.chat_id) if channel else "none",
            _fingerprint(channel.transport_principal) if channel else "none",
        )
        return PolicyVerdict(
            decision=PolicyDecision.DENY,
            reason=DENY_USER_MESSAGE,
            policy_name=f"finance_acl:{rule}",
        )

    def _allow(
        self,
        rule: str,
        ctx: ActorContext,
        capability_id: str,
        channel: FinanceChannelContext,
        actor_id: str,
    ) -> PolicyVerdict:
        logger.info(
            "ALLOW [finance_acl:%s] tenant=%s cap=%s actor=%s chat=%s",
            rule, ctx.tenant_id, capability_id, actor_id, _fingerprint(channel.chat_id),
        )
        return PolicyVerdict(
            decision=PolicyDecision.ALLOW,
            reason="Finance owner autorizado neste canal",
            policy_name=f"finance_acl:{rule}",
        )
