"""
tests/unit/test_finance_capabilities_registry.py — P2 (Financeiro pelo WhatsApp).

Confirma que as 10 capabilities finance.* do doc 00 §5 carregam do YAML com
o contrato esperado: domain=finance, adapter=finance_api, escopos e
default_policy corretos, e que material writes ficam claramente marcados
"write" enquanto reads ficam "read" (doc 00 §8 — nenhuma capability aqui
declara default_policy=deny nem permite excluir/editar bruto sem CONFIRM
fora da API).
"""

from __future__ import annotations

from cognitive.registry.registry import InMemoryCapabilityRegistry

EXPECTED_READ_CAPABILITIES = {
    "finance.summary.read",
    "finance.transactions.read",
    "finance.accounts.read",
    "finance.bills.read",
    "finance.budget.read",
    "finance.sync.status",
}
EXPECTED_WRITE_CAPABILITIES = {
    "finance.manual.create",
    "finance.category.update",
    "finance.budget.write",
    "finance.sync.run",
}
EXPECTED_ALL = EXPECTED_READ_CAPABILITIES | EXPECTED_WRITE_CAPABILITIES


def _registry() -> InMemoryCapabilityRegistry:
    registry = InMemoryCapabilityRegistry()
    registry.load_from_yaml()
    return registry


def test_all_ten_finance_capabilities_are_registered():
    registry = _registry()
    ids = {cap.id for cap in registry.list_all() if cap.id.startswith("finance.")}
    assert ids == EXPECTED_ALL


def test_every_finance_capability_uses_the_finance_api_adapter_and_finance_domain():
    registry = _registry()
    for cap_id in EXPECTED_ALL:
        cap = registry.get(cap_id)
        assert cap is not None, f"{cap_id} não carregou"
        assert cap.adapter == "finance_api"
        assert cap.domain == "finance"
        # Sem `tools:` — orchestrator invoca o adapter com tool_name=capability_id
        # diretamente (ver execution/orchestrator.py, ramo "capability simples").
        assert cap.tools == []


def test_read_capabilities_require_finance_read_scope():
    registry = _registry()
    for cap_id in EXPECTED_READ_CAPABILITIES:
        cap = registry.get(cap_id)
        assert cap.required_scopes == ["finance:read"], cap_id


def test_write_capabilities_require_finance_write_scope():
    registry = _registry()
    for cap_id in EXPECTED_WRITE_CAPABILITIES:
        cap = registry.get(cap_id)
        assert cap.required_scopes == ["finance:write"], cap_id


def test_all_finance_capabilities_default_to_allow():
    """
    doc 00 §8: lançamento manual, orçamento e reclassificação de transação
    identificada são ALLOW direto — nenhuma capability finance.* nasce
    default_policy=deny ou =confirm neste V1. CONFIRM/DENY (delete, editar
    valor/data material) vivem na Finance API (rota DELETE exige
    {"confirm": true}), não como uma capability separada aqui.
    """
    registry = _registry()
    for cap_id in EXPECTED_ALL:
        cap = registry.get(cap_id)
        assert cap.default_policy == "allow", cap_id


def test_manual_create_and_sync_run_reject_duplicate_idempotency_keys():
    """Efeitos colaterais reais (criar lançamento, disparar sync) nunca usam
    return_cached — um retry com a mesma Idempotency-Key deve ser rejeitado,
    não silenciosamente devolver o resultado antigo como se fosse novo."""
    registry = _registry()
    assert registry.get("finance.manual.create").idempotency_behavior.value == "reject"
    assert registry.get("finance.sync.run").idempotency_behavior.value == "reject"


def test_redaction_rules_present_on_every_finance_capability():
    registry = _registry()
    for cap_id in EXPECTED_ALL:
        cap = registry.get(cap_id)
        assert set(cap.redaction_rules) >= {"api_key", "password", "token", "secret"}, cap_id
