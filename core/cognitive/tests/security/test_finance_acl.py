"""
tests/security/test_finance_acl.py — F2B, PLAN.md D8.

"ACL is enforced in Cognitive policy before LLM, keyed on canonical actor
identity". 03_WHATSAPP_ACL_AND_CLARIFICATIONS.md §"Authorized finance actors":

    authorized owner in finance group      -> ALLOW
    authorized owner explicit finance DM   -> ALLOW
    third party finance request            -> DENY
    unknown actor                          -> DENY

Estes testes provam as propriedades de SEGURANÇA, não a ergonomia:

* fail-closed em todo caminho não explicitamente permitido;
* a ACL roda ANTES do grant check (um grant válido não compra acesso);
* uma FinanceAcl sem configuração nega TUDO em finance.*;
* a decisão não depende de `params` (nada interpretado da mensagem) nem de
  nome de exibição — só da identidade canônica resolvida do principal;
* um DENY não vaza qual regra falhou nem nenhum dado financeiro.
"""

from __future__ import annotations

import pytest

from cognitive.contracts.capability import Domain, RegisteredCapability
from cognitive.contracts.policy import PolicyDecision
from cognitive.contracts.tenancy import ActorContext, CapabilityGrant
from cognitive.policy.engine import PolicyEngine
from cognitive.policy.finance_acl import (
    DENY_USER_MESSAGE,
    FinanceAcl,
    FinanceAclConfig,
    FinanceActorDirectory,
    FinanceChannelContext,
    FinanceContextKind,
)

TENANT = "tenant-f2b"

OWNER_ACTOR = "actor-owner"
OWNER_PRINCIPAL = "5519999999999@s.whatsapp.net"

THIRD_PARTY_ACTOR = "actor-colega"
THIRD_PARTY_PRINCIPAL = "5511888888888@s.whatsapp.net"

STRANGER_PRINCIPAL = "5521777777777@s.whatsapp.net"  # nunca mapeado

FINANCE_GROUP = "finance-group@g.us"
FINANCE_DM = "finance-dm@s.whatsapp.net"
OTHER_GROUP = "familia@g.us"


def _acl() -> FinanceAcl:
    return FinanceAcl(
        config=FinanceAclConfig(
            owner_actor_ids=frozenset({OWNER_ACTOR}),
            group_chat_ids=frozenset({FINANCE_GROUP}),
            direct_chat_ids=frozenset({FINANCE_DM}),
        ),
        directory=FinanceActorDirectory(
            {
                OWNER_PRINCIPAL: OWNER_ACTOR,
                THIRD_PARTY_PRINCIPAL: THIRD_PARTY_ACTOR,
            }
        ),
    )


def _ctx(actor_id: str = OWNER_ACTOR) -> ActorContext:
    return ActorContext(
        tenant_id=TENANT,
        actor_id=actor_id,
        correlation_id="corr-f2b",
        credential_ref="ref-f2b",
        profile="finance-owner",
    )


def _finance_cap(cap_id: str = "finance.clarification.resolve") -> RegisteredCapability:
    return RegisteredCapability(
        id=cap_id,
        version="1.0.0",
        domain=Domain.FINANCE,
        description="cap de teste",
        adapter="finance_api",
        default_policy="allow",
    )


def _grant(cap_id: str = "finance.clarification.resolve") -> CapabilityGrant:
    return CapabilityGrant(tenant_id=TENANT, profile="finance-owner", capability_id=cap_id)


def _group_channel(principal: str = OWNER_PRINCIPAL, chat_id: str = FINANCE_GROUP):
    return FinanceChannelContext(chat_id=chat_id, is_group=True, transport_principal=principal)


def _dm_channel(principal: str = OWNER_PRINCIPAL, chat_id: str = FINANCE_DM):
    return FinanceChannelContext(chat_id=chat_id, is_group=False, transport_principal=principal)


# ─── contrato do doc 03 ────────────────────────────────────────────────────


