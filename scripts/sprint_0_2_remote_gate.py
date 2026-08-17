#!/usr/bin/env python3
"""
Sprint 0.2 — Remote Supabase Homolog Gate Runner.

Executar NO SERVIDOR PROSPERFY onde COGNITIVE_DB_ADMIN_URL está configurado.
Nunca imprime secrets ou connection strings completas.

Usage:
  python scripts/sprint_0_2_remote_gate.py verify-target
  python scripts/sprint_0_2_remote_gate.py migrate
  python scripts/sprint_0_2_remote_gate.py validate-schema
  python scripts/sprint_0_2_remote_gate.py test-db
  python scripts/sprint_0_2_remote_gate.py full-gate
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COGNITIVE_DIR = REPO_ROOT / "core" / "cognitive"
MIGRATIONS_RUNNER = REPO_ROOT / "core" / "migrations" / "runner.py"

sys.path.insert(0, str(COGNITIVE_DIR))

from cognitive.config.db_target import (  # noqa: E402
    HOMOLOG_PROJECT_REF,
    FORBIDDEN_PROJECT_REF,
    project_ref_from_dsn,
    verify_homolog_admin_dsn,
)

EXPECTED_TABLES = {
    "tenants",
    "tenant_members",
    "tenant_resources",
    "credential_refs",
    "tenant_integrations",
    "capability_grants",
    "service_identities",
    "audit_events",
    "execution_traces",
    "cost_telemetry",
    "_migrations",
}


def _admin_url() -> str:
    return os.getenv("COGNITIVE_DB_ADMIN_URL", "")


def _ensure_app_worker_urls() -> None:
    """Define COGNITIVE_DB_URL/WORKER a partir de secrets remotos se ausentes."""
    admin = _admin_url()
    ref = project_ref_from_dsn(admin)
    if not ref:
        raise SystemExit("Cannot derive project ref from admin DSN")

    if not os.getenv("COGNITIVE_DB_URL"):
        app_password = os.getenv("COGNITIVE_APP_PASSWORD")
        if not app_password:
            raise SystemExit(
                "COGNITIVE_DB_URL missing — set remotely or provide COGNITIVE_APP_PASSWORD"
            )
        os.environ["COGNITIVE_DB_URL"] = (
            f"postgresql://cognitive_app:{app_password}@db.{ref}.supabase.co:5432/postgres"
        )

    if not os.getenv("COGNITIVE_DB_WORKER_URL"):
        worker_password = os.getenv("COGNITIVE_WORKER_PASSWORD")
        if not worker_password:
            raise SystemExit(
                "COGNITIVE_DB_WORKER_URL missing — set remotely or provide COGNITIVE_WORKER_PASSWORD"
            )
        os.environ["COGNITIVE_DB_WORKER_URL"] = (
            f"postgresql://cognitive_worker:{worker_password}@db.{ref}.supabase.co:5432/postgres"
        )

    os.environ.setdefault("COGNITIVE_MODE", "database")


def cmd_verify_target() -> int:
    admin = _admin_url()
    if not admin:
        print("COGNITIVE_DB_ADMIN_URL=NOT_AVAILABLE")
        return 1
    ok, reason = verify_homolog_admin_dsn(admin)
    ref = project_ref_from_dsn(admin) or "unknown"
    user = __import__("urllib.parse").urlparse(admin).username or "unknown"
    print(f"COGNITIVE_DB_ADMIN_URL=AVAILABLE")
    print(f"project_ref={ref}")
    print(f"expected_homolog={HOMOLOG_PROJECT_REF}")
    print(f"forbidden_production={FORBIDDEN_PROJECT_REF}")
    print(f"forbidden_match={ref == FORBIDDEN_PROJECT_REF}")
    print(f"homolog_match={ref == HOMOLOG_PROJECT_REF}")
    print(f"connect_user={user}")
    print(f"verified={'YES' if ok else 'NO'}")
    print(f"reason={reason}")
    return 0 if ok else 1


def cmd_migrate() -> int:
    if cmd_verify_target() != 0:
        return 1
    proc = subprocess.run(
        [sys.executable, str(MIGRATIONS_RUNNER), "--up"],
        cwd=str(REPO_ROOT),
        env=os.environ.copy(),
    )
    return proc.returncode


async def _validate_schema_async() -> int:
    import asyncpg

    if cmd_verify_target() != 0:
        return 1
    conn = await asyncpg.connect(_admin_url())
    try:
        tables = {
            r["tablename"]
            for r in await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
        }
        missing = EXPECTED_TABLES - tables
        if missing:
            print(f"schema_missing={sorted(missing)}")
            return 1
        print(f"schema_tables_ok={len(EXPECTED_TABLES)}")

        roles = await conn.fetch(
            """
            SELECT rolname, rolbypassrls, rolsuper
            FROM pg_roles
            WHERE rolname IN ('cognitive_admin', 'cognitive_app', 'cognitive_worker', current_user)
            ORDER BY rolname
            """
        )
        for row in roles:
            print(
                f"role={row['rolname']} bypassrls={row['rolbypassrls']} super={row['rolsuper']}"
            )

        rls = await conn.fetch(
            """
            SELECT c.relname, c.relrowsecurity
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relkind = 'r'
              AND c.relname IN (
                'tenants','tenant_members','tenant_resources','audit_events',
                'capability_grants','service_identities','cost_telemetry'
              )
            ORDER BY c.relname
            """
        )
        disabled = [r["relname"] for r in rls if not r["relrowsecurity"]]
        if disabled:
            print(f"rls_disabled={disabled}")
            return 1
        print(f"rls_enabled_tables={len(rls)}")

        migrations = await conn.fetch("SELECT version FROM _migrations ORDER BY version")
        print(f"migrations_applied={[r['version'] for r in migrations]}")
    finally:
        await conn.close()
    return 0


def cmd_validate_schema() -> int:
    return asyncio.run(_validate_schema_async())


def cmd_test_db() -> int:
    if cmd_verify_target() != 0:
        return 1
    _ensure_app_worker_urls()
    env = os.environ.copy()
    env["COGNITIVE_MODE"] = "database"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/db/", "-v", "--tb=short"],
        cwd=str(COGNITIVE_DIR),
        env=env,
    )
    return proc.returncode


def cmd_full_gate() -> int:
    steps = [
        ("verify-target", cmd_verify_target),
        ("migrate", cmd_migrate),
        ("validate-schema", cmd_validate_schema),
        ("test-db", cmd_test_db),
    ]
    for name, fn in steps:
        print(f"\n=== STEP: {name} ===")
        rc = fn()
        if rc != 0:
            print(f"GATE_FAILED at step={name}")
            return rc
    print("\nGATE_DB_STEPS=PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Sprint 0.2 remote homolog gate")
    parser.add_argument(
        "command",
        choices=["verify-target", "migrate", "validate-schema", "test-db", "full-gate"],
    )
    args = parser.parse_args()
    return {
        "verify-target": cmd_verify_target,
        "migrate": cmd_migrate,
        "validate-schema": cmd_validate_schema,
        "test-db": cmd_test_db,
        "full-gate": cmd_full_gate,
    }[args.command]()


if __name__ == "__main__":
    raise SystemExit(main())
