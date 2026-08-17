#!/usr/bin/env python3
"""
Sprint 0.2 — Remote Supabase Homolog Gate Runner.

Executar NO SERVIDOR PROSPERFY onde COGNITIVE_DB_ADMIN_URL está configurado.
Nunca imprime secrets ou connection strings completas.

Flow:
  verify-target → migrate → validate-schema → bootstrap-credentials
  → authenticate-real-roles → test-db → full-gate

Required env (minimum):
  COGNITIVE_DB_ADMIN_URL
  COGNITIVE_APP_PASSWORD
  COGNITIVE_WORKER_PASSWORD

COGNITIVE_DB_URL / COGNITIVE_DB_WORKER_URL are built after bootstrap (not required upfront).
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

from cognitive.config.db_target import project_ref_from_dsn  # noqa: E402
from cognitive.gate.auth_check import verify_role_connection  # noqa: E402
from cognitive.gate.credential_bootstrap import bootstrap_role_passwords  # noqa: E402
from cognitive.gate.dsn_builder import build_supabase_role_dsn  # noqa: E402
from cognitive.gate.redaction import safe_connection_target, sanitize_exception  # noqa: E402
from cognitive.gate.verify_target import print_verify_target_report, verify_target  # noqa: E402

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


def _require_passwords() -> tuple[str, str]:
    app_password = os.getenv("COGNITIVE_APP_PASSWORD", "")
    worker_password = os.getenv("COGNITIVE_WORKER_PASSWORD", "")
    if not app_password or not worker_password:
        raise SystemExit(
            "COGNITIVE_APP_PASSWORD and COGNITIVE_WORKER_PASSWORD are required"
        )
    return app_password, worker_password


def _project_ref_or_exit() -> str:
    report = verify_target(_admin_url())
    if not report.verified:
        raise SystemExit(f"Target verification failed: {report.reason}")
    ref = project_ref_from_dsn(_admin_url())
    if not ref:
        raise SystemExit("Cannot derive project ref from admin DSN")
    return ref


def _configure_role_dsns(app_password: str, worker_password: str, project_ref: str) -> None:
    os.environ["COGNITIVE_DB_URL"] = build_supabase_role_dsn(
        project_ref=project_ref,
        role="cognitive_app",
        password=app_password,
    )
    os.environ["COGNITIVE_DB_WORKER_URL"] = build_supabase_role_dsn(
        project_ref=project_ref,
        role="cognitive_worker",
        password=worker_password,
    )
    os.environ.setdefault("COGNITIVE_MODE", "database")


def cmd_verify_target() -> int:
    report = verify_target(_admin_url())
    print_verify_target_report(report)
    return report.exit_code()


def cmd_migrate() -> int:
    if cmd_verify_target() != 0:
        return 1
    target = safe_connection_target(_admin_url())
    print(f"migrate_target={target}")
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
    try:
        conn = await asyncpg.connect(_admin_url())
    except Exception as exc:
        print(f"schema_connect_failed={sanitize_exception(exc)}")
        return 1
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
            SELECT rolname, rolcanlogin, rolbypassrls, rolsuper
            FROM pg_roles
            WHERE rolname IN ('cognitive_admin', 'cognitive_app', 'cognitive_worker')
            ORDER BY rolname
            """
        )
        for row in roles:
            print(
                f"role={row['rolname']} login={row['rolcanlogin']} "
                f"bypassrls={row['rolbypassrls']} super={row['rolsuper']}"
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


async def _bootstrap_credentials_async() -> int:
    import asyncpg

    if cmd_verify_target() != 0:
        return 1
    app_password, worker_password = _require_passwords()
    try:
        conn = await asyncpg.connect(_admin_url())
    except Exception as exc:
        print(f"bootstrap_connect_failed={sanitize_exception(exc)}")
        return 1
    try:
        await bootstrap_role_passwords(conn, app_password, worker_password)
        print("bootstrap_credentials=APPLIED")
        print("bootstrap_idempotent=YES")
    except Exception as exc:
        print(f"bootstrap_failed={sanitize_exception(exc)}")
        return 1
    finally:
        await conn.close()

    project_ref = _project_ref_or_exit()
    _configure_role_dsns(app_password, worker_password, project_ref)
    print("COGNITIVE_DB_URL=CONFIGURED")
    print("COGNITIVE_DB_WORKER_URL=CONFIGURED")
    return 0


def cmd_bootstrap_credentials() -> int:
    return asyncio.run(_bootstrap_credentials_async())


async def _authenticate_real_roles_async() -> int:
    if cmd_verify_target() != 0:
        return 1
    app_password, worker_password = _require_passwords()
    project_ref = _project_ref_or_exit()
    _configure_role_dsns(app_password, worker_password, project_ref)

    app_dsn = os.environ["COGNITIVE_DB_URL"]
    worker_dsn = os.environ["COGNITIVE_DB_WORKER_URL"]

    app_result = await verify_role_connection(app_dsn, "cognitive_app")
    print(f"app_current_user={app_result.current_user or 'none'}")
    print(f"app_authenticated={'YES' if app_result.ok else 'NO'}")
    print(f"app_reason={app_result.reason}")
    if not app_result.ok:
        return 1

    worker_result = await verify_role_connection(worker_dsn, "cognitive_worker")
    print(f"worker_current_user={worker_result.current_user or 'none'}")
    print(f"worker_authenticated={'YES' if worker_result.ok else 'NO'}")
    print(f"worker_reason={worker_result.reason}")
    if not worker_result.ok:
        return 1

    if not app_result.privilege_escape_blocked or not worker_result.privilege_escape_blocked:
        print("privilege_escape_check=FAILED")
        return 1
    print("privilege_escape_check=PASS")
    return 0


def cmd_authenticate_real_roles() -> int:
    return asyncio.run(_authenticate_real_roles_async())


def cmd_test_db() -> int:
    if cmd_verify_target() != 0:
        return 1
    if not os.getenv("COGNITIVE_DB_URL") or not os.getenv("COGNITIVE_DB_WORKER_URL"):
        rc = cmd_bootstrap_credentials()
        if rc != 0:
            return rc
        rc = cmd_authenticate_real_roles()
        if rc != 0:
            return rc

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
        ("bootstrap-credentials", cmd_bootstrap_credentials),
        ("authenticate-real-roles", cmd_authenticate_real_roles),
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
        choices=[
            "verify-target",
            "migrate",
            "validate-schema",
            "bootstrap-credentials",
            "authenticate-real-roles",
            "test-db",
            "full-gate",
        ],
    )
    args = parser.parse_args()
    handlers = {
        "verify-target": cmd_verify_target,
        "migrate": cmd_migrate,
        "validate-schema": cmd_validate_schema,
        "bootstrap-credentials": cmd_bootstrap_credentials,
        "authenticate-real-roles": cmd_authenticate_real_roles,
        "test-db": cmd_test_db,
        "full-gate": cmd_full_gate,
    }
    return handlers[args.command]()


if __name__ == "__main__":
    raise SystemExit(main())
