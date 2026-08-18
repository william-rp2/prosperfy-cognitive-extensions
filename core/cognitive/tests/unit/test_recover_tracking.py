"""
tests/unit/test_recover_tracking.py — --recover-tracking write-path
contract, sem Postgres real (mocka a conexão e a transação, mesmo padrão
FakeConn/FakeTransaction de test_runner_atomicity.py).

--recover-tracking é o ÚNICO comando deste hotfix com um write path, e
mesmo assim só escreve em `_migrations` — nunca em tabela, role, policy ou
função de negócio. Este arquivo prova duas coisas:

  1. Recusa: se `diagnose_database()` não retornar EXATAMENTE
     TRACKING_MISSING_ONLY, nenhum write é tentado (nem CREATE TABLE, nem
     INSERT) — "perto o suficiente" não conta.
  2. Escrita: se retornar TRACKING_MISSING_ONLY, a transação escrita é
     EXATAMENTE CREATE TABLE IF NOT EXISTS + 3 INSERTs (checksums
     derivados do arquivo em disco, nunca aceitos como input), tudo dentro
     de UM `conn.transaction()` — mesmo contrato de atomicidade do resto
     do runner.

`diagnose_database()` em si (as queries reais contra 000/001/002) é
mockada aqui — a classificação pura já tem cobertura própria em
test_diagnose_classification.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"
sys.path.insert(0, str(MIGRATIONS_DIR))
import runner  # noqa: E402  (import após sys.path.insert, é intencional)

# Host reconhecido como o project ref Homolog por verify_homolog_admin_dsn
# (core/cognitive/cognitive/config/db_target.py) — string de DSN só, nunca
# conecta de verdade.
HOMOLOG_DSN = "postgresql://cognitive_admin:fake-not-a-real-secret@db.esvjfkknrzzziafovwrv.supabase.co:5432/postgres"
FORBIDDEN_PROD_DSN = "postgresql://cognitive_admin:fake-not-a-real-secret@db.wioorhtdwnfujkrynxij.supabase.co:5432/postgres"
NON_HOMOLOG_DSN = "postgresql://user:pass@localhost:5440/cognitive_dev"


class FakeTransaction:
    """Mesmo shape de test_runner_atomicity.py::FakeTransaction — registra
    BEGIN/COMMIT/ROLLBACK, nunca engole exceção."""

    def __init__(self, log: list[str]):
        self._log = log

    async def __aenter__(self):
        self._log.append("BEGIN")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._log.append("ROLLBACK" if exc_type else "COMMIT")
        return False


class FakeConn:
    def __init__(self):
        self.log: list[str] = []
        self.execute_calls: list[tuple[str, tuple]] = []
        self.fetchval_calls: list[str] = []

    def transaction(self):
        return FakeTransaction(self.log)

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))
        self.log.append(f"EXEC[{len(self.execute_calls)}]")

    async def fetchval(self, query, *args):
        self.fetchval_calls.append(query)
        return None

    async def fetch(self, query, *args):
        return []


def _make_diagnosis(verdict: str) -> runner.DiagnosisResult:
    return runner.DiagnosisResult(
        verdict=verdict,
        signals_000=dict(runner.EXPECTED_PRESENT_000),
        signals_001=dict(runner.EXPECTED_PRESENT_001),
        signals_002=dict(runner.EXPECTED_APPLIED["002"]),
        tracked={"000": None, "001": None, "002": None},
    )


@pytest.mark.asyncio
class TestRecoverTrackingRefusesUnsafeVerdicts:
    @pytest.mark.parametrize(
        "verdict",
        ["SCHEMA_PARTIAL", "UNKNOWN_UNSAFE_STATE"],
    )
    async def test_refuses_to_write_when_verdict_is_not_tracking_missing_only(
        self, monkeypatch, verdict
    ):
        conn = FakeConn()

        async def fake_diagnose(_conn):
            return _make_diagnosis(verdict)

        monkeypatch.setattr(runner, "diagnose_database", fake_diagnose)

        with pytest.raises(SystemExit) as exc_info:
            await runner.run_recover_tracking(conn, HOMOLOG_DSN)

        assert exc_info.value.code == 1
        assert conn.execute_calls == []
        assert conn.log == []  # nenhuma transação sequer foi aberta

    async def test_refuses_gracefully_when_already_healthy_no_error(self, monkeypatch):
        """Idempotência: rodar --recover-tracking numa base já HEALTHY não
        deve ser tratado como erro — é um no-op esperado (ex: segunda
        chamada logo após uma recuperação bem-sucedida)."""
        conn = FakeConn()

        async def fake_diagnose(_conn):
            return _make_diagnosis("HEALTHY")

        monkeypatch.setattr(runner, "diagnose_database", fake_diagnose)

        # Não deve levantar SystemExit nem qualquer outra exceção.
        await runner.run_recover_tracking(conn, HOMOLOG_DSN)

        assert conn.execute_calls == []
        assert conn.log == []

    async def test_refuses_non_homolog_dsn_before_even_diagnosing(self, monkeypatch):
        """A guarda de alvo roda ANTES de diagnose_database() — nunca
        conecta/escreve num banco que não verifique como Homolog."""
        conn = FakeConn()
        diagnose_called = False

        async def fake_diagnose(_conn):
            nonlocal diagnose_called
            diagnose_called = True
            return _make_diagnosis("TRACKING_MISSING_ONLY")

        monkeypatch.setattr(runner, "diagnose_database", fake_diagnose)

        with pytest.raises(SystemExit) as exc_info:
            await runner.run_recover_tracking(conn, NON_HOMOLOG_DSN)

        assert exc_info.value.code == 1
        assert diagnose_called is False
        assert conn.execute_calls == []

    async def test_refuses_forbidden_production_ref(self, monkeypatch):
        conn = FakeConn()

        async def fake_diagnose(_conn):
            return _make_diagnosis("TRACKING_MISSING_ONLY")

        monkeypatch.setattr(runner, "diagnose_database", fake_diagnose)

        with pytest.raises(SystemExit) as exc_info:
            await runner.run_recover_tracking(conn, FORBIDDEN_PROD_DSN)

        assert exc_info.value.code == 1
        assert conn.execute_calls == []


@pytest.mark.asyncio
class TestRecoverTrackingWritesWhenSafe:
    async def test_writes_exactly_create_table_and_three_inserts_in_one_transaction(
        self, monkeypatch
    ):
        conn = FakeConn()

        async def fake_diagnose(_conn):
            return _make_diagnosis("TRACKING_MISSING_ONLY")

        monkeypatch.setattr(runner, "diagnose_database", fake_diagnose)

        await runner.run_recover_tracking(conn, HOMOLOG_DSN)

        # Uma única transação: BEGIN, 4 EXEC (1 CREATE TABLE + 3 INSERT), COMMIT.
        assert conn.log == ["BEGIN", "EXEC[1]", "EXEC[2]", "EXEC[3]", "EXEC[4]", "COMMIT"]
        assert len(conn.execute_calls) == 4

        create_query, _ = conn.execute_calls[0]
        assert "CREATE TABLE IF NOT EXISTS _migrations" in create_query

        insert_queries = conn.execute_calls[1:]
        expected_versions = {
            "000_foundation_tenancy",
            "001_capability_registry_audit",
            "002_service_identities_lookup_least_privilege",
        }
        seen_versions = set()
        for query, args in insert_queries:
            assert "INSERT INTO _migrations" in query
            assert "ON CONFLICT" in query
            assert "DO NOTHING" in query
            version, checksum = args
            seen_versions.add(version)
            # Checksum sempre derivado do arquivo em disco AGORA — nunca
            # aceito como input do operador — e precisa bater com
            # file_checksum() do arquivo real.
            path = dict(runner.MIGRATIONS)[version]
            assert checksum == runner.file_checksum(path)

        assert seen_versions == expected_versions

    async def test_checksums_are_freshly_derived_not_reused_across_calls(self, monkeypatch):
        """Garantia adicional: nada no caminho de recuperação aceita um
        checksum vindo de fora — cada INSERT usa file_checksum(path)
        calculado na hora a partir do MIGRATIONS_DIR real."""
        conn = FakeConn()

        async def fake_diagnose(_conn):
            return _make_diagnosis("TRACKING_MISSING_ONLY")

        monkeypatch.setattr(runner, "diagnose_database", fake_diagnose)

        await runner.run_recover_tracking(conn, HOMOLOG_DSN)

        checksum_by_version = {
            version: path for version, path in runner.MIGRATIONS
        }
        for query, args in conn.execute_calls[1:]:
            version, checksum = args
            expected = runner.file_checksum(checksum_by_version[version])
            assert checksum == expected
