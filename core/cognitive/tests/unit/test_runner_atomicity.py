"""
tests/unit/test_runner_atomicity.py — Migration runner atomicity contract,
sem Postgres real (mocka a conexão).

Antes deste hotfix, runner.py fazia `conn.execute(sql_do_arquivo)` e
`conn.execute("INSERT INTO _migrations...")` como DUAS chamadas
separadas — um crash entre as duas deixaria a migration aplicada mas não
rastreada. Corrigido: `apply_one_migration()` envolve as duas na MESMA
`async with conn.transaction()`.

Este arquivo prova o contrato do lado Python (chama transaction(), propaga
exceção, não mascara falha). O comportamento real de ROLLBACK do Postgres
só pode ser provado contra um banco de verdade — ver
tests/db/test_runner_atomicity.py (skip local, roda no Gate).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"
sys.path.insert(0, str(MIGRATIONS_DIR))
import runner  # noqa: E402  (import após sys.path.insert, é intencional)


class FakeTransaction:
    """Mocka `async with conn.transaction():` — registra entrada/saída,
    inclusive se a saída foi por exceção (equivalente a rollback)."""

    def __init__(self, log: list[str]):
        self._log = log

    async def __aenter__(self):
        self._log.append("BEGIN")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._log.append("ROLLBACK" if exc_type else "COMMIT")
        return False  # nunca engole a exceção


class FakeConn:
    def __init__(self, fail_on_execute_call: int | None = None):
        self.log: list[str] = []
        self.execute_calls: list[str] = []
        self._fail_on_execute_call = fail_on_execute_call

    def transaction(self):
        return FakeTransaction(self.log)

    async def execute(self, query, *args):
        self.execute_calls.append(query)
        self.log.append(f"EXEC[{len(self.execute_calls)}]")
        if self._fail_on_execute_call == len(self.execute_calls):
            raise RuntimeError("simulated SQL failure")

    async def fetchval(self, query, *args):
        return None

    async def fetch(self, query, *args):
        return []


@pytest.mark.asyncio
class TestApplyOneMigrationAtomicity:
    async def test_success_wraps_sql_and_tracking_in_one_transaction(self, tmp_path):
        sql_file = tmp_path / "003_test.sql"
        sql_file.write_text("CREATE TABLE t (a int);", encoding="utf-8")
        conn = FakeConn()

        await runner.apply_one_migration(conn, "003_test", sql_file)

        assert conn.log == ["BEGIN", "EXEC[1]", "EXEC[2]", "COMMIT"]
        assert len(conn.execute_calls) == 2
        assert "CREATE TABLE" in conn.execute_calls[0]
        assert "INSERT INTO _migrations" in conn.execute_calls[1]

    async def test_sql_failure_never_reaches_tracking_insert(self, tmp_path):
        """Se o SQL do arquivo falhar, o INSERT de tracking nunca é tentado
        — e a transação sai por ROLLBACK, nunca COMMIT."""
        sql_file = tmp_path / "003_test.sql"
        sql_file.write_text("CREATE TABLE t (a int); SELECT 1/0;", encoding="utf-8")
        conn = FakeConn(fail_on_execute_call=1)

        with pytest.raises(RuntimeError, match="simulated SQL failure"):
            await runner.apply_one_migration(conn, "003_test", sql_file)

        assert conn.log == ["BEGIN", "EXEC[1]", "ROLLBACK"]
        assert len(conn.execute_calls) == 1  # nunca chegou no INSERT de tracking
        assert "COMMIT" not in conn.log

    async def test_tracking_insert_failure_also_rolls_back(self, tmp_path):
        """Se o próprio INSERT de tracking falhar (ex: checksum duplicado
        por corrida), o SQL do arquivo também é revertido — não fica
        'aplicado sem tracking'."""
        sql_file = tmp_path / "003_test.sql"
        sql_file.write_text("CREATE TABLE t (a int);", encoding="utf-8")
        conn = FakeConn(fail_on_execute_call=2)

        with pytest.raises(RuntimeError, match="simulated SQL failure"):
            await runner.apply_one_migration(conn, "003_test", sql_file)

        assert conn.log == ["BEGIN", "EXEC[1]", "EXEC[2]", "ROLLBACK"]
        assert "COMMIT" not in conn.log


@pytest.mark.asyncio
class TestInspectMigrationClassification:
    """Lógica pura de classificação CLEAN/PARTIAL/APPLIED — não depende de
    Postgres real, só do valor que os sinais retornariam."""

    async def test_tracked_is_always_applied(self, monkeypatch):
        conn = FakeConn()

        async def fake_get_applied(_conn):
            return {"002": "abc123"}

        monkeypatch.setattr(runner, "get_applied", fake_get_applied)
        verdict = await runner.inspect_migration(conn, "002")
        assert verdict == "APPLIED"

    async def test_untracked_with_no_signals_is_clean(self, monkeypatch):
        conn = FakeConn()

        async def fake_get_applied(_conn):
            return {}

        async def fake_fetchval(query, *args):
            return False

        monkeypatch.setattr(runner, "get_applied", fake_get_applied)
        monkeypatch.setattr(conn, "fetchval", fake_fetchval)
        verdict = await runner.inspect_migration(conn, "002")
        assert verdict == "CLEAN"

    async def test_untracked_with_any_signal_true_is_partial(self, monkeypatch):
        conn = FakeConn()

        async def fake_get_applied(_conn):
            return {}

        call_count = {"n": 0}

        async def fake_fetchval(query, *args):
            call_count["n"] += 1
            # primeiro sinal (function_exists) retorna True, resto False —
            # simula exatamente o caso real: CREATE FUNCTION rodou, ALTER
            # OWNER falhou antes do resto.
            return call_count["n"] == 1

        monkeypatch.setattr(runner, "get_applied", fake_get_applied)
        monkeypatch.setattr(conn, "fetchval", fake_fetchval)
        verdict = await runner.inspect_migration(conn, "002")
        assert verdict == "PARTIAL"

    async def test_unknown_version_without_fingerprint_falls_back_to_tracking(self, monkeypatch):
        conn = FakeConn()

        async def fake_get_applied(_conn):
            return {}

        monkeypatch.setattr(runner, "get_applied", fake_get_applied)
        verdict = await runner.inspect_migration(conn, "999_nonexistent")
        assert verdict == "UNKNOWN"