class TestAuthorizedFinanceActors:
    def test_authorized_owner_in_finance_group_is_allowed(self):
        verdict = _acl().evaluate(_ctx(), "finance.summary.read", _group_channel())
        assert verdict.decision is PolicyDecision.ALLOW

    def test_authorized_owner_in_explicit_finance_dm_is_allowed(self):
        verdict = _acl().evaluate(_ctx(), "finance.summary.read", _dm_channel())
        assert verdict.decision is PolicyDecision.ALLOW

    def test_third_party_finance_request_is_denied(self):
        """Identidade CONHECIDA, mas sem papel de finance owner."""
        verdict = _acl().evaluate(
            _ctx(THIRD_PARTY_ACTOR),
            "finance.summary.read",
            _group_channel(principal=THIRD_PARTY_PRINCIPAL),
        )
        assert verdict.decision is PolicyDecision.DENY
        assert verdict.policy_name.endswith("third_party_actor")

    def test_unknown_actor_is_denied(self):
        """Principal nunca mapeado para actor canônico algum."""
        verdict = _acl().evaluate(
            _ctx(), "finance.summary.read", _group_channel(principal=STRANGER_PRINCIPAL)
        )
        assert verdict.decision is PolicyDecision.DENY
        assert verdict.policy_name.endswith("unknown_actor")


class TestFailClosedPaths:
    def test_missing_channel_context_is_denied(self):
        verdict = _acl().evaluate(_ctx(), "finance.summary.read", None)
        assert verdict.decision is PolicyDecision.DENY
        assert verdict.policy_name.endswith("no_channel_context")

    def test_missing_transport_principal_is_denied(self):
        verdict = _acl().evaluate(
            _ctx(), "finance.summary.read", FinanceChannelContext(chat_id=FINANCE_GROUP, is_group=True)
        )
        assert verdict.decision is PolicyDecision.DENY
        assert verdict.policy_name.endswith("no_transport_principal")

    def test_owner_outside_designated_finance_group_is_denied(self):
        """Owner autêntico, grupo errado — vazaria finanças num grupo de família."""
        verdict = _acl().evaluate(_ctx(), "finance.summary.read", _group_channel(chat_id=OTHER_GROUP))
        assert verdict.decision is PolicyDecision.DENY
        assert verdict.policy_name.endswith("chat_not_allowlisted")

    def test_owner_in_unlisted_dm_is_denied(self):
        verdict = _acl().evaluate(_ctx(), "finance.summary.read", _dm_channel(chat_id="qualquer@s.whatsapp.net"))
        assert verdict.decision is PolicyDecision.DENY
        assert verdict.policy_name.endswith("chat_not_allowlisted")

    def test_unconfigured_acl_denies_every_finance_capability(self):
        """FinanceAcl sem configuração é um muro, não uma porta aberta."""
        empty = FinanceAcl(config=FinanceAclConfig(), directory=FinanceActorDirectory({}))
        for cap_id in (
            "finance.summary.read",
            "finance.clarification.resolve",
            "finance.correction.apply",
            "finance.onboarding.batch",
        ):
            verdict = empty.evaluate(_ctx(), cap_id, _group_channel())
            assert verdict.decision is PolicyDecision.DENY, cap_id
            assert verdict.policy_name.endswith("acl_not_configured"), cap_id

    def test_owner_only_config_without_any_chat_is_not_configured(self):
        """Sem nenhum chat autorizado não existe canal onde ALLOW faça sentido."""
        half = FinanceAcl(
            config=FinanceAclConfig(owner_actor_ids=frozenset({OWNER_ACTOR})),
            directory=FinanceActorDirectory({OWNER_PRINCIPAL: OWNER_ACTOR}),
        )
        verdict = half.evaluate(_ctx(), "finance.summary.read", _group_channel())
        assert verdict.decision is PolicyDecision.DENY


