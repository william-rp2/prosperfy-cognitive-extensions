"""
tests/unit/test_inspect_normalization.py — resolve_migration_version() e a
normalização de versão em --inspect, sem Postgres real (mocka a conexão).

Bug corrigido: `_migrations.version` grava o STEM COMPLETO do arquivo (ex:
"002_service_identities_lookup_least_privilege" — ver
apply_one_migration()/get_applied() em runner.py), mas
INSPECTION_QUERIES/EXPECTED_CLEAN/EXPECTED_APPLIED são indexados pelo
prefixo curto ("002"), e `inspect_migration(conn, version)` comparava
`version in applied` usando a string crua passada em --inspect. Rodar
`--inspect 002` com a migration 002 de fato rastreada dava tracked=False
(comparando "002" contra "002_service_identities_lookup_least_privilege"),
produzindo um veredito silenciosamente errado.

`resolve_migration_version()` resolve short-prefix ou stem completo pro
stem canônico, fail-closed (levanta ValueError) pra qualquer coisa que não
bata com exatamente um arquivo real em MIGRATIONS — nunca "adivinha".
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"
sys.path.insert(0, str(MIGRATIONS_DIR))
import runner  # noqa: E402  (import após sys.path.insert, é intencional)


class FakeConn:
    """Mesmo estilo do FakeConn em test_runner_atomicity.py — só o
    suficiente pra inspect_migration() rodar sem Postgres real."""

    def __init__(self):
        self.execute_calls: list[str] = []

    async def execute(self, query, *args):
        self.execute_calls.append(query)

    async def fetchval(self, query, *args):
        return None

    async def fetch(self, query, *args):
        return []


class TestResolveMigrationVersion:
    def test_exact_full_stem_match(self):
        assert (
            runner.resolve_migration_version(
                "002_service_identities_lookup_least_privilege"
            )
            == "002_service_identities_lookup_least_privilege"
        )

    def test_unique_short_prefix_002(self):
        assert (
            runner.resolve_migration_version("002")
            == "002_service_identities_lookup_least_privilege"
        )

    def test_unique_short_prefix_000(self):
        assert runner.resolve_migration_version("000") == "000_foundation_tenancy"

    def test_unique_short_prefix_001(self):
        assert runner.resolve_migration_version("001") == "001_capability_registry_audit"

    def test_nonexistent_version_raises(self):
        with pytest.raises(ValueError, match="desconhecida"):
            runner.resolve_migration_version("nonexistent_version_xyz")

    def test_ambiguous_prefix_0_raises(self):
        """"0" prefix-bate com "000_...", "001_..." E "002_..." ao mesmo
        tempo (todos começam com "0") — isso DEVE ser recusado como
        ambíguo, nunca silenciosamente resolvido pro primeiro match."""
        with pytest.raises(ValueError, match="[Aa]mb[ií]gu"):
            runner.resolve_migration_version("0")

    def test_whitespace_is_stripped(self):
        assert (
            runner.resolve_migration_version("  002  ")
            == "002_service_identities_lookup_least_privilege"
        )


@pytest.mark.asyncio
class TestInspectMigrationNormalization:
    """Cobre os casos obrigatórios do Problem A: short prefix, stem
    completo, 000/001 sem fingerprint, versão inexistente, prefixo
    ambíguo — todos precisam produzir o mesmo veredito
    independentemente de qual forma de versão o operador digitou."""

    async def test_short_prefix_002_and_full_stem_002_agree_when_tracked(self, monkeypatch):
        conn = FakeConn()

        async def fake_get_applied(_conn):
            return {"002_service_identities_lookup_least_privilege": "abc123"}

        monkeypatch.setattr(runner, "get_applied", fake_get_applied)

        verdict_short = await runner.inspect_migration(conn, "002")
        verdict_full = await runner.inspect_migration(
            conn, "002_service_identities_lookup_least_privilege"
        )
        assert verdict_short == "APPLIED"
        assert verdict_full == "APPLIED"

    async def test_short_prefix_002_and_full_stem_002_agree_when_untracked_clean(self, monkeypatch):
        """Antes da correção, --inspect 002 com a migration de fato
        rastreada dava tracked=False (comparação de string crua) — o
        oposto do que este teste cobre não é o ponto; o ponto é que as
        DUAS formas de digitar a versão têm que concordar sempre."""
        conn = FakeConn()

        async def fake_get_applied(_conn):
            return {}

        monkeypatch.setattr(runner, "get_applied", fake_get_applied)

        clean_signals = {
            "function_exists": False,
            "function_owner_is_not_app_or_worker": False,
            "public_has_execute_on_function": False,
            "cognitive_app_has_direct_select_on_table": True,
            "old_tenant_isolation_policy_exists": True,
        }
        markers = {
            "function_exists": "IS NOT NULL AS v",
            "function_owner_is_not_app_or_worker": "pg_has_role('cognitive_app'",
            "public_has_execute_on_function": "has_function_privilege('public'",
            "cognitive_app_has_direct_select_on_table": "has_table_privilege",
            "old_tenant_isolation_policy_exists": "pg_policies",
        }

        async def fake_fetchval(query, *args):
            for name, marker in markers.items():
                if marker in query:
                    return clean_signals[name]
            raise AssertionError(f"query não reconhecida: {query}")

        monkeypatch.setattr(conn, "fetchval", fake_fetchval)

        verdict_short = await runner.inspect_migration(conn, "002")
        verdict_full = await runner.inspect_migration(
            conn, "002_service_identities_lookup_least_privilege"
        )
        assert verdict_short == "CLEAN"
        assert verdict_full == "CLEAN"

    async def test_inspect_000_untracked_no_fingerprint_is_unknown(self, monkeypatch):
        """000 não tem fingerprint cadastrado em INSPECTION_QUERIES (só
        002 tem) — normalização precisa resolver "000" pro stem canônico e
        então cair no fallback existente (sem fingerprint -> UNKNOWN se
        não rastreada), sem regressão."""
        conn = FakeConn()

        async def fake_get_applied(_conn):
            return {}

        monkeypatch.setattr(runner, "get_applied", fake_get_applied)
        verdict = await runner.inspect_migration(conn, "000")
        assert verdict == "UNKNOWN"

    async def test_inspect_000_tracked_no_fingerprint_is_applied(self, monkeypatch):
        conn = FakeConn()

        async def fake_get_applied(_conn):
            return {"000_foundation_tenancy": "def456"}

        monkeypatch.setattr(runner, "get_applied", fake_get_applied)
        verdict = await runner.inspect_migration(conn, "000")
        assert verdict == "APPLIED"

    async def test_inspect_001_untracked_no_fingerprint_is_unknown(self, monkeypatch):
        conn = FakeConn()

        async def fake_get_applied(_conn):
            return {}

        monkeypatch.setattr(runner, "get_applied", fake_get_applied)
        verdict = await runner.inspect_migration(conn, "001")
        assert verdict == "UNKNOWN"

    async def test_inspect_001_tracked_no_fingerprint_is_applied(self, monkeypatch):
        conn = FakeConn()

        async def fake_get_applied(_conn):
            return {"001_capability_registry_audit": "ghi789"}

        monkeypatch.setattr(runner, "get_applied", fake_get_applied)
        verdict = await runner.inspect_migration(conn, "001")
        assert verdict == "APPLIED"

    async def test_inspect_nonexistent_version_is_invalid(self, monkeypatch):
        conn = FakeConn()

        async def fake_get_applied(_conn):
            return {}

        monkeypatch.setattr(runner, "get_applied", fake_get_applied)
        verdict = await runner.inspect_migration(conn, "nonexistent_version_xyz")
        assert verdict == "INVALID_VERSION"
        # Versão inválida é detectada ANTES de qualquer acesso ao banco —
        # nem ensure_migrations_table (write) nem get_applied são chamados.
        assert conn.execute_calls == []

    async def test_inspect_ambiguous_prefix_0_is_invalid(self, monkeypatch):
        conn = FakeConn()

        async def fake_get_applied(_conn):
            return {}

        monkeypatch.setattr(runner, "get_applied", fake_get_applied)
        verdict = await runner.inspect_migration(conn, "0")
        assert verdict == "INVALID_VERSION"
        assert conn.execute_calls == []

    async def test_invalid_version_is_distinct_from_unknown(self, monkeypatch):
        """INVALID_VERSION (versão não reconhecida) e UNKNOWN (migration
        real, sem fingerprint cadastrado, não rastreada) são falhas
        DIFERENTES — a matriz de CLI precisa distingui-las, não
        conflacioná-las num único "não sei"."""
        conn = FakeConn()

        async def fake_get_applied(_conn):
            return {}

        monkeypatch.setattr(runner, "get_applied", fake_get_applied)

        invalid_verdict = await runner.inspect_migration(conn, "nonexistent_version_xyz")
        unknown_verdict = await runner.inspect_migration(conn, "000")

        assert invalid_verdict == "INVALID_VERSION"
        assert unknown_verdict == "UNKNOWN"
        assert invalid_verdict != unknown_verdict
