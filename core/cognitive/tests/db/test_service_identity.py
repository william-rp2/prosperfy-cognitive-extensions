"""tests/db/test_service_identity.py — ServiceIdentityRepository + identity resolver DB.

SEC-002: a versão anterior deste arquivo continha
test_app_role_select_is_unrestricted_by_tenant, que DOCUMENTAVA (como
comportamento pretendido) a vulnerabilidade encontrada pelo Gate: SELECT
irrestrito em service_identities para cognitive_app/cognitive_worker.
Substituída pela bateria TestDirectTableAccessLockedDown, que prova o
oposto: nenhuma das duas roles consegue ler a tabela diretamente — o único
acesso é via resolve_service_identity_by_credential_hash.
"""

from __future__ import annotations

import uuid

import pytest

from cognitive.db.repositories.identity_repo import ServiceIdentityRepository, hash_credential
from cognitive.tenancy.identity_resolver import IdentityResolver
from .conftest import db_integration_available, skip_reason

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not db_integration_available(), reason=skip_reason()),
]


@pytest.fixture
async def seeded_identity(admin_conn, seeded_tenants):
    tenant_a_id = seeded_tenants["tenant-a"]
    credential = "gate-test-credential-abc123"
    cred_hash = hash_credential(credential)
    await admin_conn.execute(
        """
        INSERT INTO service_identities(tenant_id, actor_id, credential_hash, profile)
        VALUES($1, 'actor-test', $2, 'owner-core')
        ON CONFLICT (credential_hash) DO NOTHING
        """,
        uuid.UUID(tenant_a_id),
        cred_hash,
    )
    yield credential, tenant_a_id
    await admin_conn.execute(
        "DELETE FROM service_identities WHERE credential_hash = $1", cred_hash
    )


class TestServiceIdentityLookup:
    async def test_lookup_valid_credential(self, db_pools, seeded_identity):
        credential, tenant_a_id = seeded_identity
        repo = ServiceIdentityRepository()
        identity = await repo.lookup(credential)
        assert identity is not None
        assert identity.tenant_id == tenant_a_id

    async def test_lookup_invalid_credential_returns_none(self, db_pools):
        repo = ServiceIdentityRepository()
        assert await repo.lookup("definitely-wrong-credential") is None

    async def test_lookup_result_never_carries_credential_hash(self, db_pools, seeded_identity):
        """SEC-002: o retorno do lookup nunca inclui credential_hash — nem
        como atributo do objeto."""
        credential, _ = seeded_identity
        repo = ServiceIdentityRepository()
        identity = await repo.lookup(credential)
        assert identity is not None
        assert not hasattr(identity, "credential_hash")

    async def test_hash_credential_never_stores_plaintext(self, seeded_identity, admin_conn):
        credential, _ = seeded_identity
        rows = await admin_conn.fetch(
            "SELECT credential_hash FROM service_identities WHERE credential_hash = $1",
            hash_credential(credential),
        )
        assert rows[0]["credential_hash"] != credential


class TestRegisterDeactivateLookupEndToEnd:
    """Fluxo de negócio completo via ServiceIdentityRepository — register()
    e deactivate() usam admin_connection() (bootstrap/CLI), lookup() usa a
    função estreita (runtime). Nunca exercitado fim-a-fim antes."""

    async def test_register_then_lookup_resolves(self, db_pools, seeded_tenants):
        tenant_a_id = seeded_tenants["tenant-a"]
        credential = "e2e-register-lookup-credential"
        repo = ServiceIdentityRepository()
        try:
            registered = await repo.register(tenant_a_id, "actor-e2e", credential)
            assert registered.tenant_id == tenant_a_id

            resolved = await repo.lookup(credential)
            assert resolved is not None
            assert resolved.tenant_id == tenant_a_id
            assert resolved.actor_id == "actor-e2e"
        finally:
            await repo.deactivate(credential)

    async def test_register_then_deactivate_then_lookup_returns_none(
        self, db_pools, seeded_tenants
    ):
        tenant_a_id = seeded_tenants["tenant-a"]
        credential = "e2e-register-deactivate-credential"
        repo = ServiceIdentityRepository()
        await repo.register(tenant_a_id, "actor-e2e-2", credential)
        assert await repo.lookup(credential) is not None

        await repo.deactivate(credential)

        assert await repo.lookup(credential) is None


