"""
test_cognitive_api_adapter.py — Unit tests do CognitiveApiAdapter (httpx.MockTransport).

Sem rede: o transporte HTTP é mockado deterministicamente. Cobrem o contrato
ProtocolAdapter falando com o Cognitive Gateway V2:
  resolve_catalog / authorize / execute / get_result / get_status
e os comportamentos fail-closed (http 4xx/5xx, erro de transporte, status
failed da aplicação, credencial nunca vazada).
"""

from __future__ import annotations

import logging

import httpx
import pytest

from capability_intelligence.models import (
    AuthorizationRequest,
    CapabilityResult,
    ExecutionReference,
    ExecutionRequest,
    IntentQuery,
)
from capability_intelligence.transport.cognitive_api_adapter import CognitiveApiAdapter

CREDENTIAL = "unit-secret-credential"
TENANT = "unit-tenant"
ACTOR = "unit-actor"
BASE = "http://cognitive.test"


def make_adapter(handler) -> CognitiveApiAdapter:
    transport = httpx.MockTransport(handler)
    return CognitiveApiAdapter(
        base_url=BASE,
        credential=CREDENTIAL,
        tenant_id=TENANT,
        actor_id=ACTOR,
        transport=transport,
    )


def json_response(status_code: int, payload: dict) -> httpx.Response:
    return httpx.Response(status_code=status_code, json=payload)


def _completed_execute_payload() -> dict:
    return {
        "execution_id": "exec-unit-1",
        "correlation_id": "corr-unit-1",
        "status": "completed",
        "data": {
            "prosperfy_vps_panorama": {"status": "ok", "host": "srv"},
            "prosperfy_vps_listar_containers": {"containers": []},
        },
        "audit_id": "audit-unit-1",
        "error": None,
    }


