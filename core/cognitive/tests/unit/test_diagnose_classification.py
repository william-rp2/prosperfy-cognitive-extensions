"""
tests/unit/test_diagnose_classification.py — classify_diagnosis() puro,
sem Postgres real e sem sequer FakeConn (a lógica de classificação não
recebe conexão — só sinais já coletados, exatamente como a separação
CLEAN/PARTIAL/APPLIED em inspect_migration()).

Contexto: um teste destrutivo derrubou `_migrations` num run real contra
Homolog depois de 000/001/002 terem aplicado com sucesso. `--diagnose`
determina o estado real do schema (tabelas, roles, RLS) independente de
`_migrations`, e `classify_diagnosis()` decide o veredito a partir desses
sinais + do estado de tracking observado.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"
sys.path.insert(0, str(MIGRATIONS_DIR))
import runner  # noqa: E402  (import após sys.path.insert, é intencional)


def _present_000() -> dict[str, bool]:
    return dict(runner.EXPECTED_PRESENT_000)


def _absent_000() -> dict[str, bool]:
    return {k: False for k in runner.EXPECTED_PRESENT_000}


def _present_001() -> dict[str, bool]:
    return dict(runner.EXPECTED_PRESENT_001)


def _absent_001() -> dict[str, bool]:
    return {k: False for k in runner.EXPECTED_PRESENT_001}


def _partial_001() -> dict[str, bool]:
    """Nem totalmente ausente, nem totalmente presente — ex: tabelas
    existem mas RLS ainda não foi habilitada em todas, ou vice-versa."""
    signals = _absent_001()
    first_key = next(iter(signals))
    signals[first_key] = True
    return signals


def _fully_tracked() -> dict[str, bool | None]:
    return {"000": True, "001": True, "002": True}


def _tracking_missing() -> dict[str, bool | None]:
    return {"000": None, "001": None, "002": None}


class TestClassifyDiagnosisHealthy:
    def test_all_present_and_all_tracked_with_matching_checksum_is_healthy(self):
        verdict = runner.classify_diagnosis(
            signals_000=_present_000(),
            signals_001=_present_001(),
            signals_002=dict(runner.EXPECTED_APPLIED["002"]),
            tracked=_fully_tracked(),
        )
        assert verdict == "HEALTHY"


class TestClassifyDiagnosisTrackingMissingOnly:
    def test_schema_intact_but_migrations_table_missing_is_tracking_missing_only(self):
        """Reproduz o incidente real: 000/001/002 comprovadamente
        aplicadas (schema/roles/RLS intactos), mas _migrations foi
        derrubada por um teste destrutivo — nenhuma linha de tracking pra
        nenhuma das três."""
        verdict = runner.classify_diagnosis(
            signals_000=_present_000(),
            signals_001=_present_001(),
            signals_002=dict(runner.EXPECTED_APPLIED["002"]),
            tracked=_tracking_missing(),
        )
        assert verdict == "TRACKING_MISSING_ONLY"

    def test_is_the_only_verdict_distinct_from_healthy_when_schema_matches(self):
        healthy = runner.classify_diagnosis(
            _present_000(), _present_001(), dict(runner.EXPECTED_APPLIED["002"]), _fully_tracked()
        )
        missing = runner.classify_diagnosis(
            _present_000(), _present_001(), dict(runner.EXPECTED_APPLIED["002"]), _tracking_missing()
        )
        assert healthy == "HEALTHY"
        assert missing == "TRACKING_MISSING_ONLY"
        assert healthy != missing


class TestClassifyDiagnosisSchemaPartial:
    def test_000_complete_001_mixed_is_schema_partial(self):
        verdict = runner.classify_diagnosis(
            signals_000=_present_000(),
            signals_001=_partial_001(),
            signals_002=dict(runner.EXPECTED_CLEAN["002"]),
            tracked=_tracking_missing(),
        )
        assert verdict == "SCHEMA_PARTIAL"


class TestClassifyDiagnosisMigration002Missing:
    def test_000_and_001_present_002_exactly_clean_is_migration_002_missing(self):
        """002 nunca rodou — estado normal e seguro, não corrupção."""
        verdict = runner.classify_diagnosis(
            signals_000=_present_000(),
            signals_001=_present_001(),
            signals_002=dict(runner.EXPECTED_CLEAN["002"]),
            tracked=_tracking_missing(),
        )
        assert verdict == "MIGRATION_002_MISSING"

    def test_independent_of_tracking_state(self):
        """002 nunca rodou -> nunca deveria estar rastreada mesmo — o
        veredito não depende do dict `tracked` neste caso."""
        verdict_a = runner.classify_diagnosis(
            _present_000(), _present_001(), dict(runner.EXPECTED_CLEAN["002"]), _tracking_missing()
        )
        verdict_b = runner.classify_diagnosis(
            _present_000(), _present_001(), dict(runner.EXPECTED_CLEAN["002"]),
            {"000": True, "001": True, "002": None},
        )
        assert verdict_a == "MIGRATION_002_MISSING"
        assert verdict_b == "MIGRATION_002_MISSING"


class TestClassifyDiagnosisUnknownUnsafeState:
    def test_000_not_present_is_unsafe_catch_all(self):
        """000 nem completo nem no formato de nenhum outro veredito
        nomeado — fail-closed."""
        verdict = runner.classify_diagnosis(
            signals_000=_absent_000(),
            signals_001=_absent_001(),
            signals_002=dict(runner.EXPECTED_CLEAN["002"]),
            tracked=_tracking_missing(),
        )
        assert verdict == "UNKNOWN_UNSAFE_STATE"

    def test_full_schema_but_mixed_tracking_state_is_unsafe(self):
        """Schema 100% intacto, mas tracking num estado misto (uma
        migration rastreada certa, outra sem linha nenhuma) — não é
        HEALTHY (nem tudo bate) nem TRACKING_MISSING_ONLY (não é tudo
        ausente). Fail-closed: precisa de revisão humana."""
        verdict = runner.classify_diagnosis(
            signals_000=_present_000(),
            signals_001=_present_001(),
            signals_002=dict(runner.EXPECTED_APPLIED["002"]),
            tracked={"000": True, "001": None, "002": True},
        )
        assert verdict == "UNKNOWN_UNSAFE_STATE"

    def test_full_schema_but_checksum_mismatch_is_unsafe(self):
        """Linha de tracking existe pras três, mas o checksum de uma não
        bate com o arquivo em disco atual — não é seguro chamar isso de
        HEALTHY."""
        verdict = runner.classify_diagnosis(
            signals_000=_present_000(),
            signals_001=_present_001(),
            signals_002=dict(runner.EXPECTED_APPLIED["002"]),
            tracked={"000": True, "001": True, "002": False},
        )
        assert verdict == "UNKNOWN_UNSAFE_STATE"

    def test_002_neither_clean_nor_applied_with_000_001_present_is_unsafe(self):
        """000/001 completos, mas 002 num estado que não bate nem com
        CLEAN nem com APPLIED (residual/parcial genuíno) — mesma
        classificação PARTIAL que inspect_migration já usa pra esse tipo
        de sinal, mas no vocabulário de diagnose é o catch-all."""
        mixed_002 = dict(runner.EXPECTED_CLEAN["002"])
        # Flip um sinal só, pra não bater nem com CLEAN nem com APPLIED.
        first_key = next(iter(mixed_002))
        mixed_002[first_key] = not mixed_002[first_key]

        verdict = runner.classify_diagnosis(
            signals_000=_present_000(),
            signals_001=_present_001(),
            signals_002=mixed_002,
            tracked=_tracking_missing(),
        )
        assert verdict == "UNKNOWN_UNSAFE_STATE"
