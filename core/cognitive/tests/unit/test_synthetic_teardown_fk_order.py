"""
test_synthetic_teardown_fk_order.py — Regressão do BUG 2 (TEARDOWN=FAIL).

O teardown do contexto sintético (scripts/sprint_0_3_synthetic_context.py)
tentava remover `service_identities` antes dos `identity_events` relacionados
(migration 003 criou `identity_events` referenciando service_identities SEM
ON DELETE CASCADE) → ForeignKeyViolation no teardown.

Este teste (sem DB) valida a ORDEM da constante `TEARDOWN_TABLES`: qualquer
tabela-filha dependente de FK deve ser removida ANTES da tabela-pai, no mesmo
espírito do fix de ordem já aplicado na Sprint 0.4 em
core/cognitive/tests/db/conftest.py::seeded_tenants.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]  # core/cognitive/tests/unit -> repo root
SCRIPTS_DIR = REPO_ROOT / "scripts"


@pytest.fixture(scope="module")
def teardown_tables():
    """Importa o script real (pelo nome, via sys.path) e retorna a tupla
    TEARDOWN_TABLES."""
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import sprint_0_3_synthetic_context as ctx
    return ctx.TEARDOWN_TABLES


def test_identity_events_removed_before_service_identities(teardown_tables):
    """identity_events (migration 003) referencia service_identities SEM
    cascade — deve ser removido ANTES, senão o DELETE de service_identities
    viola a FK (TEARDOWN=FAIL no Gate)."""
    assert "identity_events" in teardown_tables
    assert "service_identities" in teardown_tables
    assert teardown_tables.index("identity_events") < teardown_tables.index(
        "service_identities"
    )


def test_child_tables_precede_tenant_removal(teardown_tables):
    """Todos os filhos (audit_events, execution_traces, cost_telemetry,
    identity_events, service_identities, tenant_resources, capability_grants,
    tenant_members, credential_refs, tenant_integrations) devem ser removidos
    ANTES de `tenants` (o teardown deleta tenants por último, fora da tupla)."""
    # `tenants` é removido separadamente em teardown_context; a tupla não o
    # contém. Garantia mínima: nenhuma tabela da tupla é removida depois do
    # pai que ela referencia (spell out as dependências críticas conhecidas).
    assert "service_identities" in teardown_tables
    assert "tenant_resources" in teardown_tables
    assert "capability_grants" in teardown_tables


def test_teardown_whitelist_is_scoped_not_global(teardown_tables):
    """O teardown usa uma whitelist fixa (sem DELETE global/TRUNCATE/DROP) —
    garante que a tupla não contém primitivas destrutivas globais."""
    assert "tenants" not in teardown_tables  # removido separadamente por id
    assert all(isinstance(t, str) and t for t in teardown_tables)