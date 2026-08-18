"""
tests/db/conftest.py — DB integration fixtures.

Priority:
  1. REMOTE DSN mode — COGNITIVE_DB_ADMIN_URL + COGNITIVE_DB_URL + COGNITIVE_DB_WORKER_URL
  2. testcontainers (optional CI only)
  3. explicit skip

Gate Sprint 0.2: remote homolog Supabase (esvjfkknrzzziafovwrv).
"""

from __future__ import annotations

import asyncio
import os
import secrets
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

from cognitive.config.db_target import (
    FORBIDDEN_PROJECT_REF,
    HOMOLOG_PROJECT_REF,
    project_ref_from_dsn,
    verify_homolog_admin_dsn,
)
from cognitive.gate.credential_bootstrap import bootstrap_role_passwords
from cognitive.gate.dsn_builder import build_postgres_dsn, host_from_admin_dsn

try:
    try:
        from testcontainers.community.postgres import PostgresContainer
    except ImportError:
        from testcontainers.postgres import PostgresContainer
    TESTCONTAINERS_AVAILABLE = True
except ImportError:
    TESTCONTAINERS_AVAILABLE = False

MIGRATIONS_DIR = Path(__file__).parents[3] / "migrations"
GATE_TENANT_SLUGS = ("gate-tenant-a", "gate-tenant-b")


def _remote_dsns_configured() -> bool:
    return all(
        os.getenv(name)
        for name in (
            "COGNITIVE_DB_ADMIN_URL",
            "COGNITIVE_DB_URL",
            "COGNITIVE_DB_WORKER_URL",
        )
    )


def db_integration_available() -> bool:
    if _remote_dsns_configured():
        ok, _ = verify_homolog_admin_dsn(os.environ["COGNITIVE_DB_ADMIN_URL"])
        return ok
    return TESTCONTAINERS_AVAILABLE


def skip_reason() -> str:
    if _remote_dsns_configured():
        ok, reason = verify_homolog_admin_dsn(os.environ["COGNITIVE_DB_ADMIN_URL"])
        if not ok:
            return f"remote DSN invalid: {reason}"
    if TESTCONTAINERS_AVAILABLE:
        return "Docker/testcontainers unavailable"
    return (
        "DB integration unavailable — configure COGNITIVE_DB_* for homolog "
        f"({HOMOLOG_PROJECT_REF}) or testcontainers in CI"
    )


pytestmark = pytest.mark.skipif(
    not db_integration_available(),
    reason=skip_reason(),
)


@pytest.fixture(scope="session")
def db_mode() -> str:
    return "remote" if _remote_dsns_configured() else "testcontainers"


def resolve_db_test_mode() -> str:
    """Returns 'remote_homolog', 'ephemeral', or 'unset'. Raises RuntimeError
    if the env var is set to anything else."""
    raw = os.getenv("COGNITIVE_DB_TEST_MODE", "").strip().lower()
    if raw and raw not in ("remote_homolog", "ephemeral"):
        raise RuntimeError(
            f"COGNITIVE_DB_TEST_MODE inválido: {raw!r} — use 'remote_homolog' ou 'ephemeral'"
        )
    return raw or "unset"


class DbTestModeFailClosed(Exception):
    """Raised by _decide_db_test_mode when the declared COGNITIVE_DB_TEST_MODE
    and the actual DB target disagree (or agreement is missing). The message
    is the exact text the db_test_mode fixture passes to pytest.exit — kept
    as a plain exception (rather than calling pytest.exit directly) so the
    decision logic is unit-testable without invoking real pytest internals."""