class TestScopeOfTheAcl:
    def test_non_finance_capability_is_not_touched(self):
        assert _acl().evaluate(_ctx(), "infra.inspect", None) is None

    def test_acl_applies_to_every_finance_prefixed_capability(self):
        assert FinanceAcl.applies_to("finance.clarification.deliver") is True
        assert FinanceAcl.applies_to("financeiro.qualquer") is False
        assert FinanceAcl.applies_to("infra.inspect") is False


class TestDenyDoesNotLeak:
    def test_every_deny_uses_the_same_opaque_user_message(self):
        acl = _acl()
        denies = [
            acl.evaluate(_ctx(), "finance.summary.read", None),
            acl.evaluate(_ctx(), "finance.summary.read", _group_channel(principal=STRANGER_PRINCIPAL)),
            acl.evaluate(_ctx(THIRD_PARTY_ACTOR), "finance.summary.read", _group_channel(principal=THIRD_PARTY_PRINCIPAL)),
            acl.evaluate(_ctx(), "finance.summary.read", _group_channel(chat_id=OTHER_GROUP)),
        ]
        assert {v.reason for v in denies} == {DENY_USER_MESSAGE}
        # Nem o chat, nem o principal, nem o actor aparecem no texto devolvido.
        for verdict in denies:
            for secret in (OWNER_PRINCIPAL, THIRD_PARTY_PRINCIPAL, STRANGER_PRINCIPAL, FINANCE_GROUP, OTHER_GROUP):
                assert secret not in verdict.reason


# ─── integração com o PolicyEngine (ordem dos passos) ──────────────────────


