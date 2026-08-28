"""
tests/unit/test_registry_loader.py — Testes do Registry e loader YAML.
"""

from __future__ import annotations

from pathlib import Path

from cognitive.registry.loader import load_all_capabilities, load_capability_yaml
from cognitive.registry.registry import InMemoryCapabilityRegistry
from cognitive.contracts.tenancy import CapabilityGrant


def test_load_infra_inspect_yaml():
    """infra.inspect deve estar presente nas capabilities YAML."""
    caps = load_all_capabilities()
    ids = [c.id for c in caps]
    assert "infra.inspect" in ids


def test_infra_inspect_fields():
    caps = load_all_capabilities()
    cap = next(c for c in caps if c.id == "infra.inspect")
    assert cap.domain == "infrastructure"
    assert cap.default_policy == "allow"
    assert cap.adapter == "prosperfy_skills"
    assert len(cap.tools) > 0


def test_registry_get_existing():
    registry = InMemoryCapabilityRegistry()
    registry.load_from_yaml()
    cap = registry.get("infra.inspect")
    assert cap is not None
    assert cap.id == "infra.inspect"


def test_registry_get_missing():
    registry = InMemoryCapabilityRegistry()
    registry.load_from_yaml()
    assert registry.get("nonexistent.cap") is None


def test_registry_grant_resolution():
    registry = InMemoryCapabilityRegistry()
    registry.load_from_yaml()
    registry.register_grant(CapabilityGrant(
        tenant_id="tenant-a",
        profile="owner-core",
        capability_id="infra.inspect",
    ))

    grant = registry.resolve_grant("tenant-a", "owner-core", "infra.inspect")
    assert grant is not None
    assert grant.tenant_id == "tenant-a"


def test_registry_grant_not_found_other_tenant():
    """Tenant B não deve receber o grant de tenant A."""
    registry = InMemoryCapabilityRegistry()
    registry.load_from_yaml()
    registry.register_grant(CapabilityGrant(
        tenant_id="tenant-a",
        profile="owner-core",
        capability_id="infra.inspect",
    ))

    grant = registry.resolve_grant("tenant-b", "owner-core", "infra.inspect")
    assert grant is None


# ─── Track BH: browser.read / browser.act / browser.account ────────────────

def test_load_browser_capabilities_yaml():
    caps = load_all_capabilities()
    ids = {c.id for c in caps}
    assert {"browser.read", "browser.act", "browser.account"} <= ids


def test_browser_read_is_allow_by_default():
    caps = load_all_capabilities()
    cap = next(c for c in caps if c.id == "browser.read")
    assert cap.default_policy == "allow"
    assert cap.adapter == "browser_harness"
    assert cap.tools[0]["name"] == "browser_read_links"


def test_browser_act_and_account_are_deny_by_default():
    """doc 00: browser.act/browser.account default_policy=deny -- grant
    explicito obrigatorio (matriz 6.2 e enforced no worker, nao aqui)."""
    caps = load_all_capabilities()
    by_id = {c.id: c for c in caps}
    assert by_id["browser.act"].default_policy == "deny"
    assert by_id["browser.account"].default_policy == "deny"
    assert by_id["browser.act"].adapter == "browser_harness"
    assert by_id["browser.account"].adapter == "browser_harness"


def test_browser_capabilities_redact_secret_like_fields():
    caps = load_all_capabilities()
    for cap_id in ("browser.read", "browser.act", "browser.account"):
        cap = next(c for c in caps if c.id == cap_id)
        for field in ("password", "token", "secret", "cookie", "authorization"):
            assert field in cap.redaction_rules, f"{cap_id} missing redaction for {field}"


def test_browser_act_without_grant_denies_by_registry():
    """Sem grant, browser.act nao aparece resolvivel mesmo com default_policy
    lido do YAML -- mesma semantica de infra.action (DENY [no_grant])."""
    registry = InMemoryCapabilityRegistry()
    registry.load_from_yaml()
    assert registry.resolve_grant("tenant-a", "owner-core", "browser.act") is None
