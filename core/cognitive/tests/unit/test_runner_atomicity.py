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

    # Mapeia cada nome de sinal cadastrado em INSPECTION_QUERIES["002"] pra
    # um trecho da própria query que o identifica de forma única — permite
    # simular fetchval() por SINAL (não por ordem de chamada), robusto a
    # reordenar INSPECTION_QUERIES no futuro. Isso é o que faltava no gap
    # apontado pela revisão adversarial: o teste anterior simulava "1º
    # sinal true, resto false" (um `any()` uniforme), que nunca reproduzia
    # o estado real pré-002 — onde os DOIS ÚLTIMOS sinais (herdados de 001)
    # já são True e os três primeiros False.
    SIGNAL_MARKERS = {
        "function_exists": "IS NOT NULL AS v",
        "function_owner_is_not_app_or_worker": "pg_has_role('cognitive_app'",
        "public_has_execute_on_function": "has_function_privilege('public'",
        "cognitive_app_has_direct_select_on_table": "has_table_privilege",
        "old_tenant_isolation_policy_exists": "pg_policies",
    }

    def _fetchval_returning(self, signal_values: dict[str, bool]):
        async def fake_fetchval(query, *args):
            for name, marker in self.SIGNAL_MARKERS.items():
                if marker in query:
                    return signal_values[name]
            raise AssertionError(f"query não reconhecida por nenhum marcador: {query}")
        return fake_fetchval

    async def test_tracked_is_always_applied(self, monkeypatch):
        """_migrations.version grava o STEM COMPLETO (ver
        apply_one_migration) — o fake precisa refletir isso, não o
        prefixo curto "002" (esse era exatamente o bug de normalização
        corrigido em resolve_migration_version/inspect_migration: comparar
        "002" cru contra o stem completo sempre dava tracked=False)."""
        conn = FakeConn()

        async def fake_get_applied(_conn):
            return {"002_service_identities_lookup_least_privilege": "abc123"}

        monkeypatch.setattr(runner, "get_applied", fake_get_applied)
        verdict = await runner.inspect_migration(conn, "002")
        assert verdict == "APPLIED"

    async def test_clean_state_matches_post_001_pre_002_fingerprint(self, monkeypatch):
        """Estado real pré-002 (só 001 aplicada): function_exists=False,
        MAS cognitive_app_has_direct_select_on_table=True e
        old_tenant_isolation_policy_exists=True (herdados de 001). Esse é
        o cenário exato que a revisão adversarial achou classificado
        errado como PARTIAL antes desta correção."""
        conn = FakeConn()

        async def fake_get_applied(_conn):
            return {}

        monkeypatch.setattr(runner, "get_applied", fake_get_applied)
        monkeypatch.setattr(conn, "fetchval", self._fetchval_returning({
            "function_exists": False,
            "function_owner_is_not_app_or_worker": False,
            "public_has_execute_on_function": False,
            "cognitive_app_has_direct_select_on_table": True,
            "old_tenant_isolation_policy_exists": True,
        }))
        verdict = await runner.inspect_migration(conn, "002")
        assert verdict == "CLEAN"

    async def test_fully_applied_signals_without_tracking_is_applied_but_untracked(self, monkeypatch):
        conn = FakeConn()

        async def fake_get_applied(_conn):
            return {}

        monkeypatch.setattr(runner, "get_applied", fake_get_applied)
        monkeypatch.setattr(conn, "fetchval", self._fetchval_returning({
            "function_exists": True,
            "function_owner_is_not_app_or_worker": True,
            "public_has_execute_on_function": False,
            "cognitive_app_has_direct_select_on_table": False,
            "old_tenant_isolation_policy_exists": False,
        }))
        verdict = await runner.inspect_migration(conn, "002")
        assert verdict == "APPLIED_BUT_UNTRACKED"

    async def test_genuinely_mixed_signals_is_partial(self, monkeypatch):
        """Combinação sintética de sinais que não bate com nenhum fingerprint
        conhecido — cobertura de robustez da classificação PARTIAL. Não é
        mais um cenário alcançável pela migration 002 atual (que não tem
        mais ALTER OWNER, e roda como uma única transação atômica — uma
        falha no meio reverte tudo, não deixa resíduo parcial); documenta
        um estado histórico (versão anterior do runner/migration) e serve
        de cinto-de-segurança caso a suposição de atomicidade do Postgres
        falhe por algum motivo não previsto."""
        conn = FakeConn()

        async def fake_get_applied(_conn):
            return {}

        monkeypatch.setattr(runner, "get_applied", fake_get_applied)
        monkeypatch.setattr(conn, "fetchval", self._fetchval_returning({
            "function_exists": True,
            "function_owner_is_not_app_or_worker": False,
            "public_has_execute_on_function": True,  # default do Postgres pra função nova
            "cognitive_app_has_direct_select_on_table": True,
            "old_tenant_isolation_policy_exists": True,
        }))
        verdict = await runner.inspect_migration(conn, "002")
        assert verdict == "PARTIAL"

    async def test_unrecognized_version_is_invalid(self, monkeypatch):
        """"999_nonexistent" não bate com nenhum arquivo real em MIGRATIONS
        — desde a correção de normalização (resolve_migration_version),
        isso é INVALID_VERSION (fail-closed), não mais um fallback
        silencioso pra UNKNOWN. UNKNOWN continua reservado pra uma
        migration REAL sem fingerprint cadastrado (ex: 000/001) e não
        rastreada — ver test_inspect_normalization.py."""
        conn = FakeConn()

        async def fake_get_applied(_conn):
            return {}

        monkeypatch.setattr(runner, "get_applied", fake_get_applied)
        verdict = await runner.inspect_migration(conn, "999_nonexistent")
        assert verdict == "INVALID_VERSION"
