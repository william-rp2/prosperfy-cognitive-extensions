"""
registry/loader.py — Carrega definições de capability de arquivos YAML.

ADR-V2-005: definição de capability é código/YAML versionado no repositório.
O banco NÃO é source of truth para definições — apenas para grants e runtime data.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from ..contracts.capability import IdempotencyBehavior, RegisteredCapability

# Diretório padrão de capabilities
_CAPABILITIES_DIR = Path(__file__).parent / "capabilities"


def load_capability_yaml(path: Path) -> RegisteredCapability:
    """Carrega e valida uma definição de capability de um arquivo YAML."""
    with open(path, encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f)

    return RegisteredCapability(
        id=raw["id"],
        version=raw.get("version", "1.0.0"),
        domain=raw.get("domain", "other"),
        description=raw.get("description", ""),
        adapter=raw.get("adapter", "prosperfy_skills"),
        default_policy=raw.get("default_policy", "deny"),
        required_scopes=raw.get("required_scopes", []),
        input_schema=raw.get("input_schema", {}),
        output_schema=raw.get("output_schema", {}),
        idempotency_behavior=IdempotencyBehavior(
            raw.get("idempotency_behavior", "return_cached")
        ),
        timeout_seconds=raw.get("timeout_seconds", 30),
        cost_class=raw.get("cost_class", "low"),
        audit_rules=raw.get("audit_rules", {}),
        redaction_rules=raw.get("redaction_rules", []),
        tools=raw.get("tools", []),
    )


def load_all_capabilities(directory: Path | None = None) -> list[RegisteredCapability]:
    """Carrega todas as capabilities YAML do diretório configurado."""
    dir_path = directory or _CAPABILITIES_DIR
    capabilities = []
    for yaml_file in sorted(dir_path.glob("*.yaml")):
        cap = load_capability_yaml(yaml_file)
        capabilities.append(cap)
    return capabilities
