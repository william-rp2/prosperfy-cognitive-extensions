"""
tests/unit/test_identity_repo_least_privilege.py

SEC-001 (Sprint 0.3): ServiceIdentityRepository.lookup() deve usar o pool
normal da app (app_connection_no_tenant), nunca admin_connection — o
processo web público não deve depender de BYPASSRLS para resolver
identidade.

SEC-002 (revisão do Gate): lookup() deve chamar exclusivamente a função
SECURITY DEFINER resolve_service_identity_by_credential_hash — nunca um
SELECT direto na tabela — e o resultado nunca deve carregar
credential_hash. register()/deactivate() continuam em admin_connection()
(bootstrap/CLI, fora do processo web).

Mocka as connection functions — sem DB real necessário.
"""

from __future__ import annotations

import contextlib

import pytest

from cognitive.db.repositories import identity_repo as identity_repo_module
from cognitive.db.repositories.identity_repo import ServiceIdentityRepository, hash_credential


class _FakeTransaction:
    """No-op `async with conn.transaction():` — register()/deactivate()
    wrap their writes in a transaction since Sprint 0.4 (identity_events
    audit trail), but these tests only care about call counts/shape, not
    real commit/rollback semantics (see tests/unit/test_runner_atomicity.py
    for a FakeTransaction that does track BEGIN/COMMIT/ROLLBACK)."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeConn:
    def __init__(self, row=None):
        self._row = row
        self.fetchrow_calls: list[tuple] = []
        self.execute_calls: list[tuple] = []

    def transaction(self):
        return _FakeTransaction()

    async def fetchrow(self, query, *args):
        self.fetchrow_calls.append((query, args))
        return self._row

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))


@contextlib.asynccontextmanager
async def _fake_ctx(conn):
    yield conn


def _make_resolved_row():
    """Shape do retorno de resolve_service_identity_by_credential_hash —
    nunca inclui credential_hash (SEC-002)."""
    return {
        "service_identity_id": "id-1",
        "tenant_id": "tenant-1",
        "actor_id": "actor-1",
        "profile": "owner-core",
    }


class TestLookupUsesAppPoolNoTenant:
    @pytest.mark.asyncio
    async def test_lookup_uses_app_connection_no_tenant_not_admin(self, monkeypatch):
        conn = FakeConn(row=_make_resolved_row())
        app_calls = {"count": 0}

        def fake_app_no_tenant():
            app_calls["count"] += 1
            return _fake_ctx(conn)

        def fake_admin():
            raise AssertionError("lookup() não deve mais usar admin_connection (SEC-001)")

        monkeypatch.setattr(identity_repo_module, "app_connection_no_tenant", fake_app_no_tenant)
        monkeypatch.setattr(identity_repo_module, "admin_connection", fake_admin)

        repo = ServiceIdentityRepository()
        result = await repo.lookup("cred")

        assert app_calls["count"] == 1
        assert result is not None
        assert result.tenant_id == "tenant-1"

    @pytest.mark.asyncio
    async def test_lookup_calls_only_the_security_definer_function(self, monkeypatch):
        """SEC-002: um único fetchrow, chamando a função — nunca SELECT
        direto na tabela, nunca uma segunda operação de 'touch' separada
        (a função atualiza last_used_at atomicamente por dentro)."""
        conn = FakeConn(row=_make_resolved_row())
        monkeypatch.setattr(
            identity_repo_module, "app_connection_no_tenant", lambda: _fake_ctx(conn)
        )

        repo = ServiceIdentityRepository()
        await repo.lookup("cred")

        assert len(conn.fetchrow_calls) == 1
        query, args = conn.fetchrow_calls[0]
        assert "resolve_service_identity_by_credential_hash" in query
        assert "FROM service_identities" not in query  # nunca SELECT direto na tabela
        assert args == (hash_credential("cred"),)
        # Nenhuma chamada extra de "touch" — a função já fez tudo.
        assert conn.execute_calls == []

    @pytest.mark.asyncio
    async def test_lookup_result_never_has_credential_hash(self, monkeypatch):
        conn = FakeConn(row=_make_resolved_row())
        monkeypatch.setattr(
            identity_repo_module, "app_connection_no_tenant", lambda: _fake_ctx(conn)
        )

        repo = ServiceIdentityRepository()
        result = await repo.lookup("cred")

        assert result is not None
        assert not hasattr(result, "credential_hash")

    @pytest.mark.asyncio
    async def test_lookup_miss_returns_none(self, monkeypatch):
        conn = FakeConn(row=None)
        monkeypatch.setattr(
            identity_repo_module, "app_connection_no_tenant", lambda: _fake_ctx(conn)
        )

        repo = ServiceIdentityRepository()
        result = await repo.lookup("wrong-credential")

        assert result is None


class TestRegisterDeactivateStayAdminBootstrapOnly:
    """register()/deactivate() não são chamados por rota HTTP alguma —
    continuar em admin_connection() é seguro e documentado."""

    @pytest.mark.asyncio
    async def test_register_uses_admin_connection(self, monkeypatch):
        conn = FakeConn(row={
            "id": "id-1",
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "actor_id": "actor-1",
            "credential_hash": hash_credential("cred"),
            "profile": "owner-core",
            "active": True,
        })
        calls = {"count": 0}

        def fake_admin():
            calls["count"] += 1
            return _fake_ctx(conn)

        monkeypatch.setattr(identity_repo_module, "admin_connection", fake_admin)

        repo = ServiceIdentityRepository()
        await repo.register("11111111-1111-1111-1111-111111111111", "actor-1", "cred")

        assert calls["count"] == 1

    @pytest.mark.asyncio
    async def test_deactivate_uses_admin_connection(self, monkeypatch):
        conn = FakeConn()
        calls = {"count": 0}

        def fake_admin():
            calls["count"] += 1
            return _fake_ctx(conn)

        monkeypatch.setattr(identity_repo_module, "admin_connection", fake_admin)

        repo = ServiceIdentityRepository()
        await repo.deactivate("cred")

        assert calls["count"] == 1
