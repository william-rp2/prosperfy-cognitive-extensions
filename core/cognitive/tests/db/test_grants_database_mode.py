"""
tests/db/test_grants_database_mode.py — FIX Sprint 0.3 RETURN_TO_DEV (Item A).

Prova CONTRA UM POSTGRES REAL que a resolução de grants em database mode
consulta capability_grants com RLS de verdade (não a lista in-memory):

  - grant persistido → resolvido (ALLOW no fluxo real do PolicyEngine)
  - sem grant → None (DENY)
  - profile incorreto → None
  - capability diferente → None
  - grant de OUTRO tenant → NÃO É VISÍVEL (RLS tenant_isolation) mesmo
    existindo a linha para o outro tenant
  - grant inativo (active=false) → None
  - policy_override persistido é devolvido no grant
  - list_for_tenant_profile respeita o mesmo isolamento

DB real obrigatório: tests/db/conftest.py aplica skipif quando não há alvo
(COGNITIVE_DB_* remote homolog ou testcontainers). Roda apenas com
VPS_REQUIRED (gap do trabalho — esta máquina não tem Postgres).
"""

from __future__ import annotations

import pytest_asyncio

from cognitive.db.repositories.tenancy_repo import GrantRepository
from cognitive.registry.grant_resolver import PostgresGrantResolver


@pytest_asyncio.fixture
async def grant_rows(admin_conn, seeded_tenants):
    """Seeds idempotente de grants via admin (BYPASSRLS):
    - tenant-a owner-core → infra.inspect (ativo)
    - tenant-a owner-core → finance.report (INATIVO)
    - tenant-b infra-read   → infra.inspect com policy_override=confirm
    - tenant-b owner-core   → SEM grant (isolação: quem tem o de infra.inspect é o A)
    """
    tenant_a = seeded_tenants["tenant-a"]
    tenant_b = seeded_tenants["tenant-b"]
    await admin_conn.execute(
        "INSERT INTO capability_grants(tenant_id, profile, capability_id) "
        "VALUES($1, 'owner-core', 'infra.inspect')",
        tenant_a,
    )
    await admin_conn.execute(
        "INSERT INTO capability_grants(tenant_id, profile, capability_id, active) "
        "VALUES($1, 'owner-core', 'finance.report', false)",
        tenant_a,
    )
    await admin_conn.execute(
        "INSERT INTO capability_grants(tenant_id, profile, capability_id, policy_override) "
        "VALUES($1, 'infra-read', 'infra.inspect', 'confirm')",
        tenant_b,
    )
    yield {"tenant-a": tenant_a, "tenant-b": tenant_b}
    await admin_conn.execute(
        "DELETE FROM capability_grants WHERE tenant_id = ANY($1::uuid[])",
        [tenant_a, tenant_b],
    )


class TestPostgresGrantResolverDatabaseMode:
    @pytest_asyncio.fixture
    async def resolver(self, db_pools):
        return PostgresGrantResolver(repo=GrantRepository())

    async def test_valid_grant_permitted(self, resolver, grant_rows):
        grant = await resolver.resolve_grant(
            grant_rows["tenant-a"], "owner-core", "infra.inspect",
        )
        assert grant is not None
        assert grant.tenant_id == grant_rows["tenant-a"]
        assert grant.capability_id == "infra.inspect"
        assert grant.policy_override is None

    async def test_policy_override_persisted_is_returned(self, resolver, grant_rows):
        grant = await resolver.resolve_grant(
            grant_rows["tenant-b"], "infra-read", "infra.inspect",
        )
        assert grant is not None
        assert grant.policy_override == "confirm"

    async def test_no_grant_denied(self, resolver, grant_rows):
        assert await resolver.resolve_grant(
            grant_rows["tenant-a"], "observer", "infra.inspect",
        ) is None

    async def test_wrong_profile_denied(self, resolver, grant_rows):
        owner = await resolver.resolve_grant(
            grant_rows["tenant-a"], "owner-core", "infra.inspect",
        )
        assert owner is not None
        # Mesmo tenant/capability, profile errado → sem grant.
        assert await resolver.resolve_grant(
            grant_rows["tenant-a"], "viewer", "infra.inspect",
        ) is None

    async def test_wrong_capability_denied(self, resolver, grant_rows):
        assert await resolver.resolve_grant(
            grant_rows["tenant-a"], "owner-core", "nonexistent.capability",
        ) is None

    async def test_other_tenant_grant_not_leaked_by_rls(self, resolver, grant_rows):
        """tenant-a TEM o grant de infra.inspect; tenant-b NÃO. A RLS
        tenant_isolation garante que a linha de tenant-a é invisível quando o
        contexto é tenant-b (mesmo com WHERE igual)."""
        assert await resolver.resolve_grant(
            grant_rows["tenant-b"], "owner-core", "infra.inspect",
        ) is None

    async def test_reverse_direction_isolation(self, resolver, grant_rows):
        """tenant-b TEM grant infra-read de infra.inspect; tenant-a não vê."""
        assert await resolver.resolve_grant(
            grant_rows["tenant-a"], "infra-read", "infra.inspect",
        ) is None

    async def test_inactive_grant_denied(self, resolver, grant_rows):
        assert await resolver.resolve_grant(
            grant_rows["tenant-a"], "owner-core", "finance.report",
        ) is None

    async def test_list_for_tenant_profile_scoped_by_rls(self, resolver, grant_rows):
        grants = await resolver.list_for_tenant_profile(
            grant_rows["tenant-a"], "owner-core",
        )
        caps = {g.capability_id for g in grants}
        assert caps == {"infra.inspect"}  # finance.report inativo excluído

        other = await resolver.list_for_tenant_profile(
            grant_rows["tenant-b"], "owner-core",
        )
        assert other == []  # tenant-b não tem grant owner-core (invisível)