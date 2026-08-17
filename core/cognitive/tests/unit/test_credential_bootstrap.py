"""Tests for secure credential bootstrap (quote_literal path)."""

from __future__ import annotations

import pytest

from cognitive.gate.credential_bootstrap import (
    ALLOWED_ROLES,
    APP_ROLE,
    WORKER_ROLE,
    bootstrap_role_passwords,
    set_role_password,
)
from cognitive.gate.redaction import sanitize_exception


class MockConn:
    def __init__(self, role_exists: bool = True) -> None:
        self.role_exists = role_exists
        self.fetchval_calls: list[tuple] = []
        self.execute_calls: list[str] = []

    async def fetchval(self, query: str, *args):
        self.fetchval_calls.append((query, args))
        if "pg_roles" in query:
            return 1 if self.role_exists else None
        if "quote_literal" in query:
            value = args[0]
            escaped = str(value).replace("'", "''")
            return f"'{escaped}'"
        return None

    async def execute(self, query: str, *args):
        self.execute_calls.append(query)


SPECIAL_PASSWORDS = [
    "simple",
    "pass'; DROP ROLE x;--",
    'pass"quote',
    "p@ss",
    "colon:value",
    "slash/value",
    "percent%value",
    "space value",
    "x" * 128,
    "unicode—密码🔒",
]


class TestSetRolePassword:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("password", SPECIAL_PASSWORDS)
    async def test_special_character_passwords(self, password: str):
        conn = MockConn()
        await set_role_password(conn, APP_ROLE, password)
        alter_pwd = [q for q in conn.execute_calls if "PASSWORD" in q][0]
        assert "PASSWORD $1" not in alter_pwd
        assert conn.fetchval_calls[1][0] == "SELECT quote_literal($1::text)"

    @pytest.mark.asyncio
    async def test_idempotent_reexecution(self):
        conn = MockConn()
        await set_role_password(conn, APP_ROLE, "first-password")
        first_calls = len(conn.execute_calls)
        await set_role_password(conn, APP_ROLE, "second-password")
        assert len(conn.execute_calls) == first_calls * 2

    @pytest.mark.asyncio
    async def test_non_allowlisted_role_denied(self):
        conn = MockConn()
        with pytest.raises(ValueError, match="not allowlisted"):
            await set_role_password(conn, "postgres", "secret")

    @pytest.mark.asyncio
    async def test_missing_role_raises_without_password_in_message(self):
        conn = MockConn(role_exists=False)
        secret = "my-ultra-secret-password"
        with pytest.raises(RuntimeError) as exc:
            await set_role_password(conn, APP_ROLE, secret)
        assert secret not in str(exc.value)

    @pytest.mark.asyncio
    async def test_bootstrap_sanitizes_inner_exceptions(self):
        conn = MockConn(role_exists=False)
        secret = "bootstrap-secret-value"
        with pytest.raises(RuntimeError) as exc:
            await bootstrap_role_passwords(conn, secret, "worker-secret")
        msg = str(exc.value)
        assert secret not in msg
        assert "worker-secret" not in msg


class TestAllowlist:
    def test_only_expected_roles(self):
        assert ALLOWED_ROLES == frozenset({APP_ROLE, WORKER_ROLE})


class TestBootstrapOutputSafety:
    @pytest.mark.asyncio
    async def test_execute_sql_never_contains_raw_password(self):
        password = "raw';secret"
        conn = MockConn()
        await set_role_password(conn, WORKER_ROLE, password)
        for sql in conn.execute_calls:
            assert password not in sql

    def test_sanitize_exception_strips_dsn_from_error_chain(self):
        dsn = "postgresql://user:leaked-secret@host:5432/db"
        msg = sanitize_exception(Exception(f"connection failed: {dsn}"))
        assert "leaked-secret" not in msg
        assert "postgresql://***:***@***" in msg