class TestIdentityResolverDatabaseMode:
    async def test_valid_identity_resolves(self, db_pools, seeded_identity):
        credential, tenant_a_id = seeded_identity
        resolver = IdentityResolver(
            identity_repo=ServiceIdentityRepository(),
            database_mode=True,
        )
        ctx = await resolver.resolve(
            f"Bearer {credential}",
            tenant_a_id,
            "actor-test",
            "corr-1",
        )
        assert ctx.tenant_id == tenant_a_id

    async def test_invalid_credential_denied(self, db_pools):
        resolver = IdentityResolver(
            identity_repo=ServiceIdentityRepository(),
            database_mode=True,
        )
        with pytest.raises(ValueError, match="Credencial inválida"):
            await resolver.resolve(
                "Bearer wrong-token",
                "any-tenant",
                "any-actor",
                None,
            )

    async def test_wrong_tenant_header_denied(self, db_pools, seeded_identity):
        credential, _ = seeded_identity
        resolver = IdentityResolver(
            identity_repo=ServiceIdentityRepository(),
            database_mode=True,
        )
        with pytest.raises(ValueError, match="X-Tenant-Id"):
            await resolver.resolve(
                f"Bearer {credential}",
                "wrong-tenant-id",
                "actor-test",
                None,
            )


class TestLookupLeastPrivilege:
    """SEC-001/SEC-002 (Sprint 0.3): lookup via pool cognitive_app (least
    privilege), sem admin_connection/BYPASSRLS e sem SELECT direto na
    tabela — só a função SECURITY DEFINER estreita."""

    async def test_lookup_updates_last_used_at(self, db_pools, seeded_identity, admin_conn):
        credential, _ = seeded_identity
        repo = ServiceIdentityRepository()
        identity = await repo.lookup(credential)
        assert identity is not None

        row = await admin_conn.fetchrow(
            "SELECT last_used_at FROM service_identities WHERE id = $1",
            uuid.UUID(identity.id),
        )
        assert row["last_used_at"] is not None

    async def test_lookup_only_touches_the_matched_identity(
        self, db_pools, seeded_tenants, admin_conn
    ):
        """last_used_at só muda pra identidade cujo credential_hash bateu —
        nunca pra outras, mesmo de outro tenant."""
        tenant_a_id = seeded_tenants["tenant-a"]
        tenant_b_id = seeded_tenants["tenant-b"]
        cred_a = "touch-scope-a"
        cred_b = "touch-scope-b"
        hash_a, hash_b = hash_credential(cred_a), hash_credential(cred_b)
        await admin_conn.execute(
            """
            INSERT INTO service_identities(tenant_id, actor_id, credential_hash, profile)
            VALUES ($1, 'actor-a', $2, 'owner-core'), ($3, 'actor-b', $4, 'owner-core')
            ON CONFLICT (credential_hash) DO NOTHING
            """,
            uuid.UUID(tenant_a_id), hash_a, uuid.UUID(tenant_b_id), hash_b,
        )
        try:
            repo = ServiceIdentityRepository()
            await repo.lookup(cred_a)

            row_a = await admin_conn.fetchrow(
                "SELECT last_used_at FROM service_identities WHERE credential_hash = $1", hash_a,
            )
            row_b = await admin_conn.fetchrow(
                "SELECT last_used_at FROM service_identities WHERE credential_hash = $1", hash_b,
            )
            assert row_a["last_used_at"] is not None
            assert row_b["last_used_at"] is None
        finally:
            await admin_conn.execute(
                "DELETE FROM service_identities WHERE credential_hash IN ($1, $2)", hash_a, hash_b,
            )

    async def test_app_role_insert_into_other_tenant_denied(
        self, db_pools, seeded_tenants, app_conn
    ):
        """Sem GRANT algum em service_identities para cognitive_app (SEC-002)
        — INSERT direto falha por privilégio, não só por RLS."""
        from .conftest import set_tenant_local

        tenant_a_id = seeded_tenants["tenant-a"]
        tenant_b_id = seeded_tenants["tenant-b"]

        await set_tenant_local(app_conn, tenant_a_id)
        with pytest.raises(Exception):
            await app_conn.execute(
                """
                INSERT INTO service_identities(tenant_id, actor_id, credential_hash, profile)
                VALUES($1, 'cross-tenant-actor', 'cross-tenant-hash-xyz', 'owner-core')
                """,
                uuid.UUID(tenant_b_id),
            )

    async def test_repo_lookup_of_a_hash_prefix_never_matches(self, db_pools, seeded_identity):
        """lookup() sempre hasheia a credencial recebida — um "hash parcial"
        passado como credencial vira, ele mesmo, um hash totalmente
        diferente (efeito avalanche do sha256), então nunca bate. Isso
        prova que nada de texto livre do cliente pode aproximar-se de um
        credential_hash real — não prova, sozinho, a semântica `=` da
        função no banco (ver test_function_uses_exact_equality_not_wildcard
        pra isso)."""
        credential, _ = seeded_identity
        full_hash = hash_credential(credential)
        prefix = full_hash[:10]

        repo = ServiceIdentityRepository()
        assert await repo.lookup(prefix) is None

    async def test_function_uses_exact_equality_not_wildcard(
        self, db_pools, seeded_identity, admin_conn
    ):
        """Chama a função SQL diretamente (bypassando o hashing do Python)
        com um valor no formato de wildcard SQL — prova que a comparação
        interna é `=`, não `LIKE`/`~`, então um % ou _ no input não vira
        curinga."""
        credential, _ = seeded_identity
        full_hash = hash_credential(credential)
        wildcard_attempt = f"{full_hash[:10]}%"

        row = await admin_conn.fetchrow(
            "SELECT * FROM resolve_service_identity_by_credential_hash($1)",
            wildcard_attempt,
        )
        assert row is None


