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
