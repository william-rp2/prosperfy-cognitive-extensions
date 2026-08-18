"""
tests/unit/test_identity_repo_least_privilege.py

SEC-001 (Sprint 0.3): ServiceIdentityRepository.lookup() deve usar o pool
normal da app (app_connection_no_tenant), nunca admin_connection — o
processo web público não deve depender de BYPASSRLS para resolver
identidade. register()/deactivate() continuam em admin_connection()
(bootstrap/CLI, fora do processo web).

Mocka as connection functions — sem DB real necessário.
"""

from __future__ import annotations

import contextlib

import pytest

from cognitive.db.repositories import identity_repo as identity_repo_module
from cognitive.db.repositories.identity_repo import ServiceIdentityRepository, hash_credential


class FakeConn:
    def __init__(self, row=None):
        self._row = row
        self.fetchrow_calls: list[tuple] = []
        self.execute_calls: list[tuple] = []

    async def fetchrow(self, query, *args):
        self.fetchrow_calls.append((query, args))
        return self._row

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))


@contextlib.asynccontextmanager
async def _fake_ctx(conn):
    yield conn


def _make_row():
    return {
        "id": "id-1",
        "tenant_id": "tenant-1",
        "actor_id": "actor-1",
        "credential_hash": hash_credential("cred"),
        "profile": "owner-core",
        "active": True,
    }


class TestLookupUsesAppPoolNoTenant:
    @pytest.mark.asyncio
    async def test_lookup_uses_app_connection_no_tenant_not_admin(self, monkeypatch):
        conn = FakeConn(row=_make_row())
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
    async def test_lookup_touches_last_used_via_security_definer_function(self, monkeypatch):
        conn = FakeConn(row=_make_row())
        monkeypatch.setattr(
            identity_repo_module, "app_connection_no_tenant", lambda: _fake_ctx(conn)
        )

        repo = ServiceIdentityRepository()
        await repo.lookup("cred")

        assert len(conn.execute_calls) == 1
        query, args = conn.execute_calls[0]
        assert "touch_service_identity_last_used" in query
        assert "SET last_used_at" not in query  # não faz UPDATE direto
        assert args == ("id-1",)

    @pytest.mark.asyncio
    async def test_lookup_miss_does_not_touch(self, monkeypatch):
        conn = FakeConn(row=None)
        monkeypatch.setattr(
            identity_repo_module, "app_connection_no_tenant", lambda: _fake_ctx(conn)
        )

        repo = ServiceIdentityRepository()
        result = await repo.lookup("wrong-credential")

        assert result is None
        assert conn.execute_calls == []


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