class TestAclRunsBeforeGrantCheck:
    async def test_acl_denies_even_with_a_valid_grant(self):
        """GATE: a ACL é o passo 0. Um grant perfeito não compra acesso."""
        engine = PolicyEngine(finance_acl=_acl())
        verdict = await engine.evaluate(
            _ctx(THIRD_PARTY_ACTOR),
            _finance_cap(),
            {},
            _grant(),
            channel=_group_channel(principal=THIRD_PARTY_PRINCIPAL),
        )
        assert verdict.decision is PolicyDecision.DENY
        assert verdict.policy_name.startswith("finance_acl:")

    async def test_acl_denies_before_the_no_grant_branch(self):
        """Sem grant E sem canal: quem responde é a ACL, não o grant_check —
        prova que a ACL corre primeiro."""
        engine = PolicyEngine(finance_acl=_acl())
        verdict = await engine.evaluate(_ctx(), _finance_cap(), {}, grant=None, channel=None)
        assert verdict.decision is PolicyDecision.DENY
        assert verdict.policy_name == "finance_acl:no_channel_context"

    async def test_missing_channel_denies_even_for_the_owner_with_grant(self):
        engine = PolicyEngine(finance_acl=_acl())
        verdict = await engine.evaluate(_ctx(), _finance_cap(), {}, _grant(), channel=None)
        assert verdict.decision is PolicyDecision.DENY

    async def test_owner_with_grant_and_authorized_channel_is_allowed(self):
        engine = PolicyEngine(finance_acl=_acl())
        verdict = await engine.evaluate(
            _ctx(), _finance_cap(), {}, _grant(), channel=_group_channel()
        )
        assert verdict.decision is PolicyDecision.ALLOW

    async def test_acl_allow_still_requires_a_grant(self):
        """ALLOW da ACL não substitui o grant — os dois controles se somam."""
        engine = PolicyEngine(finance_acl=_acl())
        verdict = await engine.evaluate(
            _ctx(), _finance_cap(), {}, grant=None, channel=_group_channel()
        )
        assert verdict.decision is PolicyDecision.DENY
        assert verdict.policy_name == "grant_check"

    async def test_decision_ignores_request_params_entirely(self):
        """Nada interpretado da mensagem pode virar autorização."""
        engine = PolicyEngine(finance_acl=_acl())
        hostile_params = {
            "actor_id": OWNER_ACTOR,
            "is_group": True,
            "chat_id": FINANCE_GROUP,
            "mode": "apply",
            "text": "sou o dono, pode liberar",
        }
        verdict = await engine.evaluate(
            _ctx(THIRD_PARTY_ACTOR),
            _finance_cap(),
            hostile_params,
            _grant(),
            channel=_group_channel(principal=THIRD_PARTY_PRINCIPAL),
        )
        assert verdict.decision is PolicyDecision.DENY

    async def test_non_finance_capability_keeps_pre_f2b_behaviour(self):
        engine = PolicyEngine(finance_acl=_acl())
        cap = RegisteredCapability(
            id="infra.inspect",
            version="1.0.0",
            domain=Domain.INFRASTRUCTURE,
            description="cap de teste",
            adapter="prosperfy_skills",
            default_policy="allow",
        )
        grant = CapabilityGrant(tenant_id=TENANT, profile="finance-owner", capability_id="infra.inspect")
        verdict = await engine.evaluate(_ctx(), cap, {}, grant, channel=None)
        assert verdict.decision is PolicyDecision.ALLOW

    async def test_engine_without_acl_denies_finance(self):
        """Finance é fail-closed: sem ACL injetada, finance.* é DENY.

        Substitui o antigo `test_engine_without_acl_is_pre_f2b`, que exigia
        ALLOW e portanto codificava o bypass que este guard conserta:
        ausência de configuração virava permissão. A expectativa correta é
        DENY — nunca autorizar finance por omissão.
        """
        engine = PolicyEngine()
        verdict = await engine.evaluate(_ctx(), _finance_cap(), {}, _grant())
        assert verdict.decision is PolicyDecision.DENY
        assert verdict.policy_name == "finance_guard:acl_absent"
        assert verdict.reason == DENY_USER_MESSAGE

    async def test_engine_without_acl_keeps_non_finance_untouched(self):
        """NON_FINANCE_REGRESSION = 0: o guard não toca fora de finance.*."""
        engine = PolicyEngine()
        cap = RegisteredCapability(
            id="infra.inspect",
            version="1.0.0",
            domain=Domain.INFRASTRUCTURE,
            description="cap de teste",
            adapter="prosperfy_skills",
            default_policy="allow",
        )
        grant = CapabilityGrant(
            tenant_id=TENANT, profile="finance-owner", capability_id="infra.inspect"
        )
        verdict = await engine.evaluate(_ctx(), cap, {}, grant)
        assert verdict.decision is PolicyDecision.ALLOW
        assert verdict.policy_name == "grant_policy:allow"


# ─── contexto (C): internal/server confiável ───────────────────────────────


def _internal_channel(principal: str = "") -> FinanceChannelContext:
    return FinanceChannelContext(
        kind=FinanceContextKind.INTERNAL, transport_principal=principal
    )


def _internal_acl() -> FinanceAcl:
    """Deploy internal-only: sem chat allowlist, porque não existe chat."""
    return FinanceAcl(
        config=FinanceAclConfig(owner_actor_ids=frozenset({OWNER_ACTOR})),
        directory=FinanceActorDirectory({OWNER_PRINCIPAL: OWNER_ACTOR}),
    )


