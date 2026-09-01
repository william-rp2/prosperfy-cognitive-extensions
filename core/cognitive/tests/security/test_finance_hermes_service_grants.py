"""
tests/security/test_finance_hermes_service_grants.py — F2B Hermes service grants.

Dois planos independentes (ARCHITECTURE DECISION=APPROVED):

1. Service grant: profile real do Hermes homolog (`infra-read`) alcança finance.*
2. FinanceAcl: só owner + canal autorizado executa

SERVICE_GRANT_DOES_NOT_BYPASS_FINANCE_ACL deve ser PASS.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from cognitive.contracts.capability import Domain, RegisteredCapability
from cognitive.contracts.policy import PolicyDecision
from cognitive.contracts.tenancy import ActorContext, CapabilityGrant
from cognitive.policy.engine import PolicyEngine
from cognitive.policy.finance_acl import (
    FinanceAcl,
    FinanceAclConfig,
    FinanceActorDirectory,
    FinanceChannelContext,
)

TENANT = "tenant-f2b-hermes-grants"

OWNER_ACTOR = "actor-owner"
OWNER_PRINCIPAL = "5519999999999@s.whatsapp.net"
THIRD_PARTY_ACTOR = "actor-colega"
THIRD_PARTY_PRINCIPAL = "5511888888888@s.whatsapp.net"
STRANGER_PRINCIPAL = "5521777777777@s.whatsapp.net"

FINANCE_GROUP = "finance-group@g.us"
FINANCE_DM = "finance-dm@s.whatsapp.net"
OTHER_GROUP = "familia@g.us"

HERMES_SERVICE_PROFILE = "infra-read"

F2B_CAPS = (
    "finance.clarification.list",
    "finance.clarification.deliver",
    "finance.clarification.resolve",
    "finance.correction.apply",
    "finance.rule.upsert",
    "finance.onboarding.batch",
    "finance.statement.import",
    "finance.statement.reconcile",
    "finance.cycle.read",
)

MIGRATIONS_DIR = (
    Path(__file__).resolve().parents[3] / "migrations"
)
MIG_008 = MIGRATIONS_DIR / "008_finance_capability_grants.sql"
MIG_009 = MIGRATIONS_DIR / "009_finance_f2b_grants.sql"
MIG_010 = MIGRATIONS_DIR / "010_finance_f2b_hermes_service_grants.sql"


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


def _hermes_ctx(actor_id: str = OWNER_ACTOR) -> ActorContext:
    """ActorContext do service identity Hermes: profile = infra-read."""
    return ActorContext(
        tenant_id=TENANT,
        actor_id=actor_id,
        correlation_id="corr-hermes-grants",
        credential_ref="ref-hermes-service",
        profile=HERMES_SERVICE_PROFILE,
    )


def _cap(cap_id: str = "finance.clarification.list") -> RegisteredCapability:
    return RegisteredCapability(
        id=cap_id,
        version="1.0.0",
        domain=Domain.FINANCE,
        description="cap de teste",
        adapter="finance_api",
        default_policy="allow",
    )


def _infra_read_grant(cap_id: str = "finance.clarification.list") -> CapabilityGrant:
    return CapabilityGrant(
        tenant_id=TENANT,
        profile=HERMES_SERVICE_PROFILE,
        capability_id=cap_id,
    )


def _group(principal: str = OWNER_PRINCIPAL, chat_id: str = FINANCE_GROUP):
    return FinanceChannelContext(
        chat_id=chat_id, is_group=True, transport_principal=principal
    )


def _extract_caps(sql: str) -> list[str]:
    return re.findall(r"\('(finance\.[a-z0-9_.]+)'\)", sql)


# ─── A–F security regression ────────────────────────────────────────────────


class TestHermesServiceGrantWithFinanceAcl:
    async def test_a_owner_channel_with_infra_read_grant_allows(self):
        engine = PolicyEngine(finance_acl=_acl())
        for cap_id in F2B_CAPS:
            verdict = await engine.evaluate(
                _hermes_ctx(),
                _cap(cap_id),
                {},
                _infra_read_grant(cap_id),
                channel=_group(),
            )
            assert verdict.decision is PolicyDecision.ALLOW, cap_id

    async def test_b_third_party_denied_despite_service_grant(self):
        engine = PolicyEngine(finance_acl=_acl())
        verdict = await engine.evaluate(
            _hermes_ctx(THIRD_PARTY_ACTOR),
            _cap(),
            {},
            _infra_read_grant(),
            channel=_group(principal=THIRD_PARTY_PRINCIPAL),
        )
        assert verdict.decision is PolicyDecision.DENY
        assert verdict.policy_name.startswith("finance_acl:")
        # SERVICE_GRANT_DOES_NOT_BYPASS_FINANCE_ACL
        assert "grant_check" not in verdict.policy_name

    async def test_c_wrong_group_denied_despite_service_grant(self):
        engine = PolicyEngine(finance_acl=_acl())
        verdict = await engine.evaluate(
            _hermes_ctx(),
            _cap(),
            {},
            _infra_read_grant(),
            channel=_group(chat_id=OTHER_GROUP),
        )
        assert verdict.decision is PolicyDecision.DENY
        assert verdict.policy_name.endswith("chat_not_allowlisted")

    async def test_d_no_channel_denied_despite_service_grant(self):
        engine = PolicyEngine(finance_acl=_acl())
        verdict = await engine.evaluate(
            _hermes_ctx(), _cap(), {}, _infra_read_grant(), channel=None
        )
        assert verdict.decision is PolicyDecision.DENY
        assert verdict.policy_name.endswith("no_channel_context")

    async def test_e_unknown_principal_denied_despite_service_grant(self):
        engine = PolicyEngine(finance_acl=_acl())
        verdict = await engine.evaluate(
            _hermes_ctx(),
            _cap(),
            {},
            _infra_read_grant(),
            channel=_group(principal=STRANGER_PRINCIPAL),
        )
        assert verdict.decision is PolicyDecision.DENY
        assert verdict.policy_name.endswith("unknown_actor")

    async def test_f_non_finance_behaviour_unchanged(self):
        engine = PolicyEngine(finance_acl=_acl())
        cap = RegisteredCapability(
            id="infra.inspect",
            version="1.0.0",
            domain=Domain.INFRASTRUCTURE,
            description="cap de teste",
            adapter="prosperfy_skills",
            default_policy="allow",
        )
        grant = CapabilityGrant(
            tenant_id=TENANT,
            profile=HERMES_SERVICE_PROFILE,
            capability_id="infra.inspect",
        )
        verdict = await engine.evaluate(_hermes_ctx(), cap, {}, grant, channel=None)
        assert verdict.decision is PolicyDecision.ALLOW

    async def test_acl_allow_still_requires_infra_read_grant(self):
        """Sem grant infra-read → DENY [no_grant] mesmo com ACL ALLOW."""
        engine = PolicyEngine(finance_acl=_acl())
        verdict = await engine.evaluate(
            _hermes_ctx(), _cap(), {}, grant=None, channel=_group()
        )
        assert verdict.decision is PolicyDecision.DENY
        assert verdict.policy_name == "grant_check"


# ─── migration contract (sem DB live) ───────────────────────────────────────


class TestMigration010Contract:
    def test_migration_file_exists_and_targets_infra_read(self):
        assert MIG_010.is_file()
        text = MIG_010.read_text(encoding="utf-8")
        assert "SELECT t.id, 'infra-read', cap.capability_id, NULL" in text
        assert "SERVICE_PROFILE_RENAMING=BACKLOG" in text
        assert "ON CONFLICT" in text and "DO NOTHING" in text
        assert "prosperfy-homolog" in text
        assert "009_finance_f2b_grants.sql" in text
        assert "NÃO rebindar Hermes para finance-owner" in text or "NAO rebindar Hermes para finance-owner" in text

    def test_f2b_grants_count_is_nine(self):
        caps = _extract_caps(MIG_010.read_text(encoding="utf-8"))
        assert len(caps) == 9
        assert set(caps) == set(F2B_CAPS)

    def test_each_required_capability_is_present(self):
        text = MIG_010.read_text(encoding="utf-8")
        for cap in F2B_CAPS:
            assert f"('{cap}')" in text

    def test_migration_008_unchanged(self):
        text = MIG_008.read_text(encoding="utf-8")
        assert "finance.summary.read" in text
        assert "hermes-homolog" in text
        assert "infra-read" in text
        # 008 não contém as 9 F2B
        assert "finance.clarification.list" not in text

    def test_migration_009_unchanged_and_finance_owner_only(self):
        text = MIG_009.read_text(encoding="utf-8")
        assert "finance-owner" in text
        assert set(_extract_caps(text)) == set(F2B_CAPS)
        # 009 deliberadamente NÃO semeia infra-read
        insert_body = text.split("INSERT", 1)[1]
        assert "'infra-read'" not in insert_body
        assert "'finance-owner'" in insert_body

    def test_migration_010_idempotent_sqlite_simulation(self):
        """first apply → 9 grants; second apply → sem duplicação."""
        text = MIG_010.read_text(encoding="utf-8")
        assert "ON CONFLICT (tenant_id, profile, capability_id) DO NOTHING" in text
        caps = _extract_caps(text)
        assert len(caps) == 9

        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE capability_grants ("
            " tenant_id TEXT NOT NULL,"
            " profile TEXT NOT NULL,"
            " capability_id TEXT NOT NULL,"
            " policy_override TEXT,"
            " UNIQUE (tenant_id, profile, capability_id))"
        )

        def apply_once() -> None:
            for cap_id in caps:
                conn.execute(
                    "INSERT INTO capability_grants"
                    " (tenant_id, profile, capability_id, policy_override)"
                    " VALUES (?, 'infra-read', ?, NULL)"
                    " ON CONFLICT (tenant_id, profile, capability_id) DO NOTHING",
                    ("tenant-1", cap_id),
                )

        apply_once()
        count1 = conn.execute(
            "SELECT COUNT(*) FROM capability_grants WHERE profile = 'infra-read'"
        ).fetchone()[0]
        apply_once()
        count2 = conn.execute(
            "SELECT COUNT(*) FROM capability_grants WHERE profile = 'infra-read'"
        ).fetchone()[0]
        stored = {
            r[0]
            for r in conn.execute(
                "SELECT capability_id FROM capability_grants WHERE profile = 'infra-read'"
            )
        }
        assert count1 == 9
        assert count2 == 9
        assert stored == set(F2B_CAPS)
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM capability_grants WHERE profile = 'finance-owner'"
            ).fetchone()[0]
            == 0
        )
