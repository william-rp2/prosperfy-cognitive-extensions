"""
tests/unit/test_finance_api_adapter.py — P2 (Financeiro pelo WhatsApp).

FinanceApiAdapter (cognitive/adapters/finance_api/client.py) é o boundary
HTTP entre o Cognitive e apps/financeiro-pessoal-api. Testado com
httpx.MockTransport (sem rede real, sem depender do Node estar rodando) —
exercita headers/query/body reais, não apenas a lógica de decisão.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from cognitive.adapters.finance_api.client import FinanceApiAdapter
from cognitive.adapters.prosperfy_skills.guard import ForbiddenArgumentError

TENANT = "tenant-p2"
CORRELATION = "corr-p2"
TOKEN = "test-finance-token"


def _adapter(handler, token: str | None = TOKEN) -> FinanceApiAdapter:
    transport = httpx.MockTransport(handler)
    return FinanceApiAdapter(base_url="http://finance.local", token=token, transport=transport)


def _json_response(status_code: int, body: dict[str, Any]) -> httpx.Response:
    return httpx.Response(status_code, json=body)


class TestSuccessPaths:
    async def test_get_capability_sends_bearer_auth_and_query_params(self):
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            seen["path"] = request.url.path
            seen["params"] = dict(request.url.params)
            seen["authorization"] = request.headers.get("authorization")
            seen["correlation"] = request.headers.get("x-correlation-id")
            return _json_response(200, {"monthExpense": 42})

        adapter = _adapter(handler)
        result = await adapter.invoke_tool(
            "finance.summary.read", {"month": "2026-08", "category": "Alimentação"}, TENANT, CORRELATION
        )

        assert seen["method"] == "GET"
        assert seen["path"] == "/api/finance/summary"
        assert seen["params"] == {"month": "2026-08", "category": "Alimentação"}
        assert seen["authorization"] == f"Bearer {TOKEN}"
        assert seen["correlation"] == CORRELATION
        assert result == {"success": True, "data": {"monthExpense": 42}}

    async def test_post_capability_sends_json_body(self):
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            seen["path"] = request.url.path
            seen["body"] = json.loads(request.content)
            return _json_response(201, {"transaction": {"id": "tx-1"}, "message": "Registrado."})

        adapter = _adapter(handler)
        payload = {"amount": 89, "direction": "expense", "description": "Combustível"}
        result = await adapter.invoke_tool("finance.manual.create", payload, TENANT, CORRELATION)

        assert seen["method"] == "POST"
        assert seen["path"] == "/api/finance/transactions/manual"
        assert seen["body"] == payload
        assert result["success"] is True
        assert result["data"]["transaction"]["id"] == "tx-1"

    async def test_patch_capability_uses_patch_method(self):
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            return _json_response(200, {"updated": {"id": "tx-1"}})

        adapter = _adapter(handler)
        await adapter.invoke_tool("finance.category.update", {"transactionId": "tx-1", "source": "manual", "category": "Lazer"}, TENANT, CORRELATION)
        assert seen["method"] == "PATCH"


class TestExpectedBusinessErrors:
    """400/404/409 are part of the capability's contract — returned as data, never raised."""

    async def test_404_not_found_returns_success_false_with_structured_error(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return _json_response(404, {"error": "category_not_found"})

        adapter = _adapter(handler)
        result = await adapter.invoke_tool("finance.category.update", {"transactionId": "tx-1", "source": "manual", "category": "x"}, TENANT, CORRELATION)

        assert result["success"] is False
        assert result["error"]["code"] == "category_not_found"
        assert result["error"]["http_status"] == 404

    async def test_409_ambiguity_preserves_the_candidate_list(self):
        matches = [
            {"source": "manual", "id": "tx-1", "description": "Uber viagem", "amount": 20, "date": "2026-08-11"},
            {"source": "manual", "id": "tx-2", "description": "Uber viagem", "amount": 20, "date": "2026-08-12"},
        ]

        def handler(_request: httpx.Request) -> httpx.Response:
            return _json_response(409, {"error": "transaction_ambiguous", "message": "...", "matches": matches})

        adapter = _adapter(handler)
        result = await adapter.invoke_tool("finance.category.update", {"description": "Uber", "amount": 20, "category": "Transporte"}, TENANT, CORRELATION)

        assert result["success"] is False
        assert result["error"]["code"] == "transaction_ambiguous"
        # The candidate list must survive the adapter boundary intact — the
        # specialist needs it verbatim to ask the user which one (doc 00 §7.1).
        assert result["error"]["details"]["matches"] == matches

    async def test_400_validation_error_returns_success_false(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return _json_response(400, {"error": "invalid_amount"})

        adapter = _adapter(handler)
        result = await adapter.invoke_tool("finance.manual.create", {"amount": 0, "direction": "expense", "description": "x"}, TENANT, CORRELATION)
        assert result == {"success": False, "error": {"code": "invalid_amount", "message": "", "http_status": 400, "details": {"error": "invalid_amount"}}}


class TestRealFailures:
    """Transport errors, auth rejection, and unmapped tools must never look like success."""

    async def test_401_raises_runtime_error(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "unauthorized"})

        adapter = _adapter(handler)
        with pytest.raises(RuntimeError, match="401"):
            await adapter.invoke_tool("finance.summary.read", {}, TENANT, CORRELATION)

    async def test_500_raises_runtime_error_not_returned_as_data(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "internal"})

        adapter = _adapter(handler)
        with pytest.raises(RuntimeError):
            await adapter.invoke_tool("finance.summary.read", {}, TENANT, CORRELATION)

    async def test_connection_error_raises_runtime_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        adapter = _adapter(handler)
        with pytest.raises(RuntimeError, match="inacessível"):
            await adapter.invoke_tool("finance.summary.read", {}, TENANT, CORRELATION)

    async def test_unmapped_tool_name_raises_without_making_a_request(self):
        called = False

        def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return _json_response(200, {})

        adapter = _adapter(handler)
        with pytest.raises(RuntimeError, match="não mapeada"):
            await adapter.invoke_tool("finance.not.a.real.capability", {}, TENANT, CORRELATION)
        assert called is False

    async def test_missing_token_raises_without_making_a_request(self):
        called = False

        def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return _json_response(200, {})

        adapter = _adapter(handler, token="")
        with pytest.raises(RuntimeError, match="FINANCE_API_TOKEN"):
            await adapter.invoke_tool("finance.summary.read", {}, TENANT, CORRELATION)
        assert called is False

    async def test_guard_rejects_forbidden_argument_keys(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return _json_response(200, {})

        adapter = _adapter(handler)
        with pytest.raises(ForbiddenArgumentError):
            await adapter.invoke_tool("finance.summary.read", {"command": "rm -rf /"}, TENANT, CORRELATION)


class TestHealth:
    async def test_health_true_on_200(self):
        adapter = _adapter(lambda r: httpx.Response(200, json={"ok": True}))
        assert await adapter.health() is True

    async def test_health_false_on_error_status(self):
        adapter = _adapter(lambda r: httpx.Response(503))
        assert await adapter.health() is False

    async def test_health_false_on_transport_error_never_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        adapter = _adapter(handler)
        assert await adapter.health() is False
