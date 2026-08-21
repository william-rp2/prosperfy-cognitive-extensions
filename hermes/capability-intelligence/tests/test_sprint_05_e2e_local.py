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
from cognitive.contracts.tenancy import CapabilityGrant  # noqa: E402
from cognitive.gateway.app import create_app  # noqa: E402

from capability_intelligence.models import (  # noqa: E402
    AuthorizationRequest,
    ExecutionRequest,
    IntentQuery,
)
from capability_intelligence.infra_service import InfraService  # noqa: E402
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


@pytest.mark.asyncio
async def test_infra_service_uses_cognitive_path():
    """O caminho REAL do Hermes ('Como estão meus servidores?') passa pelo
    Cognitive: InfraService → CognitiveApiAdapter → Cognitive API (gateway
    in-memory aqui, mock da ProsperfySkill). Nenhum MCPAdapter legado é usado
    — LEGACY_INFRA_PATH_USED=NO."""
    service = InfraService(make_adapter())
    view = await service.servers_status()

    assert view["capability_id"] == "infra.inspect"
    norm = view["normalized"]
    assert norm["host"] == "mock-host"
    assert norm["container_count"] == 2
    assert norm["ports_open_count"] == 3
    assert "2 containers: 2 rodando." in view["summary"]


@pytest.mark.asyncio
async def test_infra_service_deny_fails_closed_no_legacy_fallback():
    """Tenant sem grant → Cognitive responde DENY → InfraService levanta
    RuntimeError. NUNCA cai no caminho legado MCP direto (fail closed)."""
    service = InfraService(make_adapter(
        credential="sprint05-denied-secret",
        tenant="sprint05-denied-tenant",
        actor="sprint05-denied-actor",
    ))
    with pytest.raises(RuntimeError) as exc_info:
        await service.servers_status()
    assert "não possui grant" in str(exc_info.value)


def test_plugin_servidores_command_via_cognitive():
    """Prova o comando /servidores do plugin (superfície do Hermes real)
    atravessando o Cognitive e devolvendo o resumo PT-BR.

    Handler do plugin é síncrono (chama asyncio.run internamente), então o
    teste roda fora de event loop.
    """
    import importlib.util
    from pathlib import Path

    from capability_intelligence import infra_service

    plugin_path = Path(__file__).resolve().parents[1] / "plugin" / "__init__.py"
    spec = importlib.util.spec_from_file_location("hermes_plugin", plugin_path)
    plugin_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plugin_mod)

    real_from_env = infra_service.InfraService.from_env
    infra_service.InfraService.from_env = lambda: InfraService(make_adapter())
    try:
        out = plugin_mod._handle_servidores("prosperfy-main")
    finally:
        infra_service.InfraService.from_env = real_from_env

    assert "mock-host" in out
    assert "2 containers: 2 rodando." in out
    assert "OK" in out


# ─── Reprodução da falha funcional do Homolog (Sprint 0.5 RETURN_TO_DEV) ──
#
# No Homolog (database mode) o tenant_resource provisionado pelo bootstrap 0.3
# tem resource_key "homolog-synthetic-vps" — NÃO "prosperfy-main". O
# InfraService (pré-fix) hardcodava "prosperfy-main" como selector → Resource
# Resolver não encontrava → status=failed → REAL_VPS_DATA=NO.
#
# O app "homolog-like" abaixo simula esse estado: só o resource
# "homolog-synthetic-vps" existe para o tenant (nada de "prosperfy-main").

HOMOLOG_APP = create_app()

HOMOLOG_APP.state.identity_resolver.register_static(
    "sprint05-homolog-secret", "sprint05-homolog-tenant", "sprint05-homolog-actor", "owner-core",
)
HOMOLOG_APP.state.registry.register_grant(CapabilityGrant(
    tenant_id="sprint05-homolog-tenant",
    profile="owner-core",
    capability_id="infra.inspect",
))
# Só o resource do bootstrap 0.3 existe — sem "prosperfy-main".
HOMOLOG_APP.state.resource_resolver.register(
    "sprint05-homolog-tenant", "homolog-synthetic-vps",
    {"host": "mock-vps-homolog.test", "type": "vps"},
)


def make_homolog_adapter() -> CognitiveApiAdapter:
    return CognitiveApiAdapter(
        base_url="http://testserver",
        credential="sprint05-homolog-secret",
        tenant_id="sprint05-homolog-tenant",
        actor_id="sprint05-homolog-actor",
        transport=httpx.ASGITransport(app=HOMOLOG_APP),
    )


def test_homolog_failure_reproduced_with_wrong_selector():
    """REPRODUÇÃO: InfraService com resource selector que NÃO existe no
    tenant (equivalente ao pré-fix "prosperfy-main" no Homolog) falha fechado
    com erro de resource — MCP nunca é chamado, sem dados reais."""
    from capability_intelligence import infra_service

    real_env = os.environ.get("COGNITIVE_RESOURCE_KEY")
    os.environ.pop("COGNITIVE_RESOURCE_KEY", None)  # default = prosperfy-main
    service = InfraService(make_homolog_adapter())
    try:
        with pytest.raises(RuntimeError) as exc_info:
            import asyncio
            asyncio.run(service.servers_status())  # sem selector → default DEV
    finally:
        if real_env is not None:
            os.environ["COGNITIVE_RESOURCE_KEY"] = real_env
    assert "não encontrado" in str(exc_info.value).lower() or "resource" in str(exc_info.value).lower()


