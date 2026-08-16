"""
tests/db/test_migrations.py — Testes de reprodutibilidade e rollback de migrations.

GATE:
  - Migrations reproduzíveis do zero (down 0 → up → schema idêntico)
  - Rollback/forward strategy funcional
  - Tabela _migrations registra versões e checksums corretamente
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import asyncpg
import pytest

from .conftest import MIGRATIONS_DIR, TESTCONTAINERS_AVAILABLE

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not TESTCONTAINERS_AVAILABLE, reason="testcontainers indisponível"),
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
    """Aplica todas as migrations em ordem."""
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
            sql = path.read_text(encoding="utf-8")
            await conn.execute(sql)
            checksum = file_checksum(path)
            await conn.execute(
                "INSERT INTO _migrations(version, checksum) VALUES($1, $2)",
                version, checksum,
            )


async def rollback_all(conn: asyncpg.Connection) -> None:
    """Reverte todas as migrations em ordem inversa."""
    applied = sorted(
        [r["version"] for r in await conn.fetch("SELECT version FROM _migrations")],
        reverse=True,
    )
    for version in applied:
        rollback_path = ROLLBACK_DIR / f"{version}_rollback.sql"
        if rollback_path.exists():
            sql = rollback_path.read_text(encoding="utf-8")
            await conn.execute(sql)
        await conn.execute("DELETE FROM _migrations WHERE version = $1", version)

    # Drop _migrations table também
    await conn.execute("DROP TABLE IF EXISTS _migrations")


async def get_tables(conn: asyncpg.Connection) -> set[str]:
    """Retorna set de tabelas existentes no schema public."""
    rows = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
    )
    return {r["tablename"] for r in rows}


class TestMigrationReproducibility:
    """Migrations reproduzíveis: down 0 → up → mesmo schema."""

    async def test_apply_all_creates_expected_tables(self, admin_conn):
        """Após aplicar todas as migrations, tabelas esperadas existem."""
        await apply_all(admin_conn)

        tables = await get_tables(admin_conn)
        expected = {
            "tenants", "tenant_members", "tenant_resources",
            "credential_refs", "tenant_integrations", "capability_grants",
            "service_identities", "audit_events", "execution_traces",
            "cost_telemetry", "_migrations",
        }
        missing = expected - tables
        assert not missing, f"Tabelas ausentes após migrations: {missing}"

    async def test_rollback_removes_all_tables(self, admin_conn):
        """Após rollback completo, tabelas de migrations removidas."""
        await apply_all(admin_conn)
        await rollback_all(admin_conn)

        tables = await get_tables(admin_conn)
        cognitive_tables = {
            "tenants", "tenant_members", "tenant_resources",
            "credential_refs", "tenant_integrations", "capability_grants",
            "service_identities", "audit_events", "execution_traces",
            "cost_telemetry",
        }
        remaining = cognitive_tables & tables
        assert not remaining, f"Tabelas não removidas pelo rollback: {remaining}"

    async def test_reapply_after_rollback_idempotent(self, admin_conn):
        """Down → up → down → up produz o mesmo schema (idempotência)."""
        await apply_all(admin_conn)
        await rollback_all(admin_conn)
        await apply_all(admin_conn)  # segunda aplicação

        tables = await get_tables(admin_conn)
        assert "tenants" in tables
        assert "audit_events" in tables
        assert "_migrations" in tables

        # Verificar que _migrations registrou corretamente
        rows = await admin_conn.fetch("SELECT version, checksum FROM _migrations ORDER BY version")
        assert len(rows) == len(migration_files())

        # Cleanup
        await rollback_all(admin_conn)

    async def test_migration_checksums_match_files(self, admin_conn):
        """Checksums registrados na tabela batem com os arquivos no disco."""
        await apply_all(admin_conn)

        rows = await admin_conn.fetch("SELECT version, checksum FROM _migrations ORDER BY version")
        version_map = {r["version"]: r["checksum"] for r in rows}

        for version, path in migration_files():
            expected_checksum = file_checksum(path)
            assert version in version_map, f"Migration {version} não registrada"
            assert version_map[version] == expected_checksum, (
                f"Checksum mismatch para {version}: "
                f"esperado={expected_checksum} registrado={version_map[version]}"
            )

        # Cleanup
        await rollback_all(admin_conn)
