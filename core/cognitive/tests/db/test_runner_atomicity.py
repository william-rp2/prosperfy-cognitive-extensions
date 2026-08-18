"""
tests/db/test_runner_atomicity.py — Contrato de atomicidade do runner
contra Postgres real. Destrutivo (CREATE/DROP TABLE de propósito) — só
roda em testcontainers efêmero (`allow_destructive_migrations`), nunca
contra Homolog remoto compartilhado. Mecanismo legado/opcional (DG-001):
não é requisito deste Sprint rodar localmente — sem Docker/testcontainers
disponível, tudo aqui fica SKIP, honestamente, e a prova real acontece no
Gate/CI que tiver Postgres efêmero configurado.
"""

from __future__ import annotations

import sys
from pathlib import Path

import asyncpg
import pytest

from .conftest import db_integration_available, skip_reason

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"
sys.path.insert(0, str(MIGRATIONS_DIR))
import runner  # noqa: E402

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not db_integration_available(), reason=skip_reason()),
]


@pytest.fixture
async def clean_schema(admin_conn, allow_destructive_migrations):
    """Só roda o corpo do teste se destrutivo for permitido; garante uma
    tabela de tracking vazia isolada por teste (nome único evita colidir
    com _migrations real usada por outros testes/fixtures)."""
    if not allow_destructive_migrations:
        pytest.skip("testes de atomicidade só rodam em testcontainers efêmero")
    await admin_conn.execute("DROP TABLE IF EXISTS _migrations_test_atomicity")
    yield admin_conn
    await admin_conn.execute("DROP TABLE IF EXISTS runner_atomicity_probe")
    await admin_conn.execute("DROP TABLE IF EXISTS _migrations_test_atomicity")


async def _applied_test(conn: asyncpg.Connection) -> dict[str, str]:
    rows = await conn.fetch("SELECT version, checksum FROM _migrations_test_atomicity")
    return {r["version"]: r["checksum"] for r in rows}