def test_homolog_passes_with_correct_selector():
    """FIX: InfraService com o selector correto ("homolog-synthetic-vps",
    provisionado no Homolog) atravessa o Cognitive e produz dados reais
    (mock) — PANORAMA/CONTAINERS/PORTS/NORMALIZED/SUMMARY."""
    service = InfraService(make_homolog_adapter())
    import asyncio

    view = asyncio.run(service.servers_status(resource="homolog-synthetic-vps"))

    norm = view["normalized"]
    # MockSkillsAdapter retorna o panorama com host "mock-host"; os três
    # contratos das tools são preenchidos.
    assert "prosperfy_vps_panorama" in view["raw"]
    assert "prosperfy_vps_listar_containers" in view["raw"]
    assert "prosperfy_vps_verificar_portas" in view["raw"]
    assert norm["container_count"] == 2
    assert norm["ports_open_count"] == 3
    assert "2 containers: 2 rodando." in view["summary"]


def test_resource_selector_configurable_via_env():
    """FIX: o selector default é configurável via COGNITIVE_RESOURCE_KEY —
    Homolog aponta o resource provisionado sem mudar código nem hardcodar
    host. Sem a env, o default DEV "prosperfy-main" continua valendo."""
    from capability_intelligence.infra_service import _resolve_default_resource

    old = os.environ.get("COGNITIVE_RESOURCE_KEY")
    os.environ["COGNITIVE_RESOURCE_KEY"] = "homolog-synthetic-vps"
    try:
        assert _resolve_default_resource() == "homolog-synthetic-vps"
    finally:
        if old is None:
            os.environ.pop("COGNITIVE_RESOURCE_KEY", None)
        else:
            os.environ["COGNITIVE_RESOURCE_KEY"] = old

    os.environ.pop("COGNITIVE_RESOURCE_KEY", None)
    assert _resolve_default_resource() == "prosperfy-main"


# ─── Traço do caminho resource → tool selection → adapter (2ª falha) ──────
#
# Prova que, com RESOURCE_FOUND=YES e GRANT_FOUND=YES, o orchestrator chega à
# seleção de tools e invoca o adapter EXATAMENTE 3 vezes (fan-out do contrato
# infra.inspect: panorama + containers + portas — NÃO é um único request).
# Se o Gate reporta MCP não confirmado com resource resolvido, a divergência
# NÃO está neste trecho (código) — está no runtime real (LIVE_MCP/credential/
# host do resource), que este teste isola por exclusão.

