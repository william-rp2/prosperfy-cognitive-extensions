"""
test_sprint_05_e2e_local.py — DEV E2E do vertical slice do Sprint 0.5.

Prova o caminho completo de Hermes → Cognitive API → resultado consolidado
sem rede externa: o Cognitive Gateway roda em modo in_memory (MockSkillsAdapter)
dentro do processo, e o CognitiveApiAdapter do Hermes fala com ele via
httpx.ASGITransport.

Cadeia coberta (Hermes → Cognitive):
  status → authorize → catalog → execute infra.inspect
  → Identity/Tenant/Actor → Registry → Grant → Policy → Resource Resolver
  → Adapter mock → audit → resposta → build_server_status_view (summary)

Também cobre o caminho negativo: tenant sem grant recebe DENY e o client
falha fechado (RuntimeError), sem chamada ao adapter.

IMPORTANTE: as env vars COGNITIVE_* precisam estar definidas ANTES do import
de cognitive.gateway.app (create_app() roda no import do módulo).
"""

from __future__ import annotations

import os

# Config do gateway in-memory de teste — obrigatório antes do import.
os.environ["COGNITIVE_MODE"] = "in_memory"
os.environ["COGNITIVE_DEV_TENANT_ID"] = "sprint05-tenant"
os.environ["COGNITIVE_GATEWAY_CREDENTIAL"] = "sprint05-secret"
os.environ["COGNITIVE_DEV_ACTOR_ID"] = "sprint05-actor"
os.environ.pop("COGNITIVE_DB_URL", None)
os.environ.pop("COGNITIVE_DB_ADMIN_URL", None)
os.environ.pop("COGNITIVE_DB_WORKER_URL", None)

import httpx  # noqa: E402
import pytest  # noqa: E402

from cognitive.contracts.audit import AuditOutcome  # noqa: E402
from cognitive.gateway.app import create_app  # noqa: E402

from capability_intelligence.models import (  # noqa: E402
    AuthorizationRequest,
    ExecutionRequest,
    IntentQuery,
)
from capability_intelligence.server_views import build_server_status_view  # noqa: E402
from capability_intelligence.transport.cognitive_api_adapter import CognitiveApiAdapter  # noqa: E402

APP = create_app()

# Credencial extra: tenant válido mas SEM grant → DENY esperado. O recurso
# precisa estar registrado para o tenant negado para o request chegar à
# Policy (Resource Resolver roda ANTES da Policy — ADR-V2-004); sem o
# recurso, a falha seria de resolução, não de grant.
APP.state.identity_resolver.register_static(
    "sprint05-denied-secret", "sprint05-denied-tenant", "sprint05-denied-actor", "owner-core",
)
APP.state.resource_resolver.register(
    "sprint05-denied-tenant", "prosperfy-main",
    {"host": "mock-vps-denied.test", "type": "vps"},
)


def make_transport():
    return httpx.ASGITransport(app=APP)


def make_adapter(credential: str = "sprint05-secret", tenant: str = "sprint05-tenant",
                 actor: str = "sprint05-actor") -> CognitiveApiAdapter:
    return CognitiveApiAdapter(
        base_url="http://testserver",
        credential=credential,
        tenant_id=tenant,
        actor_id=actor,
        transport=make_transport(),
    )


@pytest.mark.asyncio
async def test_full_slice_status_catalog_authorize_execute_view():
    adapter = make_adapter()

    status = await adapter.get_status()
    assert status.healthy is True
    assert status.capabilities_total >= 1

    catalog = await adapter.resolve_catalog(
        IntentQuery(intent="server status", domain="infrastructure")
    )
    assert any(m.capability_id == "infra.inspect" for m in catalog.matches)

    auth = await adapter.authorize(AuthorizationRequest(capability_id="infra.inspect"))
    assert auth.authorized is True

    ref = await adapter.execute(ExecutionRequest(
        capability_id="infra.inspect", params={"resource": "prosperfy-main"},
    ))
    result = await adapter.get_result(ref)
    assert result.success is True
    assert set(result.data) >= {
        "prosperfy_vps_panorama",
        "prosperfy_vps_listar_containers",
        "prosperfy_vps_verificar_portas",
    }

    view = build_server_status_view(result.data)
    norm = view["normalized"]
    assert norm["host"] == "mock-host"
    assert norm["container_count"] == 2
    assert norm["container_running_count"] == 2
    assert norm["ports_open_count"] == 3
    assert norm["degraded"] is False
    assert "2 containers: 2 rodando." in view["summary"]


@pytest.mark.asyncio
async def test_audit_trail_written_from_hermes_client():
    adapter = make_adapter()
    ref = await adapter.execute(ExecutionRequest(
        capability_id="infra.inspect", params={"resource": "prosperfy-main"},
    ))
    result = await adapter.get_result(ref)
    assert result.success is True

    events = APP.state.audit_writer.get_all_for_tenant("sprint05-tenant")
    # Suíte compartilha o mesmo APP — execuções de outros testes também
    # gravam no mesmo audit_writer; o que importa é que exista pelo menos um
    # evento COMPLETED de infra.inspect para o tenant.
    assert any(
        e.outcome == AuditOutcome.COMPLETED and e.capability_id == "infra.inspect"
        for e in events
    )


@pytest.mark.asyncio
async def test_deny_fails_closed_without_adapter_call():
    adapter = make_adapter(
        credential="sprint05-denied-secret",
        tenant="sprint05-denied-tenant",
        actor="sprint05-denied-actor",
    )
    with pytest.raises(RuntimeError) as exc_info:
        await adapter.execute(ExecutionRequest(
            capability_id="infra.inspect", params={"resource": "prosperfy-main"},
        ))
    assert "não possui grant" in str(exc_info.value)

    events = APP.state.audit_writer.get_all_for_tenant("sprint05-denied-tenant")
    assert any(e.outcome == AuditOutcome.DENIED for e in events)


@pytest.mark.asyncio
async def test_unknown_credential_401_fails_closed():
    adapter = make_adapter(
        credential="not-a-valid-credential",
        tenant="sprint05-tenant",
        actor="sprint05-actor",
    )
    with pytest.raises(RuntimeError) as exc_info:
        await adapter.execute(ExecutionRequest(
            capability_id="infra.inspect", params={"resource": "prosperfy-main"},
        ))
    assert "401" in str(exc_info.value)