class TestDirectTableAccessLockedDown:
    """SEC-002: prova o oposto do que o teste antigo (removido) documentava.
    cognitive_app e cognitive_worker não conseguem ler service_identities
    por SELECT direto — só pela função estreita."""

    async def test_app_role_cannot_select_service_identities(
        self, db_pools, seeded_tenants, app_conn
    ):
        from .conftest import set_tenant_local

        await set_tenant_local(app_conn, seeded_tenants["tenant-a"])
        with pytest.raises(Exception):
            await app_conn.fetch("SELECT * FROM service_identities")

    async def test_app_role_cannot_select_credential_hash_column(
        self, db_pools, seeded_tenants, app_conn
    ):
        from .conftest import set_tenant_local

        await set_tenant_local(app_conn, seeded_tenants["tenant-a"])
        with pytest.raises(Exception):
            await app_conn.fetch("SELECT credential_hash FROM service_identities")

    async def test_app_role_cannot_update_other_tenant_identity(
        self, db_pools, seeded_tenants, admin_conn, app_conn
    ):
        from .conftest import set_tenant_local

        tenant_b_id = seeded_tenants["tenant-b"]
        cred_hash = hash_credential("lockdown-update-probe")
        await admin_conn.execute(
            """
            INSERT INTO service_identities(tenant_id, actor_id, credential_hash, profile)
            VALUES($1, 'actor-b', $2, 'owner-core')
            ON CONFLICT (credential_hash) DO NOTHING
            """,
            uuid.UUID(tenant_b_id), cred_hash,
        )
        try:
            await set_tenant_local(app_conn, seeded_tenants["tenant-a"])
            with pytest.raises(Exception):
                await app_conn.execute(
                    "UPDATE service_identities SET last_used_at = NOW() WHERE credential_hash = $1",
                    cred_hash,
                )
        finally:
            await admin_conn.execute(
                "DELETE FROM service_identities WHERE credential_hash = $1", cred_hash
            )

    async def test_worker_role_cannot_select_service_identities(
        self, db_pools, seeded_tenants, worker_conn
    ):
        from .conftest import set_tenant_local

        await set_tenant_local(worker_conn, seeded_tenants["tenant-a"])
        with pytest.raises(Exception):
            await worker_conn.fetch("SELECT * FROM service_identities")

    async def test_worker_role_cannot_select_credential_hash_column(
        self, db_pools, seeded_tenants, worker_conn
    ):
        from .conftest import set_tenant_local

        await set_tenant_local(worker_conn, seeded_tenants["tenant-a"])
        with pytest.raises(Exception):
            await worker_conn.fetch("SELECT credential_hash FROM service_identities")

    async def test_app_role_cannot_delete(self, db_pools, seeded_tenants, admin_conn, app_conn):
        from .conftest import set_tenant_local

        tenant_a_id = seeded_tenants["tenant-a"]
        cred_hash = hash_credential("lockdown-delete-probe-app")
        await admin_conn.execute(
            """
            INSERT INTO service_identities(tenant_id, actor_id, credential_hash, profile)
            VALUES($1, 'actor-a', $2, 'owner-core')
            ON CONFLICT (credential_hash) DO NOTHING
            """,
            uuid.UUID(tenant_a_id), cred_hash,
        )
        try:
            await set_tenant_local(app_conn, tenant_a_id)
            with pytest.raises(Exception):
                await app_conn.execute(
                    "DELETE FROM service_identities WHERE credential_hash = $1", cred_hash,
                )
        finally:
            await admin_conn.execute(
                "DELETE FROM service_identities WHERE credential_hash = $1", cred_hash
            )

    async def test_worker_role_cannot_delete(
        self, db_pools, seeded_tenants, admin_conn, worker_conn
    ):
        from .conftest import set_tenant_local

        tenant_a_id = seeded_tenants["tenant-a"]
        cred_hash = hash_credential("lockdown-delete-probe-worker")
        await admin_conn.execute(
            """
            INSERT INTO service_identities(tenant_id, actor_id, credential_hash, profile)
            VALUES($1, 'actor-a', $2, 'owner-core')
            ON CONFLICT (credential_hash) DO NOTHING
            """,
            uuid.UUID(tenant_a_id), cred_hash,
        )
        try:
            await set_tenant_local(worker_conn, tenant_a_id)
            with pytest.raises(Exception):
                await worker_conn.execute(
                    "DELETE FROM service_identities WHERE credential_hash = $1", cred_hash,
                )
        finally:
            await admin_conn.execute(
                "DELETE FROM service_identities WHERE credential_hash = $1", cred_hash
            )


