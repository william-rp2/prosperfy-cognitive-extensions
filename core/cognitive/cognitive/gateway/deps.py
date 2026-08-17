"""
gateway/deps.py — Dependency injection do Gateway FastAPI (Sprint 0.2).

Usa IdentityResolver injetado no app.state (suporta DB e in-memory).
ADR-V2-002: identidade vem exclusivamente de headers, nunca do body.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from ..contracts.tenancy import ActorContext

AUTH_HEADER_DOCS = [
    {
        "name": "Authorization",
        "in": "header",
        "required": True,
        "schema": {"type": "string"},
        "description": "Bearer credential for service identity (never include in body).",
    },
    {
        "name": "X-Tenant-Id",
        "in": "header",
        "required": True,
        "schema": {"type": "string"},
        "description": "Tenant scope for the request (ADR-V2-002).",
    },
    {
        "name": "X-Actor-Id",
        "in": "header",
        "required": True,
        "schema": {"type": "string"},
        "description": "Actor/principal within the tenant (ADR-V2-002).",
    },
    {
        "name": "X-Correlation-Id",
        "in": "header",
        "required": False,
        "schema": {"type": "string"},
        "description": "Optional correlation id for tracing.",
    },
]


async def get_actor_context(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-Id")] = None,
    x_correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
) -> ActorContext:
    """
    Constrói ActorContext a partir dos headers via IdentityResolver do app.state.

    Sprint 0.2: suporta DB (ServiceIdentityRepository) e in-memory com fallback.
    Levanta HTTP 401 se autenticação falhar por qualquer razão.
    """
    identity_resolver = request.app.state.identity_resolver
    try:
        return await identity_resolver.resolve(
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
