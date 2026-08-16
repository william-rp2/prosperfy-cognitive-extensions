"""
tenancy/identity_resolver.py — Resolução de identidade com suporte a DB e in-memory.

Sprint 0.1: identidade in-memory (static credentials).
Sprint 0.2: identidade via ServiceIdentityRepository (Postgres).

build_actor_context_db() é o novo entry point para o Gateway com DB.
Mantém retrocompatibilidade com build_actor_context() estático.
"""

from __future__ import annotations

import hashlib
import logging
import uuid

from ..contracts.tenancy import ActorContext

logger = logging.getLogger(__name__)


class IdentityResolver:
    """
    Resolve identidade do cliente (Bearer token → ActorContext).

    Sprint 0.2: usa ServiceIdentityRepository (DB).
    Fallback: static credentials in-memory se DB não disponível.
    """

    def __init__(self, identity_repo=None) -> None:
        """
        identity_repo: ServiceIdentityRepository ou None (fallback in-memory).
        """
        self._repo = identity_repo
        self._static: dict[str, tuple[str, str, str]] = {}  # credential → (tenant, actor, profile)

    def register_static(
        self, credential: str, tenant_id: str, actor_id: str, profile: str = "owner-core"
    ) -> None:
        """Registra credencial estática (dev/test sem DB)."""
        self._static[credential] = (tenant_id, actor_id, profile)

    async def resolve(
        self,
        authorization: str | None,
        x_tenant_id: str | None,
        x_actor_id: str | None,
        x_correlation_id: str | None,
    ) -> ActorContext:
        """
        Resolve ActorContext a partir dos headers.

        1. Extrai Bearer token
        2. Tenta DB lookup (se repo disponível)
        3. Fallback para static credentials
        4. Valida que tenant/actor dos headers correspondem ao registrado

        Levanta ValueError em qualquer falha de autenticação.
        """
        if not authorization:
            raise ValueError("Header Authorization ausente")
        if not x_tenant_id:
            raise ValueError("Header X-Tenant-Id ausente")
        if not x_actor_id:
            raise ValueError("Header X-Actor-Id ausente")

        parts = authorization.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise ValueError("Authorization deve ser 'Bearer <credential>'")
        credential = parts[1].strip()

        # Tentar DB lookup
        if self._repo is not None:
            try:
                identity = await self._repo.lookup(credential)
                if identity:
                    return self._build_context_from_db(
                        identity, x_tenant_id, x_actor_id, x_correlation_id, credential
                    )
            except Exception as exc:
                logger.warning("DB identity lookup falhou, tentando fallback: %s", exc)

        # Fallback: static credentials
        return self._build_context_from_static(
            credential, x_tenant_id, x_actor_id, x_correlation_id
        )

    def _build_context_from_db(
        self,
        identity,  # ServiceIdentityRow
        x_tenant_id: str,
        x_actor_id: str,
        x_correlation_id: str | None,
        credential: str,
    ) -> ActorContext:
        if identity.tenant_id != x_tenant_id:
            raise ValueError("X-Tenant-Id não corresponde à credencial")
        if identity.actor_id != x_actor_id:
            raise ValueError("X-Actor-Id não corresponde à credencial")
        if not identity.active:
            raise ValueError("Credencial revogada")

        correlation_id = x_correlation_id or str(uuid.uuid4())
        credential_ref = hashlib.sha256(credential.encode()).hexdigest()[:16]

        return ActorContext(
            tenant_id=identity.tenant_id,
            actor_id=identity.actor_id,
            correlation_id=correlation_id,
            credential_ref=credential_ref,
            profile=identity.profile,
        )

    def _build_context_from_static(
        self,
        credential: str,
        x_tenant_id: str,
        x_actor_id: str,
        x_correlation_id: str | None,
    ) -> ActorContext:
        if credential not in self._static:
            raise ValueError("Credencial inválida ou não autorizada")

        reg_tenant, reg_actor, profile = self._static[credential]

        if reg_tenant != x_tenant_id:
            raise ValueError("X-Tenant-Id não corresponde à credencial")
        if reg_actor != x_actor_id:
            raise ValueError("X-Actor-Id não corresponde à credencial")

        correlation_id = x_correlation_id or str(uuid.uuid4())
        credential_ref = hashlib.sha256(credential.encode()).hexdigest()[:16]

        return ActorContext(
            tenant_id=reg_tenant,
            actor_id=reg_actor,
            correlation_id=correlation_id,
            credential_ref=credential_ref,
            profile=profile,
        )