class TestResolveFunctionHardening:
    """Owner, search_path e grants EXECUTE da função SECURITY DEFINER."""

    async def test_function_owner_is_cognitive_admin(self, db_pools, admin_conn):
        row = await admin_conn.fetchrow(
            """
            SELECT pg_get_userbyid(proowner) AS owner
            FROM pg_proc
            WHERE proname = 'resolve_service_identity_by_credential_hash'
            """
        )
        assert row is not None
        assert row["owner"] == "cognitive_admin"

    async def test_function_search_path_is_hardened(self, db_pools, admin_conn):
        row = await admin_conn.fetchrow(
            """
            SELECT proconfig
            FROM pg_proc
            WHERE proname = 'resolve_service_identity_by_credential_hash'
            """
        )
        assert row is not None
        assert row["proconfig"] is not None
        assert any("search_path" in cfg for cfg in row["proconfig"])

    async def test_public_has_no_execute(self, db_pools, admin_conn):
        row = await admin_conn.fetchrow(
            "SELECT has_function_privilege('public', "
            "'resolve_service_identity_by_credential_hash(text)', 'EXECUTE') AS can_execute"
        )
        assert row["can_execute"] is False

    async def test_app_and_worker_have_execute(self, db_pools, admin_conn):
        row = await admin_conn.fetchrow(
            "SELECT "
            "has_function_privilege('cognitive_app', "
            "'resolve_service_identity_by_credential_hash(text)', 'EXECUTE') AS app_can, "
            "has_function_privilege('cognitive_worker', "
            "'resolve_service_identity_by_credential_hash(text)', 'EXECUTE') AS worker_can"
        )
        assert row["app_can"] is True
        assert row["worker_can"] is True

    async def test_current_user_is_member_of_cognitive_admin(self, db_pools, admin_conn):
        """A conexão admin (quem roda migrations) precisa ser membro de
        cognitive_admin pra `ALTER FUNCTION ... OWNER TO` funcionar — é a
        causa raiz do InsufficientPrivilegeError original. `GRANT
        cognitive_admin TO CURRENT_USER` em 002 resolve isso."""
        row = await admin_conn.fetchrow(
            "SELECT pg_has_role(current_user, 'cognitive_admin', 'MEMBER') AS is_member"
        )
        assert row["is_member"] is True


