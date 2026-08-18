"""
tests/unit/test_db_connection_admin_optional.py

SEC-001 (Sprint 0.3): create_pools() deve funcionar sem COGNITIVE_DB_ADMIN_URL
— o pool admin fica None, mas o pool app (usado para servir tráfego,
incluindo identity resolution) é criado normalmente. admin_connection()
continua fail-closed (RuntimeError) se ninguém configurou admin DSN —
isso é esperado, pois só bootstrap/CLI precisa dele.

Mocka asyncpg.create_pool — sem DB real necessário.
"""

from __future__ import annotations

import pytest

from cognitive.db import connection as db_connection


class FakePool:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.closed = False

    async def close(self) -> None:
        self.closed = True

    def acquire(self):
        return _FakeAcquireCtx()


class _FakeAcquireCtx:
    async def __aenter__(self):
        return "fake-conn"

    async def __aexit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def _reset_pools():
    db_connection._app_pool = None
    db_connection._worker_pool = None
    db_connection._admin_pool = None
    yield
    db_connection._app_pool = None
    db_connection._worker_pool = None
    db_connection._admin_pool = None


@pytest.mark.asyncio
async def test_create_pools_without_admin_dsn_boots_app_pool(monkeypatch):
    async def fake_create_pool(dsn, min_size=2, max_size=10):
        return FakePool(dsn)

    monkeypatch.setattr(db_connection.asyncpg, "create_pool", fake_create_pool)

    await db_connection.create_pools(
        app_dsn="postgresql://app@host/db",
        worker_dsn=None,
        admin_dsn=None,
    )

    assert db_connection._app_pool is not None
    assert db_connection._admin_pool is None
    assert db_connection.is_db_available() is True


@pytest.mark.asyncio
async def test_app_connection_no_tenant_works_without_admin_pool(monkeypatch):
    async def fake_create_pool(dsn, min_size=2, max_size=10):
        return FakePool(dsn)

    monkeypatch.setattr(db_connection.asyncpg, "create_pool", fake_create_pool)

    await db_connection.create_pools(app_dsn="postgresql://app@host/db", admin_dsn=None)

    async with db_connection.app_connection_no_tenant() as conn:
        assert conn == "fake-conn"


@pytest.mark.asyncio
async def test_admin_connection_still_fail_closed_without_admin_dsn(monkeypatch):
    async def fake_create_pool(dsn, min_size=2, max_size=10):
        return FakePool(dsn)

    monkeypatch.setattr(db_connection.asyncpg, "create_pool", fake_create_pool)

    await db_connection.create_pools(app_dsn="postgresql://app@host/db", admin_dsn=None)

    with pytest.raises(RuntimeError, match="Admin pool"):
        async with db_connection.admin_connection():
            pass


@pytest.mark.asyncio
async def test_app_connection_no_tenant_fail_closed_without_app_dsn():
    with pytest.raises(RuntimeError, match="COGNITIVE_DB_URL"):
        async with db_connection.app_connection_no_tenant():
            pass