class CountingSkillsAdapter:
    """Envolve o MockSkillsAdapter e conta invocações + registra os args
    (host) recebidos — sem tocar em nada do Cognitive."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.calls: list[tuple[str, dict]] = []

    async def invoke_tool(self, tool_name, arguments, tenant_id, correlation_id):
        self.calls.append((tool_name, dict(arguments)))
        return await self._inner.invoke_tool(
            tool_name, arguments, tenant_id, correlation_id,
        )

    async def health(self) -> bool:
        return await self._inner.health()


def test_infra_inspect_fanout_three_tools_reaches_adapter():
    """RESOURCE_FOUND=YES + GRANT_FOUND=YES → orchestrator chega à seleção de
    tools e invoca o adapter 3x (panorama/containers/portas). O host resolvido
    é repassado ao adapter (sanitizado: apenas host, sem tipo/secret)."""
    from cognitive.adapters.prosperfy_skills.mock import MockSkillsAdapter

    counting = CountingSkillsAdapter(MockSkillsAdapter())
    original = APP.state.orchestrator._adapter
    APP.state.orchestrator._adapter = counting
    try:
        adapter = make_adapter()
        ref = __import__("asyncio").run(adapter.execute(ExecutionRequest(
            capability_id="infra.inspect", params={"resource": "prosperfy-main"},
        )))
        result = __import__("asyncio").run(adapter.get_result(ref))
    finally:
        APP.state.orchestrator._adapter = original

    assert result.success is True
    called_tools = [name for name, _ in counting.calls]
    assert called_tools == [
        "prosperfy_vps_panorama",
        "prosperfy_vps_listar_containers",
        "prosperfy_vps_verificar_portas",
    ]
    # O host resolvido do tenant_resources chega ao adapter (sem 'type').
    for _, args in counting.calls:
        assert "host" in args
        assert "type" not in args


# ─── Empty-success: fail-closed (3ª falha: success com payload vazio) ─────
#
# Reproduz o sintoma do Homolog: gateway retorna completed + data={} (ou sem as
# tools obrigatórias) e o Hermes ANTES aceitava como sucesso silencioso (visão
# vazia degraded). Contrato de infra.inspect: panorama + containers são
# obrigatórias. 3 tools esperadas + 0 resultados válidos = FAILED (não success).

class FakeEmptyAdapter:
    """Simula o gateway retornando completed com payload vazio (cenário do
    Homolog que o Gate reportou como SUCCESS COM PAYLOAD VAZIO)."""

    def __init__(self, data: dict | None = None) -> None:
        self._data = {} if data is None else data

    async def execute(self, request):
        from capability_intelligence.models import ExecutionReference
        return ExecutionReference(ref="empty-exec")

    async def get_result(self, ref):
        from capability_intelligence.models import CapabilityResult, ResultMetadata
        return CapabilityResult(
            success=True, data=self._data, metadata=ResultMetadata(),
        )


def test_empty_success_fails_closed():
    """ANTES: success + data={} → visão vazia sem erro (bug).
    DEPOIS: 3 tools esperadas + 0 resultados válidos → RuntimeError (fail-closed)."""
    from capability_intelligence.infra_service import InfraService

    service = InfraService(FakeEmptyAdapter(data={}))
    with pytest.raises(RuntimeError, match="obrigatórias"):
        __import__("asyncio").run(service.servers_status())


def test_partial_results_without_obligatory_tools_fails_closed():
    """Só panorama presente (sem containers obrigatória) → não é success."""
    from capability_intelligence.infra_service import InfraService

    service = InfraService(FakeEmptyAdapter(data={"prosperfy_vps_panorama": {"status": "ok"}}))
    with pytest.raises(RuntimeError, match="obrigatórias"):
        __import__("asyncio").run(service.servers_status())


def test_full_three_tools_still_success():
    """DEPOIS: 3 tools (panorama+containers obrigatórias + portas opcional) →
    success normal, sem regressão no caminho feliz."""
    from capability_intelligence.infra_service import InfraService
    from capability_intelligence.server_views import PANORAMA, CONTAINERS, PORTS

    data = {
        PANORAMA: {"status": "ok", "host": "srv", "uptime_seconds": 1000},
        CONTAINERS: {"containers": [{"name": "a", "status": "running"}]},
        PORTS: {"ports": {"80": "open"}},
    }
    service = InfraService(FakeEmptyAdapter(data=data))
    view = __import__("asyncio").run(service.servers_status())
    assert view["normalized"]["container_count"] == 1


# ─── Negativos do Gate: COGNITIVE_UNAVAILABLE + MCP_ERROR (fail-closed) ────
#
# Boundary real da Sprint 0.5: CognitiveApiAdapter → InfraService, com
# transporte controlado (httpx.MockTransport) — sem rede, sem MCP real, sem
# fallback para MCPAdapter legado.

def _mock_transport(payload=None, raise_error=None):
    def handler(request):
        if raise_error is not None:
            raise raise_error
        return httpx.Response(200, json=payload)
    return httpx.MockTransport(handler)


def test_cognitive_unavailable_fails_closed_no_legacy_fallback():
    """Cognitive indisponível (erro de transporte/5xx) → o adapter levanta
    RuntimeError sanitizado (sem secret/header) e o InfraService propaga;
    NÃO retorna visão; NÃO usa MCPAdapter legado (LEGACY_FALLBACK_USED=NO)."""
    from capability_intelligence.infra_service import InfraService

    adapter = CognitiveApiAdapter(
        base_url="http://cognitive.test",
        credential="unit-secret",
        tenant_id="unit-tenant",
        actor_id="unit-actor",
        transport=_mock_transport(raise_error=httpx.ConnectError("boom")),
    )
    service = InfraService(adapter)
    with pytest.raises(RuntimeError) as exc_info:
        __import__("asyncio").run(service.servers_status())
    assert "ConnectError" in str(exc_info.value) or "inacessível" in str(exc_info.value)
    # sem secret/header cru no erro (sanitização do adapter real)
    assert "unit-secret" not in str(exc_info.value)
    assert "Bearer" not in str(exc_info.value)


def test_mcp_error_fails_closed_no_legacy_fallback():
    """Cognitive retorna status=failed com erro originado no MCP (que ecoa a
    credencial, como um bug servidor) → o adapter real redige o erro e o
    InfraService levanta; NENHUMA summary válida; sem fallback legado; sem
    credencial crua exposta (SECRET_EXPOSED=NO)."""
    from capability_intelligence.infra_service import InfraService

    secret = "unit-super-secret-credential"
    payload = {
        "status": "failed",
        "execution_id": "mcp-exec",
        "error": f"ProsperfySkill tool 'x' falhou (erro de protocolo MCP) — {secret}",
    }
    adapter = CognitiveApiAdapter(
        base_url="http://cognitive.test",
        credential=secret,
        tenant_id="unit-tenant",
        actor_id="unit-actor",
        transport=_mock_transport(payload=payload),
    )
    service = InfraService(adapter)
    with pytest.raises(RuntimeError) as exc_info:
        __import__("asyncio").run(service.servers_status())
    # erro propagado de forma sanitizada (sem a credencial crua)
    assert secret not in str(exc_info.value)
    assert "MCP" in str(exc_info.value) or "falhou" in str(exc_info.value)