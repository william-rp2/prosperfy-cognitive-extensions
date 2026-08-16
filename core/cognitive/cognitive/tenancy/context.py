"""
tenancy/context.py — Construção e validação do ActorContext a partir de headers HTTP.

ADR-V2-002: identidade vem exclusivamente de headers, nunca do body.
Middleware do Gateway chama build_actor_context() antes de qualquer handler.
"""

from __future__ import annotations

import hashlib
import uuid

from ..contracts.tenancy import ActorContext


# Credenciais registradas: credential_value → (tenant_id, actor_id, profile)
# Sprint 0.1: in-memory estático. Sprint 0.4+: service_identities no banco.
_STATIC_CREDENTIALS: dict[str, tuple[str, str, str]] = {}


def register_static_credential(
    credential: str,
    tenant_id: str,
    actor_id: str,
    profile: str = "owner-core",
) -> None:
    """Registra uma credential estática (uso em dev/testes)."""
    _STATIC_CREDENTIALS[credential] = (tenant_id, actor_id, profile)


def build_actor_context(
    authorization: str | None,
    x_tenant_id: str | None,
    x_actor_id: str | None,
    x_correlation_id: str | None,
) -> ActorContext:
    """
    Constrói ActorContext a partir dos headers HTTP.

    Raises:
        ValueError: se headers obrigatórios estiverem ausentes ou credencial inválida.
    """
    if not authorization:
        raise ValueError("Header Authorization ausente")
    if not x_tenant_id:
        raise ValueError("Header X-Tenant-Id ausente")
    if not x_actor_id:
        raise ValueError("Header X-Actor-Id ausente")

    # Extrair Bearer token
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise ValueError("Authorization deve ser 'Bearer <credential>'")
    credential = parts[1].strip()

    # Verificar credencial
    if credential not in _STATIC_CREDENTIALS:
        raise ValueError("Credencial inválida ou não autorizada")

    reg_tenant, reg_actor, profile = _STATIC_CREDENTIALS[credential]

    # Validar que tenant/actor declarados em header batem com a credential
    if reg_tenant != x_tenant_id:
        raise ValueError("X-Tenant-Id não corresponde à credencial")
    if reg_actor != x_actor_id:
        raise ValueError("X-Actor-Id não corresponde à credencial")

    correlation_id = x_correlation_id or str(uuid.uuid4())

    # credential_ref: hash da credential — nunca o valor original (R14)
    credential_ref = hashlib.sha256(credential.encode()).hexdigest()[:16]

    return ActorContext(
        tenant_id=reg_tenant,
        actor_id=reg_actor,
        correlation_id=correlation_id,
        credential_ref=credential_ref,
        profile=profile,
    )
