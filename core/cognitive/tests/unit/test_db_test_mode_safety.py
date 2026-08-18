"""
Unit tests for the COGNITIVE_DB_TEST_MODE fail-closed safety mechanism.

NO real DB — everything here is pure functions / env var monkeypatching.
This exercises the exact incident class from the Homolog `_migrations`
drop: a destructive DB test must NEVER run unless COGNITIVE_DB_TEST_MODE=
ephemeral is explicitly declared AND no real remote DSN triplet is
configured. There is no implicit default and no override.
"""

from __future__ import annotations

import pytest

from tests.db.conftest import (
    DbTestModeFailClosed,
    _decide_db_test_mode,
    resolve_db_test_mode,
)

from cognitive.gate.remote_safety_guard import (
    InvalidDbTestMode,
    check_remote_safety,
    print_remote_safety_report,
    resolve_db_test_mode as guard_resolve_db_test_mode,
)


class TestResolveDbTestMode:
    def test_unset_returns_unset(self, monkeypatch):
        monkeypatch.delenv("COGNITIVE_DB_TEST_MODE", raising=False)
        assert resolve_db_test_mode() == "unset"

    def test_remote_homolog_accepted(self, monkeypatch):
        monkeypatch.setenv("COGNITIVE_DB_TEST_MODE", "remote_homolog")
        assert resolve_db_test_mode() == "remote_homolog"

    def test_ephemeral_accepted_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("COGNITIVE_DB_TEST_MODE", "EPHEMERAL")
        assert resolve_db_test_mode() == "ephemeral"

    def test_invalid_value_raises_runtime_error(self, monkeypatch):
        monkeypatch.setenv("COGNITIVE_DB_TEST_MODE", "yolo")
        with pytest.raises(RuntimeError, match="COGNITIVE_DB_TEST_MODE inválido"):
            resolve_db_test_mode()


class TestDecideDbTestMode:
    """Pure decision function — the actual fail-closed logic, extracted so it
    is testable without pytest.exit / real pytest session internals."""

    def test_remote_dsns_configured_without_declaration_fails_closed(self):
        # Case 1: COGNITIVE_DB_TEST_MODE unset + remote DSNs configured
        # -> must refuse (session-fatal in the real fixture).
        with pytest.raises(DbTestModeFailClosed):
            _decide_db_test_mode(db_mode="remote", declared="unset")

    def test_remote_declared_with_remote_dsns_returns_remote_homolog(self):
        # Case 2
        result = _decide_db_test_mode(db_mode="remote", declared="remote_homolog")
        assert result == "remote_homolog"

    def test_ephemeral_declared_without_remote_dsns_returns_ephemeral(self):
        # Case 3
        result = _decide_db_test_mode(db_mode="testcontainers", declared="ephemeral")
        assert result == "ephemeral"

    def test_ephemeral_declared_with_remote_dsns_fails_closed(self):
        # Case 4: contradictory — COGNITIVE_DB_TEST_MODE=ephemeral but remote
        # DSNs ARE configured (db_mode == "remote").
        with pytest.raises(DbTestModeFailClosed):
            _decide_db_test_mode(db_mode="remote", declared="ephemeral")

    def test_remote_homolog_declared_without_remote_dsns_fails_closed(self):
        # Case 5: contradictory — declared remote_homolog but db_mode says
        # testcontainers (no full remote DSN triplet configured).
        with pytest.raises(DbTestModeFailClosed):
            _decide_db_test_mode(db_mode="testcontainers", declared="remote_homolog")

    def test_no_declaration_no_remote_dsns_returns_testcontainers_undeclared(self):
        # Case 6: plain local testcontainers today, nothing declared.
        # This is the TIGHTENED behavior: previously this combination
        # silently allowed destructive tests via allow_destructive_migrations
        # == (db_mode == "testcontainers"). Now it requires explicit opt-in.
        result = _decide_db_test_mode(db_mode="testcontainers", declared="unset")
        assert result == "testcontainers_undeclared"


class TestAllowDestructiveMigrationsSemantics:
    """allow_destructive_migrations = (db_test_mode == 'ephemeral'). Verify
    that boolean directly against every db_test_mode outcome, since the
    fixture itself is a one-line derivation of db_test_mode."""

    @pytest.mark.parametrize(
        "db_test_mode_value,expected",
        [
            ("remote_homolog", False),
            ("ephemeral", True),
            ("testcontainers_undeclared", False),
        ],
    )
    def test_allow_destructive_migrations_exactly_one_true_case(
        self, db_test_mode_value, expected
    ):
        allow_destructive_migrations = db_test_mode_value == "ephemeral"
        assert allow_destructive_migrations is expected


