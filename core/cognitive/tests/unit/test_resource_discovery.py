"""
test_resource_discovery.py — GET /v1/resources (Sprint 0.6 FASE 3).

Contrato de descoberta autorizada de resources por capability:

  GET /v1/resources?capability=infra.inspect
  → {resources: [{resource_key, resource_type}]}

Segurança coberta:
  - sem grant da capability para o profile → lista vazia (fail-closed, sem
    exposição de catálogo);
  - resource sem host (não utilizável) → filtrado;
  - capability desconhecida → 404;
  - cross-tenant: tenant A nunca vê resources de tenant B (list scoped);
  - autenticação: headers que não batem com a credential → 401.
"""

from __future__ import annotations

import os

os.environ["COGNITIVE_MODE"] = "in_memory"
os.environ["COGNITIVE_DEV_TENANT_ID"] = "dev-tenant"
os.environ["COGNITIVE_GATEWAY_CREDENTIAL"] = "dev-secret"
os.environ["COGNITIVE_DEV_ACTOR_ID"] = "dev-actor"
os.environ.pop("COGNITIVE_DB_URL", None)
os.environ.pop("COGNITIVE_DB_ADMIN_URL", None)
os.environ.pop("COGNITIVE_DB_WORKER_URL", None)

import httpx  # noqa: E402
import pytest  # noqa: E402

from cognitive.gateway.app import create_app  # noqa: E402
from cognitive.contracts.tenancy import CapabilityGrant  # noqa: E402

APP = create_app()
_next_tenant = 0


def _fresh_tenant() -> str:
    global _next_tenant
    _next_tenant += 1
    return f"tenant-{_next_tenant}"


@pytest.fixture
async def client():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=APP),
        base_url="http://testserver",
    ) as c:
        yield c


def _auth_headers(credential: str, tenant: str, actor: str) -> dict:
    return {
        "Authorization": f"Bearer {credential}",
        "X-Tenant-Id": tenant,
        "X-Actor-Id": actor,
        "X-Correlation-Id": "test-correlation",
    }


async def _get_resources(client, headers, capability="infra.inspect"):
    return await client.get("/v1/resources", params={"capability": capability}, headers=headers)


def _register_identity(credential, tenant, actor, profile="owner-core"):
    APP.state.identity_resolver.register_static(credential, tenant, actor, profile)


def _register_resource(tenant, key, host=None, rtype="vps"):
    params = {"type": rtype}
    if host:
        params["host"] = host
    APP.state.resource_resolver.register(tenant, key, params)


def _register_grant(tenant, profile, capability):
    APP.state.registry.register_grant(CapabilityGrant(
        tenant_id=tenant, profile=profile, capability_id=capability,
    ))


# ─── Autorização / elegibilidade ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_resources_authorized_returns_only_logical_ids(client):
    """Identidade com grant para infra.inspect vê os resources utilizáveis do
    SEU tenant — apenas {resource_key, resource_type}, nunca host/params."""
    tenant = _fresh_tenant()
    _register_identity(f"cred-{tenant}", tenant, "actor-a")
    _register_resource(tenant, "vps-a", host="host-a.invalid", rtype="vps")
    _register_resource(tenant, "vps-b", host="host-b.invalid", rtype="vps")
    _register_grant(tenant, "owner-core", "infra.inspect")

    resp = await _get_resources(client, _auth_headers(f"cred-{tenant}", tenant, "actor-a"))
    assert resp.status_code == 200
    body = resp.json()
    keys = [r["resource_key"] for r in body["resources"]]
    assert keys == ["vps-a", "vps-b"]  # determinístico (ordenado)
    for r in body["resources"]:
        assert set(r.keys()) == {"resource_key", "resource_type"}
        assert "host" not in r
        assert "resolved_params" not in r


@pytest.mark.asyncio
async def test_list_resources_no_grant_returns_empty(client):
    """Sem grant da capability → lista VAZIA (fail-closed; não expõe catálogo
    nem resources que receberiam DENY)."""
    tenant = _fresh_tenant()
    _register_identity(f"cred-{tenant}", tenant, "actor-a")
    _register_resource(tenant, "vps-a", host="host-a.invalid")

    resp = await _get_resources(client, _auth_headers(f"cred-{tenant}", tenant, "actor-a"))
    assert resp.status_code == 200
    assert resp.json() == {"resources": []}


@pytest.mark.asyncio
async def test_list_resources_unknown_capability_404(client):
    tenant = _fresh_tenant()
    _register_identity(f"cred-{tenant}", tenant, "actor-a")
    _register_grant(tenant, "owner-core", "infra.inspect")
    resp = await _get_resources(
        client, _auth_headers(f"cred-{tenant}", tenant, "actor-a"),
        capability="nope.doesnotexist",
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_resources_filters_unusable_without_host(client):
    """Resource sem host (não utilizável por infra.inspect) é filtrado."""
    tenant = _fresh_tenant()
    _register_identity(f"cred-{tenant}", tenant, "actor-a")
    _register_resource(tenant, "vps-a", host="host-a.invalid")
    _register_resource(tenant, "vps-broken", host=None)
    _register_grant(tenant, "owner-core", "infra.inspect")

    resp = await _get_resources(client, _auth_headers(f"cred-{tenant}", tenant, "actor-a"))
    keys = [r["resource_key"] for r in resp.json()["resources"]]
    assert keys == ["vps-a"]


@pytest.mark.asyncio
async def test_list_resources_cross_tenant_blocked(client):
    """Cross-tenant: tenant B tem resources+grant, tenant A não os vê."""
    tenant_a = _fresh_tenant()
    tenant_b = _fresh_tenant()
    _register_identity(f"cred-{tenant_a}", tenant_a, "actor-a")
    _register_resource(tenant_a, "vps-a", host="host-a.invalid")
    _register_grant(tenant_a, "owner-core", "infra.inspect")

    _register_identity(f"cred-{tenant_b}", tenant_b, "actor-b")
    _register_resource(tenant_b, "vps-secreto-b", host="host-b.invalid")
    _register_grant(tenant_b, "owner-core", "infra.inspect")

    resp = await _get_resources(client, _auth_headers(f"cred-{tenant_a}", tenant_a, "actor-a"))
    keys = [r["resource_key"] for r in resp.json()["resources"]]
    assert "vps-secreto-b" not in keys
    assert keys == ["vps-a"]


@pytest.mark.asyncio
async def test_list_resources_auth_headers_mismatch_401(client):
    """Headers que não batem com a credential → 401."""
    tenant = _fresh_tenant()
    _register_identity(f"cred-{tenant}", tenant, "actor-a")
    resp = await _get_resources(client, _auth_headers(f"cred-{tenant}", "outro-tenant", "actor-a"))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_resources_unauthenticated_401(client):
    resp = await client.get("/v1/resources", params={"capability": "infra.inspect"})
    assert resp.status_code == 401


# ─── In-memory resolver: list_active scoping ────────────────────────────────


@pytest.mark.asyncio
async def test_in_memory_list_active_scoped_by_tenant():
    from cognitive.execution.resource_resolver import InMemoryResourceResolver

    resolver = InMemoryResourceResolver()
    resolver.register("tenant-x", "vps-a", {"host": "h", "type": "vps"})
    resolver.register("tenant-y", "vps-b", {"host": "h", "type": "vps"})
    assert [r["resource_key"] for r in await resolver.list_active("tenant-x")] == ["vps-a"]
    assert [r["resource_key"] for r in await resolver.list_active("tenant-y")] == ["vps-b"]