class TestFunctionOwnershipRestrictions:
    """SEC-002 hotfix (retry pós-Gate): app/worker só têm EXECUTE — nunca
    conseguem alterar, substituir, remover ou mudar grants da função, nem
    adquirir a role owner via SET ROLE."""

    async def test_app_role_cannot_alter_function_owner(
        self, db_pools, seeded_tenants, app_conn
    ):
        from .conftest import set_tenant_local

        await set_tenant_local(app_conn, seeded_tenants["tenant-a"])
        with pytest.raises(Exception):
            await app_conn.execute(
                "ALTER FUNCTION resolve_service_identity_by_credential_hash(TEXT) "
                "OWNER TO cognitive_app"
            )

    async def test_worker_role_cannot_alter_function_owner(
        self, db_pools, seeded_tenants, worker_conn
    ):
        from .conftest import set_tenant_local

        await set_tenant_local(worker_conn, seeded_tenants["tenant-a"])
        with pytest.raises(Exception):
            await worker_conn.execute(
                "ALTER FUNCTION resolve_service_identity_by_credential_hash(TEXT) "
                "OWNER TO cognitive_worker"
            )

    async def test_app_role_cannot_drop_function(self, db_pools, seeded_tenants, app_conn):
        from .conftest import set_tenant_local

        await set_tenant_local(app_conn, seeded_tenants["tenant-a"])
        with pytest.raises(Exception):
            await app_conn.execute(
                "DROP FUNCTION resolve_service_identity_by_credential_hash(TEXT)"
            )

    async def test_worker_role_cannot_drop_function(self, db_pools, seeded_tenants, worker_conn):
        from .conftest import set_tenant_local

        await set_tenant_local(worker_conn, seeded_tenants["tenant-a"])
        with pytest.raises(Exception):
            await worker_conn.execute(
                "DROP FUNCTION resolve_service_identity_by_credential_hash(TEXT)"
            )

    async def test_app_role_cannot_replace_function_body(
        self, db_pools, seeded_tenants, app_conn
    ):
        """Se app conseguisse CREATE OR REPLACE, poderia trocar o corpo
        da função por SQL arbitrário rodando com privilégio de owner —
        exatamente o que SECURITY DEFINER + ownership travado impede."""
        from .conftest import set_tenant_local

        await set_tenant_local(app_conn, seeded_tenants["tenant-a"])
        with pytest.raises(Exception):
            await app_conn.execute(
                """
                CREATE OR REPLACE FUNCTION resolve_service_identity_by_credential_hash(p_credential_hash TEXT)
                RETURNS TABLE (service_identity_id UUID, tenant_id UUID, actor_id TEXT, profile TEXT)
                LANGUAGE sql SECURITY DEFINER
                AS $$ SELECT id, tenant_id, actor_id, profile FROM service_identities $$
                """
            )

    async def test_app_role_cannot_change_grants_on_function(
        self, db_pools, seeded_tenants, app_conn
    ):
        from .conftest import set_tenant_local

        await set_tenant_local(app_conn, seeded_tenants["tenant-a"])
        with pytest.raises(Exception):
            await app_conn.execute(
                "GRANT EXECUTE ON FUNCTION resolve_service_identity_by_credential_hash(TEXT) "
                "TO PUBLIC"
            )

    async def test_worker_role_cannot_change_grants_on_function(
        self, db_pools, seeded_tenants, worker_conn
    ):
        from .conftest import set_tenant_local

        await set_tenant_local(worker_conn, seeded_tenants["tenant-a"])
        with pytest.raises(Exception):
            await worker_conn.execute(
                "GRANT EXECUTE ON FUNCTION resolve_service_identity_by_credential_hash(TEXT) "
                "TO PUBLIC"
            )

    async def test_app_role_cannot_set_role_to_admin(self, db_pools, app_conn):
        with pytest.raises(Exception):
            await app_conn.execute("SET ROLE cognitive_admin")

    async def test_worker_role_cannot_set_role_to_admin(self, db_pools, worker_conn):
        with pytest.raises(Exception):
            await worker_conn.execute("SET ROLE cognitive_admin")

    async def test_app_role_is_not_member_of_cognitive_admin(self, db_pools, admin_conn):
        """Confirma no catálogo (não só por tentativa/erro) que cognitive_app
        nunca ganhou membership em cognitive_admin — a correção do
        ownership (GRANT ... TO CURRENT_USER) é sobre a conexão que RODA
        migrations, nunca sobre as roles de runtime."""
        row = await admin_conn.fetchrow(
            "SELECT pg_has_role('cognitive_app', 'cognitive_admin', 'MEMBER') AS is_member"
        )
        assert row["is_member"] is False

    async def test_worker_role_is_not_member_of_cognitive_admin(self, db_pools, admin_conn):
        row = await admin_conn.fetchrow(
            "SELECT pg_has_role('cognitive_worker', 'cognitive_admin', 'MEMBER') AS is_member"
        )
        assert row["is_member"] is False


class TestWorkerIdentity:
    async def test_worker_identity_isolated_from_app_identity(
        self, db_pools, seeded_tenants, admin_conn
    ):
        tenant_a_id = seeded_tenants["tenant-a"]
        worker_credential = "gate-worker-credential-xyz789"
        worker_hash = hash_credential(worker_credential)
        await admin_conn.execute(
            """
            INSERT INTO service_identities(tenant_id, actor_id, credential_hash, profile)
            VALUES($1, 'worker-infra', $2, 'infra-read')
            ON CONFLICT (credential_hash) DO NOTHING
            """,
            uuid.UUID(tenant_a_id),
            worker_hash,
        )
        repo = ServiceIdentityRepository()
        identity = await repo.lookup(worker_credential)
        assert identity is not None
        assert identity.actor_id == "worker-infra"
        await admin_conn.execute(
            "DELETE FROM service_identities WHERE credential_hash = $1", worker_hash
        )
