"""
registry/registry.py — CapabilityRegistry in-memory.

Sprint 0.1: Registry carregado de YAML em memória.
Sprint 0.2+: grants e bundles persistidos em Postgres; definições continuam no YAML.
"""

from __future__ import annotations

from ..contracts.capability import CapabilityRegistryPort, RegisteredCapability
from ..contracts.tenancy import CapabilityGrant
from .loader import load_all_capabilities


class InMemoryCapabilityRegistry:
    """
    Registry in-memory de capabilities e grants.

    Implementa CapabilityRegistryPort.
    Sprint 0.1: capabilities carregadas de YAML; grants de configuração estática.
    """

    def __init__(self) -> None:
        self._capabilities: dict[str, RegisteredCapability] = {}
        self._grants: list[CapabilityGrant] = []

    def load_from_yaml(self) -> None:
        """Carrega todas as capabilities do diretório de YAML."""
        for cap in load_all_capabilities():
            self._capabilities[cap.id] = cap

    def register_grant(self, grant: CapabilityGrant) -> None:
        """Registra um grant de capability (in-memory)."""
        self._grants.append(grant)

    # ─── CapabilityRegistryPort ─────────────────────────────────────────

    def get(self, capability_id: str) -> RegisteredCapability | None:
        return self._capabilities.get(capability_id)

    def list_all(self) -> list[RegisteredCapability]:
        return list(self._capabilities.values())

    # ─── Grant resolution ────────────────────────────────────────────────

    def resolve_grant(
        self,
        tenant_id: str,
        profile: str,
        capability_id: str,
    ) -> CapabilityGrant | None:
        """
        Verifica se existe grant para (tenant, profile, capability).

        Retorna None se o tenant não possuir grant — deve resultar em DENY.
        """
        for grant in self._grants:
            if (
                grant.tenant_id == tenant_id
                and grant.capability_id == capability_id
                and grant.profile == profile
            ):
                return grant
        return None
