"""
test_sprint_06_multi_resource.py — Sprint 0.6 FASE 4: /servidores multi-resource.

Prova o contrato do lado Hermes, determinístico e SEM LLM:

  servidores_status()
    → list_resources (Cognitive descobre resources autorizados)
    → infra.inspect POR resource (cada um passa pela autorização normal)
    → build_servidores_view (consolidação determinística)

Cobertura:
  - descoberta → execução de N resources;
  - partial failure: erro de um resource não vira falso OK e não impede os
    demais resultados válidos;
  - descoberta vazia → visão vazia (não erro);
  - build_servidores_view: OK/DEGRADED/ERRO corretos;
  - adapter.list_resources: parsing da resposta;
  - determinismo (sem LLM): mesma entrada → mesma saída.
"""

from __future__ import annotations

import os

import httpx  # noqa: E402
import pytest  # noqa: E402

from capability_intelligence.infra_service import InfraService  # noqa: E402
from capability_intelligence.server_views import build_servidores_view  # noqa: E402
from capability_intelligence.transport.cognitive_api_adapter import (  # noqa: E402
    CognitiveApiAdapter,
)


# ─── Fake do Cognitive com descoberta multi-resource ────────────────────────


class FakeMultiAdapter:
    """Simula o Cognitive: list_resources + execute/get_result por resource."""

    def __init__(self, resources: list[str] | None = None, fail_on: set[str] | None = None,
                 data_factory=None) -> None:
        self._resources = resources or []
        self._fail_on = fail_on or set()
        self._data_factory = data_factory or (lambda rk: {
            "prosperfy_vps_panorama": {"status": "ok", "host": f"host-{rk}", "uptime_seconds": 1000},
            "prosperfy_vps_listar_containers": {"containers": [{"name": "a", "status": "running"}]},
            "prosperfy_vps_verificar_portas": {"ports": {"80": "open"}},
        })

    async def list_resources(self, capability: str = "infra.inspect") -> list[str]:
        return list(self._resources)

    async def execute(self, request):
        from capability_intelligence.models import ExecutionReference
        return ExecutionReference(ref=f"exec-{request.params.get('resource')}")

    async def get_result(self, ref):
        from capability_intelligence.models import CapabilityResult, ResultMetadata
        rk = ref.ref.split("exec-")[1]
        if rk in self._fail_on:
            raise RuntimeError(f"resource '{rk}' falhou (não autorizado/erro)")
        return CapabilityResult(
            success=True, data=self._data_factory(rk), metadata=ResultMetadata(),
        )


# ─── build_servidores_view ──────────────────────────────────────────────────


def _single_view(resource_key, host, degraded=False):
    raw = {
        "prosperfy_vps_panorama": {"status": "ok", "host": host, "uptime_seconds": 1000},
        "prosperfy_vps_listar_containers": {"containers": [
            {"name": "a", "status": "running" if not degraded else "stopped"}]},
        "prosperfy_vps_verificar_portas": {"ports": {"80": "open"}},
    }
    from capability_intelligence.server_views import build_server_status_view
    view = build_server_status_view(raw)
    view["resource_key"] = resource_key
    return view


def test_build_servidores_view_consolidates_counts():
    v1 = _single_view("vps-a", "host-a")                       # OK
    v2 = _single_view("vps-b", "host-b", degraded=True)        # DEGRADED
    failures = [{"resource_key": "vps-c", "error": "denied"}]
    view = build_servidores_view([v1, v2], failures)

    norm = view["normalized"]
    assert norm["ok_count"] == 1
    assert norm["degraded_count"] == 1
    assert norm["failure_count"] == 1
    assert len(norm["resources"]) == 2
    assert view["summary"].startswith("Servidores — 3")
    assert "host-a — OK" in view["summary"]
    assert "host-b — DEGRADED" in view["summary"]
    assert "vps-c — ERRO" in view["summary"]
    assert view["summary"].endswith("Resumo: 1 OK · 1 DEGRADED · 1 ERRO")