def _decide_db_test_mode(db_mode: str, declared: str) -> str:
    """Pure decision function — no pytest, no I/O. See db_test_mode fixture
    for the fail-closed safety contract this implements."""
    if db_mode == "remote":
        if declared != "remote_homolog":
            raise DbTestModeFailClosed(
                "SAFETY: COGNITIVE_DB_* aponta para um alvo remoto real, mas "
                "COGNITIVE_DB_TEST_MODE não está declarado como 'remote_homolog'. "
                "Recusando conectar a um alvo remoto sem declaração explícita de modo. "
                "Defina COGNITIVE_DB_TEST_MODE=remote_homolog antes de rodar testes DB "
                "contra Homolog."
            )
        return "remote_homolog"
    # db_mode == "testcontainers" (no full remote DSN triplet configured)
    if declared == "remote_homolog":
        raise DbTestModeFailClosed(
            "SAFETY: COGNITIVE_DB_TEST_MODE=remote_homolog foi declarado, mas "
            "COGNITIVE_DB_ADMIN_URL/COGNITIVE_DB_URL/COGNITIVE_DB_WORKER_URL não estão "
            "totalmente configurados para um alvo remoto real. Declaração e ambiente "
            "divergem — recusando prosseguir."
        )
    return "ephemeral" if declared == "ephemeral" else "testcontainers_undeclared"


@pytest.fixture(scope="session")
def db_test_mode(db_mode: str) -> str:
    declared = resolve_db_test_mode()
    try:
        return _decide_db_test_mode(db_mode, declared)
    except DbTestModeFailClosed as exc:
        pytest.exit(str(exc), returncode=1)


@pytest.fixture(scope="session")
def allow_destructive_migrations(db_test_mode: str) -> bool:
    """Destructive DB tests require an EXPLICIT COGNITIVE_DB_TEST_MODE=ephemeral.
    There is NO implicit default that grants this — merely having testcontainers
    available without the explicit declaration is NOT enough (this is intentional:
    the previous, more permissive default is exactly what let a destructive test
    run somewhere it shouldn't have). There is also no override mechanism — no
    other env var can flip this to True while db_test_mode is 'remote_homolog' or
    'testcontainers_undeclared'."""
    return db_test_mode == "ephemeral"


@pytest.fixture(scope="session")
def postgres_container(db_mode: str):
    if db_mode != "testcontainers":
        yield None
        return
    if not TESTCONTAINERS_AVAILABLE:
        pytest.skip("testcontainers não disponível")
    try:
        container = PostgresContainer("postgres:16-alpine")
        container.start()
    except Exception as exc:
        pytest.skip(f"Docker indisponível: {exc}")
    yield container
    container.stop()


@pytest.fixture(scope="session")
def admin_dsn(db_mode: str, postgres_container) -> str:
    if db_mode == "remote":
        dsn = os.environ["COGNITIVE_DB_ADMIN_URL"]
        ok, reason = verify_homolog_admin_dsn(dsn)
        if not ok:
            pytest.fail(f"Homolog target verification failed: {reason}")
        ref = project_ref_from_dsn(dsn)
        assert ref == HOMOLOG_PROJECT_REF
        assert ref != FORBIDDEN_PROJECT_REF
        return dsn

    host = postgres_container.get_container_host_ip()
    port = postgres_container.get_exposed_port(5432)
    user = postgres_container.username
    password = postgres_container.password
    db = postgres_container.dbname
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


@pytest.fixture(scope="session")
def app_dsn(db_mode: str, role_dsns: dict[str, str]) -> str:
    return role_dsns["app"]


@pytest.fixture(scope="session")
def worker_dsn(db_mode: str, role_dsns: dict[str, str]) -> str:
    return role_dsns["worker"]


@pytest.fixture(scope="session")
def role_dsns(admin_dsn: str, db_mode: str) -> dict[str, str]:
    if db_mode == "remote":
        return {
            "admin": admin_dsn,
            "app": os.environ["COGNITIVE_DB_URL"],
            "worker": os.environ["COGNITIVE_DB_WORKER_URL"],
        }
    return asyncio.run(_bootstrap_testcontainer_dsns(admin_dsn))


