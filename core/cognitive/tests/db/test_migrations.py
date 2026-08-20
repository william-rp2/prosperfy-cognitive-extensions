"""
tests/db/test_migrations.py — Migration reproducibility (ephemeral DB only).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import asyncpg
import pytest

from .conftest import MIGRATIONS_DIR, db_integration_available, skip_reason

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not db_integration_available(), reason=skip_reason()),
]

ROLLBACK_DIR = MIGRATIONS_DIR / "rollback"


def migration_files() -> list[tuple[str, Path]]:
    return sorted(
        [(p.stem, p) for p in MIGRATIONS_DIR.glob("[0-9]*.sql")],
        key=lambda x: x[0],
    )


def file_checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


async def apply_all(conn: asyncpg.Connection) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            checksum TEXT NOT NULL
        )
    """)
    applied = {r["version"] for r in await conn.fetch("SELECT version FROM _migrations")}
    for version, path in migration_files():
        if version not in applied:
            await conn.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
            await conn.execute(path.read_text(encoding="utf-8"))
            await conn.execute(
                "INSERT INTO _migrations(version, checksum) VALUES($1, $2)",
                version,
                file_checksum(path),
            )


async def rollback_all(conn: asyncpg.Connection) -> None:
    applied = sorted(
        [r["version"] for r in await conn.fetch("SELECT version FROM _migrations")],
        reverse=True,
    )
    for version in applied:
        rollback_path = ROLLBACK_DIR / f"{version}_rollback.sql"
        if rollback_path.exists():
            await conn.execute(rollback_path.read_text(encoding="utf-8"))
        await conn.execute("DELETE FROM _migrations WHERE version = $1", version)
    await conn.execute("DROP TABLE IF EXISTS _migrations")


async def get_tables(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )
    return {r["tablename"] for r in rows}


class TestMigrationReproducibility:
    @pytest.mark.safe_remote
    async def test_apply_all_creates_expected_tables(self, admin_conn, allow_destructive_migrations):
        if not allow_destructive_migrations:
            tables = await get_tables(admin_conn)
            expected = {
                "tenants", "tenant_members", "tenant_resources",
                "credential_refs", "tenant_integrations", "capability_grants",
                "service_identities", "audit_events", "execution_traces",
                "cost_telemetry", "_migrations",
            }
            missing = expected - tables
            assert not missing, f"Homolog schema missing tables: {missing}"
            return

        await apply_all(admin_conn)
        tables = await get_tables(admin_conn)
        assert "tenants" in tables
        assert "audit_events" in tables

    @pytest.mark.ephemeral_only
    async def test_rollback_removes_all_tables(self, admin_conn, allow_destructive_migrations):
        if not allow_destructive_migrations:
            pytest.skip("destructive rollback disabled on remote homolog")
        await apply_all(admin_conn)
        await rollback_all(admin_conn)
        tables = await get_tables(admin_conn)
        assert "tenants" not in tables

    @pytest.mark.safe_remote
    async def test_migration_checksums_match_files(self, admin_conn):
        rows = await admin_conn.fetch("SELECT version, checksum FROM _migrations ORDER BY version")
        if not rows:
            pytest.skip("No _migrations on homolog yet")
        version_map = {r["version"]: r["checksum"] for r in rows}
        for version, path in migration_files():
            assert version in version_map
            assert version_map[version] == file_checksum(path)
