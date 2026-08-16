"""
contracts/tenancy.py — Contratos de identidade multi-tenant do Cognitive Core V2.

Decisões congeladas em ADR-V2-002:
- Identidade vem exclusivamente de headers (X-Tenant-Id, X-Actor-Id, Authorization)
- tenant_id / actor_id NUNCA no body
- Resource é sempre lógico (ex: "prosperfy-main"), nunca IP/host arbitrário
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ActorContext:
    """
    Contexto imutável por request.

    Propagado integralmente para policy, audit, adapter e telemetry.
    Criado pelo middleware do Gateway e nunca modificado downstream.
    """
    tenant_id: str
    actor_id: str
    correlation_id: str
    credential_ref: str                        # hash/ref da credential — nunca o valor
    profile: str = "default"                  # bundle de grants (ex: "owner-core", "infra-read")
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("tenant_id é obrigatório")
        if not self.actor_id:
            raise ValueError("actor_id é obrigatório")
        if not self.correlation_id:
            raise ValueError("correlation_id é obrigatório")


@dataclass(frozen=True)
class TenantResource:
    """
    Recurso lógico tenant-scoped.

    O cliente passa resource_key (ex: "prosperfy-main").
    O ResourceResolver converte para parâmetros concretos (host, project ref, etc.)
    que seguem para o adapter — nunca expostos ao cliente.
    """
    tenant_id: str
    resource_key: str                          # identificador lógico
    resource_type: str                         # "vps" | "mailbox" | "supabase-project" | ...
    resolved_params: dict[str, Any] = field(default_factory=dict)   # preenchido pelo resolver


@dataclass
class CapabilityGrant:
    """
    Autorização de um profile/actor para uma capability.

    In-memory Sprint 0.1: carregado de configuração estática.
    Sprint 0.2+: persiste em banco com RLS.
    """
    tenant_id: str
    profile: str
    capability_id: str
    policy_override: str | None = None         # sobrescreve default_policy do YAML se definido
