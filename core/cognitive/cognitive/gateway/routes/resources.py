"""
gateway/routes/resources.py — Descoberta de resources elegíveis (Sprint 0.6).

GET /v1/resources?capability=infra.inspect

Contrato mínimo aprovado (Sprint 0.6 FASE 3):

  {
    "resources": [
      {"resource_key": "prosperfy-vps-homolog", "resource_type": "vps"}
    ]
  }

Segurança (defense-in-depth):
  - Autenticação via ActorContextDep (service identity → tenant/actor/profile
    derivados da CREDENCIAL — headers não conferidos com a identidade → 401).
  - Elegibilidade por capability: o PROFILE da identidade precisa ter GRANT
    para a capability (GrantResolverPort.resolve_grant). Sem grant → lista
    vazia (fail-closed) — nunca expõe catálogo de resources que receberiam
    DENY.
  - Lista resources ATIVOS do tenant com RLS (tenant_transaction) + filtro
    de usabilidade (resolved_params com 'host') — nada que falharia de
    imediato na execução.
  - Nunca expõe: resolved_params (host/portas), secrets, credentials, grants
    internos, metadata operacional. Apenas {resource_key, resource_type}.

A execução em si continua passando pela autorização normal por resource
(infra.inspect): LIST/DISCOVERY autorizado + EXECUTION authorization por
resource.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from ..deps import AUTH_HEADER_DOCS, ActorContextDep

router = APIRouter()


def _usable_for_infra(params: Any) -> bool:
    """Resource elegível para infra.inspect: ativo (garantido pelo repo) e
    com host concreto resolvido — sem host a execução falharia de imediato."""
    if not isinstance(params, dict):
        return False
    return bool(str(params.get("host") or "").strip())


def _normalize(row: Any) -> tuple[str, str, Any]:
    """Normaliza o shape do resource (dataclass do repo DB ou dict do
    InMemoryResourceResolver) para (resource_key, resource_type, params)."""
    if isinstance(row, dict):
        return (str(row.get("resource_key") or ""),
                str(row.get("resource_type") or "unknown"),
                row.get("resolved_params"))
    return (str(getattr(row, "resource_key", "") or ""),
            str(getattr(row, "resource_type", "") or "unknown"),
            getattr(row, "resolved_params", None))


@router.get(
    "/v1/resources",
    response_model=dict[str, Any],
    tags=["resources"],
    summary="List resources elegíveis para uma capability (Sprint 0.6)",
    openapi_extra={"parameters": AUTH_HEADER_DOCS},
)
async def list_resources(
    capability: str,
    ctx: ActorContextDep,
    request: Request,
) -> dict[str, Any]:
    """Descoberta de resources que a identidade autenticada pode UTILIZAR
    para a capability informada (não um SELECT cru de tenant_resources)."""
    registry = request.app.state.registry
    if registry.get(capability) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Capability '{capability}' não encontrada",
        )

    grant_resolver = request.app.state.grant_resolver
    # Elegibilidade: o profile da identidade tem grant para a capability?
    # Sem grant → lista vazia (fail-closed; sem exposição de catálogo).
    if grant_resolver is not None:
        grant = await grant_resolver.resolve_grant(
            tenant_id=ctx.tenant_id,
            profile=ctx.profile,
            capability_id=capability,
        )
        if grant is None:
            return {"resources": []}

    if request.app.state.use_db:
        repo = request.app.state.resource_repo
        rows = await repo.list_active(ctx.tenant_id) if repo is not None else []
    else:
        resolver = request.app.state.resource_resolver
        rows = await resolver.list_active(ctx.tenant_id) if hasattr(resolver, "list_active") else []

    usable = [r for r in rows if _usable_for_infra(_normalize(r)[2])]
    return {
        "resources": [
            {"resource_key": rk, "resource_type": rt}
            for rk, rt, _params in (_normalize(r) for r in usable)
        ],
    }