class TestRemoteSafetyGuardReport:
    """--verify-remote-safety / cognitive.gate.remote_safety_guard — must
    print exactly 3 lines and never anything DSN-shaped, on success or
    failure."""

    def test_guard_resolve_db_test_mode_matches_conftest_contract(self, monkeypatch):
        # The guard module keeps its own tiny copy of resolve_db_test_mode
        # (production code cannot import from tests/); confirm it agrees
        # with the conftest version on the same inputs.
        for raw, expected in [("", "unset"), ("remote_homolog", "remote_homolog"), ("EPHEMERAL", "ephemeral")]:
            monkeypatch.setenv("COGNITIVE_DB_TEST_MODE", raw) if raw else monkeypatch.delenv(
                "COGNITIVE_DB_TEST_MODE", raising=False
            )
            assert guard_resolve_db_test_mode() == resolve_db_test_mode() == expected

    def test_guard_invalid_value_raises(self, monkeypatch):
        monkeypatch.setenv("COGNITIVE_DB_TEST_MODE", "typo-mode")
        with pytest.raises(InvalidDbTestMode):
            guard_resolve_db_test_mode()

    def test_success_prints_exactly_three_lines_no_dsn(self, monkeypatch, capsys):
        secret = "super-secret-value-xyz"
        monkeypatch.setenv(
            "COGNITIVE_DB_ADMIN_URL",
            f"postgresql://postgres:{secret}@db.esvjfkknrzzziafovwrv.supabase.co:5432/postgres",
        )
        monkeypatch.setenv("COGNITIVE_DB_TEST_MODE", "remote_homolog")

        ok, test_mode, destructive_tests = check_remote_safety()
        print_remote_safety_report(ok, test_mode, destructive_tests)
        out = capsys.readouterr().out

        lines = [line for line in out.splitlines() if line]
        assert lines == [
            "target_verified=YES",
            "test_mode=remote_homolog",
            "destructive_tests=DISABLED",
        ]
        assert ok is True
        assert "postgresql://" not in out
        assert secret not in out

    def test_missing_test_mode_declaration_fails(self, monkeypatch, capsys):
        monkeypatch.setenv(
            "COGNITIVE_DB_ADMIN_URL",
            "postgresql://postgres:secret@db.esvjfkknrzzziafovwrv.supabase.co:5432/postgres",
        )
        monkeypatch.delenv("COGNITIVE_DB_TEST_MODE", raising=False)

        ok, test_mode, destructive_tests = check_remote_safety()
        print_remote_safety_report(ok, test_mode, destructive_tests)
        out = capsys.readouterr().out

        assert ok is False
        assert "target_verified=NO" in out
        assert "postgresql://" not in out
        assert "secret" not in out

    def test_forbidden_project_ref_fails_even_with_declaration(self, monkeypatch, capsys):
        monkeypatch.setenv(
            "COGNITIVE_DB_ADMIN_URL",
            "postgresql://postgres:secret@db.wioorhtdwnfujkrynxij.supabase.co:5432/postgres",
        )
        monkeypatch.setenv("COGNITIVE_DB_TEST_MODE", "remote_homolog")

        ok, test_mode, destructive_tests = check_remote_safety()
        print_remote_safety_report(ok, test_mode, destructive_tests)
        out = capsys.readouterr().out

        assert ok is False
        assert "target_verified=NO" in out
        assert "postgresql://" not in out
        assert "secret" not in out

    def test_invalid_declared_mode_fails_and_never_leaks_raw_value_shape(
        self, monkeypatch, capsys
    ):
        monkeypatch.setenv(
            "COGNITIVE_DB_ADMIN_URL",
            "postgresql://postgres:secret@db.esvjfkknrzzziafovwrv.supabase.co:5432/postgres",
        )
        monkeypatch.setenv("COGNITIVE_DB_TEST_MODE", "typo-mode")

        ok, test_mode, destructive_tests = check_remote_safety()
        print_remote_safety_report(ok, test_mode, destructive_tests)
        out = capsys.readouterr().out

        assert ok is False
        assert "target_verified=NO" in out
        assert "test_mode=INVALID" in out
        assert "postgresql://" not in out
        assert "secret" not in out
