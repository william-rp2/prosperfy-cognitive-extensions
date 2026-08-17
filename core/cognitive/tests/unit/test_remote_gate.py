"""Unit tests for Sprint 0.2 remote gate fixes."""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from cognitive.config.db_target import (
    FORBIDDEN_PROJECT_REF,
    HOMOLOG_PROJECT_REF,
)
from cognitive.gate.dsn_builder import build_postgres_dsn, build_supabase_role_dsn
from cognitive.gate.migration_scan import scan_migrations_dir
from cognitive.gate.redaction import redact_dsn, safe_connection_target, sanitize_exception
from cognitive.gate.verify_target import verify_target, print_verify_target_report

REPO_ROOT = Path(__file__).resolve().parents[4]
MIGRATIONS_DIR = REPO_ROOT / "core" / "migrations"
GATE_SCRIPT = REPO_ROOT / "scripts" / "sprint_0_2_remote_gate.py"


class TestVerifyTarget:
    def test_missing_admin_dsn_fail_closed(self):
        report = verify_target(None)
        assert report.verified is False
        assert report.admin_available is False
        assert "not configured" in report.reason

    def test_expected_homolog_target_pass(self):
        dsn = f"postgresql://postgres:secret@db.{HOMOLOG_PROJECT_REF}.supabase.co:5432/postgres"
        report = verify_target(dsn)
        assert report.verified is True
        assert report.homolog_match is True
        assert report.forbidden_match is False

    def test_forbidden_production_target_fail_closed(self):
        dsn = f"postgresql://postgres:secret@db.{FORBIDDEN_PROJECT_REF}.supabase.co:5432/postgres"
        report = verify_target(dsn)
        assert report.verified is False
        assert report.forbidden_match is True
        assert "forbidden" in report.reason

    def test_unknown_target_fail_closed(self):
        dsn = "postgresql://postgres:secret@db.unknownref123456.supabase.co:5432/postgres"
        report = verify_target(dsn)
        assert report.verified is False
        assert report.homolog_match is False

    def test_malformed_dsn_fail_closed(self):
        report = verify_target("not-a-valid-dsn")
        assert report.verified is False
        assert "scheme" in report.reason or "recognized" in report.reason

    def test_print_report_never_includes_password(self, capsys):
        secret = "super-secret-value-xyz"
        dsn = f"postgresql://postgres:{secret}@db.{HOMOLOG_PROJECT_REF}.supabase.co:5432/postgres"
        report = verify_target(dsn)
        print_verify_target_report(report)
        out = capsys.readouterr().out
        assert secret not in out
        assert HOMOLOG_PROJECT_REF in out


class TestVerifyTargetCli:
    def test_verify_target_cli_uses_urlparse_correctly(self, monkeypatch, capsys):
        monkeypatch.setenv(
            "COGNITIVE_DB_ADMIN_URL",
            f"postgresql://postgres:secret@db.{HOMOLOG_PROJECT_REF}.supabase.co:5432/postgres",
        )
        proc = subprocess.run(
            [sys.executable, str(GATE_SCRIPT), "verify-target"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        assert "AttributeError" not in proc.stderr
        assert "verified=YES" in proc.stdout
        assert "secret" not in proc.stdout


class TestDsnBuilder:
    def test_special_characters_escaped(self):
        dsn = build_postgres_dsn(
            user="cognitive_app",
            password="p@ss:w/rd?#",
            host="db.example.supabase.co",
        )
        assert "p%40ss%3Aw%2Frd" in dsn
        assert "sslmode=require" in dsn

    def test_supabase_role_dsn_structure(self):
        dsn = build_supabase_role_dsn(
            project_ref=HOMOLOG_PROJECT_REF,
            role="cognitive_app",
            password="x",
        )
        assert f"db.{HOMOLOG_PROJECT_REF}.supabase.co" in dsn
        assert "cognitive_app" in dsn
        assert "sslmode=require" in dsn


class TestRedaction:
    def test_redact_dsn_in_exception(self):
        dsn = "postgresql://user:password@host:5432/db"
        msg = sanitize_exception(Exception(f"connection failed: {dsn}"))
        assert "password" not in msg
        assert "postgresql://***:***@***" in msg

    def test_safe_connection_target(self):
        dsn = f"postgresql://postgres:secret@db.{HOMOLOG_PROJECT_REF}.supabase.co:5432/postgres"
        target = safe_connection_target(dsn)
        assert "secret" not in target
        assert HOMOLOG_PROJECT_REF in target


class TestMigrationSecretScan:
    def test_versioned_migrations_have_no_forbidden_credentials(self):
        violations = scan_migrations_dir(MIGRATIONS_DIR)
        assert violations == [], f"Migration secret violations: {violations}"

    def test_scan_detects_password_literal(self, tmp_path):
        bad = tmp_path / "999_bad.sql"
        bad.write_text("CREATE ROLE foo LOGIN PASSWORD 'secret';", encoding="utf-8")
        from cognitive.gate.migration_scan import scan_migration_file

        violations = scan_migration_file(bad)
        assert violations


class TestCredentialBootstrapModule:
    def test_bootstrap_uses_quote_literal(self):
        from cognitive.gate import credential_bootstrap as cb

        source = Path(cb.__file__).read_text(encoding="utf-8")
        assert "quote_literal($1" in source
        assert "PASSWORD $1" not in source
        assert "app-dev-secret" not in source
        assert "worker-dev-secret" not in source
        assert cb.BOOTSTRAP_VERSION == "2"
