"""
gateway/deps.py — Dependency injection do Gateway FastAPI.

Resolve ActorContext a partir de headers HTTP e injeta serviços.
ADR-V2-002: identidade vem exclusivamente de headers, nunca do body.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from ..contracts.tenancy import ActorContext
from ..tenancy.context import build_actor_context


def get_actor_context(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-Id")] = None,
    x_correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
) -> ActorContext:
    """
    Constrói ActorContext a partir dos headers.

    Levanta HTTP 401 se qualquer header obrigatório estiver ausente ou credencial inválida.
    """
    try:
        return build_actor_context(
            authorization=authorization,
            x_tenant_id=x_tenant_id,
            x_actor_id=x_actor_id,
            x_correlation_id=x_correlation_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


ActorContextDep = Annotated[ActorContext, Depends(get_actor_context)]