async def _bootstrap_testcontainer_dsns(admin_dsn: str) -> dict[str, str]:
    conn = await asyncpg.connect(admin_dsn)
    try:
        await _apply_migrations(conn)
        app_password = secrets.token_urlsafe(24)
        worker_password = secrets.token_urlsafe(24)
        await bootstrap_role_passwords(conn, app_password, worker_password)
    finally:
        await conn.close()

    host, port, database = host_from_admin_dsn(admin_dsn)
    return {
        "admin": admin_dsn,
        "app": build_postgres_dsn(
            user="cognitive_app",
            password=app_password,
            host=host,
            port=port,
            database=database,
            sslmode="disable",
        ),
        "worker": build_postgres_dsn(
            user="cognitive_worker",
            password=worker_password,
            host=host,
            port=port,
            database=database,
            sslmode="disable",
        ),
    }


async def _apply_migrations(conn: asyncpg.Connection) -> None:
    await conn.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            checksum TEXT NOT NULL
        )
    """)
    applied = {r["version"] for r in await conn.fetch("SELECT version FROM _migrations")}
    for sql_file in sorted(MIGRATIONS_DIR.glob("[0-9]*.sql")):
        version = sql_file.stem
        if version in applied:
            continue
        await conn.execute(sql_file.read_text(encoding="utf-8"))
        checksum = __import__("hashlib").sha256(sql_file.read_bytes()).hexdigest()[:16]
        await conn.execute(
            "INSERT INTO _migrations(version, checksum) VALUES($1, $2)",
            version,
            checksum,
        )


@pytest.fixture(scope="session")
def migrated_db(admin_dsn: str, db_mode: str, role_dsns: dict[str, str]) -> dict[str, str]:
    if db_mode == "remote":
        if not asyncio.run(_schema_exists(admin_dsn)):
            pytest.fail("Homolog DB missing schema — run migrations before gate tests")
    return {"admin": admin_dsn, "mode": db_mode}


async def _schema_exists(admin_dsn: str) -> bool:
    conn = await asyncpg.connect(admin_dsn)
    try:
        return bool(
            await conn.fetchval("SELECT to_regclass('public.tenants') IS NOT NULL")
        )
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def admin_conn(admin_dsn: str) -> asyncpg.Connection:
    conn = await asyncpg.connect(admin_dsn)
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def app_conn(app_dsn: str) -> asyncpg.Connection:
    """Conexão real como cognitive_app (RLS enforced)."""
    conn = await asyncpg.connect(app_dsn)
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def worker_conn(worker_dsn: str) -> asyncpg.Connection:
    """Conexão real como cognitive_worker (RLS enforced)."""
    conn = await asyncpg.connect(worker_dsn)
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def db_pools(admin_dsn: str, app_dsn: str, worker_dsn: str):
    """Inicializa pools reais para repositórios."""
    from cognitive.db import connection as conn_module

    await conn_module.create_pools(
        app_dsn=app_dsn,
        worker_dsn=worker_dsn,
        admin_dsn=admin_dsn,
    )
    yield conn_module
    await conn_module.close_pools()
    conn_module._app_pool = None
    conn_module._worker_pool = None
    conn_module._admin_pool = None


@pytest_asyncio.fixture
async def seeded_tenants(admin_conn: asyncpg.Connection) -> dict[str, str]:
    tenant_a = await admin_conn.fetchrow(
        "INSERT INTO tenants(slug, name) VALUES($1, 'Gate Tenant A') "
        "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name RETURNING id, slug",
        GATE_TENANT_SLUGS[0],
    )
    tenant_b = await admin_conn.fetchrow(
        "INSERT INTO tenants(slug, name) VALUES($1, 'Gate Tenant B') "
        "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name RETURNING id, slug",
        GATE_TENANT_SLUGS[1],
    )
    result = {
        "tenant-a": str(tenant_a["id"]),
        "tenant-b": str(tenant_b["id"]),
    }
    yield result
    await admin_conn.execute(
        "DELETE FROM tenants WHERE slug = ANY($1::text[])",
        list(GATE_TENANT_SLUGS),
    )


async def set_tenant_local(conn: asyncpg.Connection, tenant_id: str) -> None:
    await conn.execute(
        "SELECT set_config('app.current_tenant_id', $1, true)",
        tenant_id,
    )