class TestConstruction:
    def test_missing_config_raises(self):
        import os

        for key in ("COGNITIVE_GATEWAY_URL", "COGNITIVE_GATEWAY_CREDENTIAL",
                    "COGNITIVE_TENANT_ID", "COGNITIVE_ACTOR_ID"):
            os.environ.pop(key, None)
        with pytest.raises(ValueError):
            CognitiveApiAdapter()

    def test_credential_with_crlf_rejected(self):
        with pytest.raises(ValueError, match="controle"):
            CognitiveApiAdapter(
                base_url=BASE, credential="bad\rsecret", tenant_id=TENANT, actor_id=ACTOR,
            )

    @pytest.mark.asyncio
    async def test_headers_carry_tenant_and_actor(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["authorization"] = request.headers.get("Authorization")
            seen["tenant"] = request.headers.get("X-Tenant-Id")
            seen["actor"] = request.headers.get("X-Actor-Id")
            seen["correlation"] = request.headers.get("X-Correlation-Id")
            return json_response(200, {"healthy": True, "capabilities_count": 1, "version": "0.2.0",
                                       "environment": "test", "runtime_mode": "in_memory",
                                       "db_configured": False, "registry_loaded": True,
                                       "tenant_id": TENANT, "actor_id": ACTOR, "correlation_id": "x"})

        await make_adapter(handler).get_status()
        assert seen["authorization"] == f"Bearer {CREDENTIAL}"
        assert seen["tenant"] == TENANT
        assert seen["actor"] == ACTOR
        assert seen["correlation"]


class TestStatusAndCatalog:
    @pytest.mark.asyncio
    async def test_get_status_maps(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/status"
            return json_response(200, {"healthy": True, "capabilities_count": 3, "version": "0.2.0",
                                       "environment": "test", "runtime_mode": "in_memory",
                                       "db_configured": False, "registry_loaded": True,
                                       "tenant_id": TENANT, "actor_id": ACTOR, "correlation_id": "x"})

        status = await make_adapter(handler).get_status()
        assert status.healthy is True
        assert status.capabilities_total == 3
        assert status.capabilities_available == 3

    @pytest.mark.asyncio
    async def test_resolve_catalog_maps_describe_payload(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/capabilities"
            return json_response(200, [
                {"id": "infra.inspect", "version": "1.0.0", "domain": "infrastructure",
                 "description": "Inspeciona infra", "default_policy": "allow",
                 "required_scopes": ["infra:read"], "input_schema": {"type": "object"}},
            ])

        catalog = await make_adapter(handler).resolve_catalog(
            IntentQuery(intent="server status", domain="infrastructure")
        )
        assert len(catalog.matches) == 1
        match = catalog.matches[0]
        assert match.capability_id == "infra.inspect"
        assert match.metadata.domain == "infrastructure"
        assert match.metadata.required_role == "allow"


class TestAuthorize:
    @pytest.mark.asyncio
    async def test_authorize_200_ok(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/capabilities/infra.inspect"
            return json_response(200, {"id": "infra.inspect", "version": "1.0.0", "domain": "infrastructure",
                                       "description": "d", "default_policy": "allow"})

        result = await make_adapter(handler).authorize(
            AuthorizationRequest(capability_id="infra.inspect")
        )
        assert result.authorized is True

    @pytest.mark.asyncio
    async def test_authorize_404_not_authorized(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return json_response(404, {"detail": "Capability 'nope' não encontrada"})

        result = await make_adapter(handler).authorize(
            AuthorizationRequest(capability_id="nope")
        )
        assert result.authorized is False
        assert "404" in result.reason


class TestExecute:
    @pytest.mark.asyncio
    async def test_execute_completed_returns_ref_and_result(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/capabilities/infra.inspect/execute"
            body = request.read().decode()
            assert '"resource"' in body
            return json_response(200, _completed_execute_payload())

        adapter = make_adapter(handler)
        ref = await adapter.execute(ExecutionRequest(
            capability_id="infra.inspect", params={"resource": "prosperfy-main"},
        ))
        assert isinstance(ref, ExecutionReference)
        result = await adapter.get_result(ref)
        assert isinstance(result, CapabilityResult)
        assert result.success is True
        assert "prosperfy_vps_panorama" in result.data

    @pytest.mark.asyncio
    async def test_execute_moves_idempotency_key_out_of_params(self):
        import json

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.read().decode())
            # idempotency_key é metadado do contrato HTTP — deve estar no
            # top-level do body, nunca DENTRO de params.
            assert body["idempotency_key"] == "k-1"
            assert "idempotency_key" not in body["params"]
            return json_response(200, _completed_execute_payload())

        adapter = make_adapter(handler)
        await adapter.execute(ExecutionRequest(
            capability_id="infra.inspect",
            params={"resource": "prosperfy-main", "idempotency_key": "k-1"},
        ))

    @pytest.mark.asyncio
    async def test_execute_failed_raises_and_redacts_credential(self):
        def handler(request: httpx.Request) -> httpx.Response:
            payload = _completed_execute_payload()
            payload["status"] = "failed"
            payload["error"] = f"boom containing {CREDENTIAL}"
            return json_response(200, payload)

        adapter = make_adapter(handler)
        with pytest.raises(RuntimeError) as exc_info:
            await adapter.execute(ExecutionRequest(
                capability_id="infra.inspect", params={"resource": "prosperfy-main"},
            ))
        assert CREDENTIAL not in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_execute_http_500_raises_and_redacts(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return json_response(500, {"detail": f"internal {CREDENTIAL}"})

        adapter = make_adapter(handler)
        with pytest.raises(RuntimeError):
            await adapter.execute(ExecutionRequest(
                capability_id="infra.inspect", params={},
            ))

    @pytest.mark.asyncio
    async def test_transport_error_fail_closed(self, caplog):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        adapter = make_adapter(handler)
        with caplog.at_level(logging.ERROR, logger="capability_intelligence"):
            with pytest.raises(RuntimeError) as exc_info:
                await adapter.get_status()
        assert CREDENTIAL not in str(exc_info.value)
        assert CREDENTIAL not in caplog.text

    @pytest.mark.asyncio
    async def test_pending_confirmation_result(self):
        def handler(request: httpx.Request) -> httpx.Response:
            payload = _completed_execute_payload()
            payload["status"] = "pending_confirmation"
            payload["data"] = {}
            return json_response(200, payload)

        adapter = make_adapter(handler)
        ref = await adapter.execute(ExecutionRequest(
            capability_id="infra.inspect", params={},
        ))
        result = await adapter.get_result(ref)
        assert result.success is False
        assert "confirmação" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_get_result_unknown_ref(self):
        adapter = make_adapter(lambda req: json_response(200, {"healthy": True}))
        result = await adapter.get_result(ExecutionReference(ref="never-executed"))
        assert result.success is False