def test_build_servidores_view_partial_failure_no_false_ok():
    """Erro de um resource NÃO vira falso OK e não impede os válidos."""
    ok_view = _single_view("vps-ok", "host-ok")
    failures = [{"resource_key": "vps-bad", "error": "boom"}]
    view = build_servidores_view([ok_view], failures)
    norm = view["normalized"]
    assert norm["ok_count"] == 1  # só o válido — o ERRO NÃO é contado como OK
    assert norm["failure_count"] == 1
    assert "vps-bad — ERRO" in view["summary"]
    assert "host-ok — OK" in view["summary"]
    assert len(norm["resources"]) == 1  # o falho não entra na lista de OK


def test_build_servidores_view_empty():
    view = build_servidores_view([], [])
    assert view["normalized"]["ok_count"] == 0
    assert view["summary"] == "Servidores — 0\nResumo: 0 OK · 0 DEGRADED"


def test_build_servidores_view_deterministic_no_llm():
    a = build_servidores_view([_single_view("x", "h"), _single_view("y", "h2")])
    b = build_servidores_view([_single_view("x", "h"), _single_view("y", "h2")])
    assert a == b


# ─── InfraService.servidores_status ─────────────────────────────────────────


def test_servidores_status_discovers_and_executes_all():
    service = InfraService(FakeMultiAdapter(resources=["vps-a", "vps-b"]))
    view = __import__("asyncio").run(service.servidores_status())
    norm = view["normalized"]
    assert len(norm["resources"]) == 2
    assert norm["ok_count"] == 2
    hosts = {r["host"] for r in norm["resources"]}
    assert hosts == {"host-vps-a", "host-vps-b"}
    assert norm["failure_count"] == 0
    assert "Resumo: 2 OK · 0 DEGRADED" in view["summary"]


def test_servidores_status_partial_failure_keeps_valid_results():
    """Um resource falhando → ERRO na visão; os demais continuam válidos."""
    service = InfraService(FakeMultiAdapter(resources=["vps-ok", "vps-bad"],
                                            fail_on={"vps-bad"}))
    view = __import__("asyncio").run(service.servidores_status())
    norm = view["normalized"]
    assert norm["ok_count"] == 1
    assert norm["failure_count"] == 1
    assert norm["failures"][0]["resource_key"] == "vps-bad"
    assert "vps-bad — ERRO" in view["summary"]
    assert "host-vps-ok — OK" in view["summary"]


def test_servidores_status_empty_discovery_no_error():
    service = InfraService(FakeMultiAdapter(resources=[]))
    view = __import__("asyncio").run(service.servidores_status())
    assert view["normalized"]["ok_count"] == 0
    assert view["normalized"]["failure_count"] == 0
    assert "Servidores — 0" in view["summary"]


# ─── CognitiveApiAdapter.list_resources ─────────────────────────────────────


def _mock_transport(payload):
    def handler(request):
        return httpx.Response(200, json=payload)
    return httpx.MockTransport(handler)


def test_list_resources_parses_logical_keys():
    adapter = CognitiveApiAdapter(
        base_url="http://cognitive.test",
        credential="unit-secret",
        tenant_id="unit-tenant",
        actor_id="unit-actor",
        transport=_mock_transport({"resources": [
            {"resource_key": "vps-a", "resource_type": "vps"},
            {"resource_key": "vps-b", "resource_type": "vps"},
        ]}),
    )
    keys = __import__("asyncio").run(adapter.list_resources("infra.inspect"))
    assert keys == ["vps-a", "vps-b"]


def test_list_resources_empty_and_ignores_extra_fields():
    adapter = CognitiveApiAdapter(
        base_url="http://cognitive.test",
        credential="unit-secret",
        tenant_id="unit-tenant",
        actor_id="unit-actor",
        transport=_mock_transport({"resources": [
            {"resource_key": "vps-a", "resource_type": "vps", "host": "secret-host"},
        ]}),
    )
    keys = __import__("asyncio").run(adapter.list_resources())
    assert keys == ["vps-a"]


def test_list_resources_no_grant_returns_empty():
    adapter = CognitiveApiAdapter(
        base_url="http://cognitive.test",
        credential="unit-secret",
        tenant_id="unit-tenant",
        actor_id="unit-actor",
        transport=_mock_transport({"resources": []}),
    )
    keys = __import__("asyncio").run(adapter.list_resources("infra.inspect"))
    assert keys == []