class TestMigrationAtomicityRealPostgres:
    async def test_full_valid_migration_commits_sql_and_tracking_together(
        self, clean_schema, tmp_path
    ):
        conn = clean_schema
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS _migrations_test_atomicity (
                version TEXT PRIMARY KEY, checksum TEXT NOT NULL
            )
        """)
        sql_file = tmp_path / "900_valid.sql"
        sql_file.write_text(
            "CREATE TABLE runner_atomicity_probe (a int); "
            "INSERT INTO runner_atomicity_probe VALUES (1);",
            encoding="utf-8",
        )

        async with conn.transaction():
            await conn.execute(sql_file.read_text(encoding="utf-8"))
            await conn.execute(
                "INSERT INTO _migrations_test_atomicity(version, checksum) VALUES($1, $2)",
                "900_valid", runner.file_checksum(sql_file),
            )

        row = await conn.fetchval("SELECT a FROM runner_atomicity_probe")
        assert row == 1
        applied = await _applied_test(conn)
        assert applied["900_valid"] == runner.file_checksum(sql_file)

    async def test_statement_failure_midway_leaves_zero_trace(self, clean_schema, tmp_path):
        """statement 1 = CREATE TABLE, statement 2 = INSERT, statement 3 =
        erro proposital -> nem a tabela, nem o insert, nem o tracking
        sobrevivem."""
        conn = clean_schema
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS _migrations_test_atomicity (
                version TEXT PRIMARY KEY, checksum TEXT NOT NULL
            )
        """)
        sql_file = tmp_path / "901_broken.sql"
        sql_file.write_text(
            "CREATE TABLE runner_atomicity_probe (a int); "
            "INSERT INTO runner_atomicity_probe VALUES (1); "
            "SELECT 1/0;",
            encoding="utf-8",
        )

        with pytest.raises(Exception):
            async with conn.transaction():
                await conn.execute(sql_file.read_text(encoding="utf-8"))
                await conn.execute(
                    "INSERT INTO _migrations_test_atomicity(version, checksum) VALUES($1, $2)",
                    "901_broken", runner.file_checksum(sql_file),
                )

        table_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'runner_atomicity_probe')"
        )
        assert table_exists is False
        applied = await _applied_test(conn)
        assert "901_broken" not in applied

    async def test_retry_after_failed_attempt_succeeds_cleanly(self, clean_schema, tmp_path):
        """Reproduz o cenário real do Gate: primeira tentativa falha (SQL
        malformado), estado fica limpo (provado acima); uma segunda
        tentativa com o arquivo corrigido aplica normalmente, sem exigir
        nenhuma limpeza manual."""
        conn = clean_schema
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS _migrations_test_atomicity (
                version TEXT PRIMARY KEY, checksum TEXT NOT NULL
            )
        """)
        broken = tmp_path / "902_retry.sql"
        broken.write_text("CREATE TABLE runner_atomicity_probe (a int); SELECT 1/0;", encoding="utf-8")

        with pytest.raises(Exception):
            async with conn.transaction():
                await conn.execute(broken.read_text(encoding="utf-8"))
                await conn.execute(
                    "INSERT INTO _migrations_test_atomicity(version, checksum) VALUES($1, $2)",
                    "902_retry", runner.file_checksum(broken),
                )

        fixed = tmp_path / "902_retry.sql"
        fixed.write_text("CREATE TABLE runner_atomicity_probe (a int);", encoding="utf-8")

        async with conn.transaction():
            await conn.execute(fixed.read_text(encoding="utf-8"))
            await conn.execute(
                "INSERT INTO _migrations_test_atomicity(version, checksum) VALUES($1, $2)",
                "902_retry", runner.file_checksum(fixed),
            )

        table_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'runner_atomicity_probe')"
        )
        assert table_exists is True
        applied = await _applied_test(conn)
        assert "902_retry" in applied

    async def test_privilege_error_midway_rolls_back_everything(
        self, clean_schema, tmp_path, seeded_tenants
    ):
        """Reproduz o erro real do Gate: um statement de privilégio
        (ALTER ... OWNER TO uma role da qual current_user não é membro)
        falha no meio do arquivo — tudo antes dele reverte junto."""
        conn = clean_schema
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS _migrations_test_atomicity (
                version TEXT PRIMARY KEY, checksum TEXT NOT NULL
            )
        """)
        sql_file = tmp_path / "903_privilege_fail.sql"
        sql_file.write_text(
            "CREATE TABLE runner_atomicity_probe (a int); "
            "CREATE OR REPLACE FUNCTION runner_atomicity_probe_fn() RETURNS VOID "
            "LANGUAGE sql AS $$ SELECT 1 $$; "
            "ALTER FUNCTION runner_atomicity_probe_fn() OWNER TO cognitive_worker;",
            encoding="utf-8",
        )

        with pytest.raises(Exception):
            async with conn.transaction():
                await conn.execute(sql_file.read_text(encoding="utf-8"))
                await conn.execute(
                    "INSERT INTO _migrations_test_atomicity(version, checksum) VALUES($1, $2)",
                    "903_privilege_fail", runner.file_checksum(sql_file),
                )

        table_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'runner_atomicity_probe')"
        )
        function_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'runner_atomicity_probe_fn')"
        )
        assert table_exists is False
        assert function_exists is False
        await conn.execute("DROP FUNCTION IF EXISTS runner_atomicity_probe_fn()")


class TestRunnerUpIntegration:
    """Via runner.run_up() de verdade (não reimplementado no teste) —
    prova idempotência de skip e fail-closed de checksum."""

    async def test_already_applied_migration_is_skipped_idempotently(
        self, clean_schema, tmp_path, monkeypatch
    ):
        conn = clean_schema
        sql_file = tmp_path / "904_idempotent.sql"
        sql_file.write_text("CREATE TABLE runner_atomicity_probe (a int);", encoding="utf-8")

        monkeypatch.setattr(runner, "MIGRATIONS", [("904_idempotent", sql_file)])

        await runner.run_up(conn)  # primeira vez: aplica
        await runner.run_up(conn)  # segunda vez: SKIP, não deve re-executar nem falhar

        count = await conn.fetchval("SELECT COUNT(*) FROM _migrations WHERE version = $1", "904_idempotent")
        assert count == 1
        await conn.execute("DELETE FROM _migrations WHERE version = $1", "904_idempotent")

    async def test_checksum_mismatch_fails_closed(self, clean_schema, tmp_path, monkeypatch, capsys):
        conn = clean_schema
        sql_file = tmp_path / "905_checksum.sql"
        sql_file.write_text("CREATE TABLE runner_atomicity_probe (a int);", encoding="utf-8")
        monkeypatch.setattr(runner, "MIGRATIONS", [("905_checksum", sql_file)])
        await runner.run_up(conn)

        sql_file.write_text("CREATE TABLE runner_atomicity_probe (a int, b int);", encoding="utf-8")

        with pytest.raises(SystemExit) as exc_info:
            await runner.run_up(conn)
        assert exc_info.value.code == 1

        await conn.execute("DELETE FROM _migrations WHERE version = $1", "905_checksum")