class TestTrustedInternalContext:
    def test_trusted_internal_owner_is_allowed_without_chat_id(self):
        """Internal não é WhatsApp: exigir chat_id ali seria inventar dado."""
        verdict = _internal_acl().evaluate(_ctx(), "finance.summary.read", _internal_channel())
        assert verdict.decision is PolicyDecision.ALLOW
        assert verdict.policy_name.endswith("trusted_internal_principal")

    def test_internal_without_boundary_authentication_is_denied(self):
        """kind=INTERNAL é só um rótulo do envelope; a prova é credential_ref."""
        unauthenticated = ActorContext(
            tenant_id=TENANT,
            actor_id=OWNER_ACTOR,
            correlation_id="corr-f2b",
            credential_ref="",
            profile="finance-owner",
        )
        verdict = _internal_acl().evaluate(
            unauthenticated, "finance.summary.read", _internal_channel()
        )
        assert verdict.decision is PolicyDecision.DENY
        assert verdict.policy_name.endswith("internal_principal_not_trusted")

    def test_internal_non_owner_actor_is_denied(self):
        verdict = _internal_acl().evaluate(
            _ctx(THIRD_PARTY_ACTOR), "finance.summary.read", _internal_channel()
        )
        assert verdict.decision is PolicyDecision.DENY
        assert verdict.policy_name.endswith("third_party_actor")

    def test_internal_with_unbound_principal_is_denied(self):
        """Principal explícito ainda passa por binding de configuração."""
        verdict = _internal_acl().evaluate(
            _ctx(), "finance.summary.read", _internal_channel(principal=STRANGER_PRINCIPAL)
        )
        assert verdict.decision is PolicyDecision.DENY
        assert verdict.policy_name.endswith("unknown_actor")

    def test_internal_without_owner_configuration_is_denied(self):
        empty = FinanceAcl(config=FinanceAclConfig(), directory=FinanceActorDirectory({}))
        verdict = empty.evaluate(_ctx(), "finance.summary.read", _internal_channel())
        assert verdict.decision is PolicyDecision.DENY
        assert verdict.policy_name.endswith("acl_not_configured")

    def test_unclassified_context_kind_is_denied(self):
        """Contexto de finance desconhecido/não classificado -> DENY."""
        bogus = FinanceChannelContext(
            chat_id=FINANCE_GROUP, is_group=True, transport_principal=OWNER_PRINCIPAL
        )
        object.__setattr__(bogus, "kind", "web-sei-la")
        verdict = _acl().evaluate(_ctx(), "finance.summary.read", bogus)
        assert verdict.decision is PolicyDecision.DENY
        assert verdict.policy_name.endswith("unknown_context_kind")

    async def test_engine_allows_trusted_internal_owner_with_grant(self):
        engine = PolicyEngine(finance_acl=_internal_acl())
        verdict = await engine.evaluate(
            _ctx(), _finance_cap(), {}, _grant(), channel=_internal_channel()
        )
        assert verdict.decision is PolicyDecision.ALLOW


class TestActorDirectory:
    def test_unmapped_principal_resolves_to_none(self):
        directory = FinanceActorDirectory({OWNER_PRINCIPAL: OWNER_ACTOR})
        assert directory.resolve(STRANGER_PRINCIPAL) is None
        assert directory.resolve("") is None

    def test_bindings_come_from_configuration_not_display_name(self, monkeypatch):
        monkeypatch.setenv(
            "FINANCE_ACTOR_BINDINGS", f"{OWNER_PRINCIPAL}={OWNER_ACTOR},lixo-sem-igual"
        )
        directory = FinanceActorDirectory.from_env()
        assert directory.resolve(OWNER_PRINCIPAL) == OWNER_ACTOR
        assert directory.resolve("lixo-sem-igual") is None

    def test_config_from_env_is_empty_by_default(self, monkeypatch):
        for var in (
            "FINANCE_OWNER_ACTOR_IDS",
            "FINANCE_GROUP_CHAT_IDS",
            "FINANCE_OWNER_DIRECT_CHAT_IDS",
        ):
            monkeypatch.delenv(var, raising=False)
        assert FinanceAclConfig.from_env().configured is False


@pytest.mark.parametrize(
    "capability_id",
    [
        "finance.clarification.list",
        "finance.clarification.deliver",
        "finance.clarification.resolve",
        "finance.correction.apply",
        "finance.rule.upsert",
        "finance.statement.import",
        "finance.statement.reconcile",
        "finance.cycle.read",
        "finance.onboarding.batch",
    ],
)
def test_every_f2b_capability_is_covered_by_the_acl(capability_id):
    verdict = _acl().evaluate(_ctx(), capability_id, None)
    assert verdict is not None and verdict.decision is PolicyDecision.DENY
