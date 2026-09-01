"""
tests/unit/test_finance_api_route_selection.py — F2B.

Duas mecânicas do FinanceApiAdapter que as capabilities de F2B introduziram:

1. PATH PARAMS. Rotas como
   /api/finance/clarifications/{clarificationId}/resolve são preenchidas a
   partir de `arguments`, e o argumento consumido é REMOVIDO do corpo/query —
   nunca duplicado nos dois lugares. O valor é percent-encoded, então um id
   hostil não escapa do segmento.

2. SELEÇÃO DE ROTA POR `mode`. Duas capabilities cobrem mais de uma rota. A
   escolha vem de um enum interno declarado no input_schema do YAML — nunca de
   heurística sobre o texto do usuário, nunca de decisão de LLM. `mode` é
   consumido pelo adapter e não é repassado à Finance API.

Tudo com httpx.MockTransport: exercita a requisição real (método, path,
query, corpo), não só a lógica de decisão.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import yaml

from cognitive.adapters.finance_api.client import (
    _MODE_ROUTES,
    _ROUTES,
    FinanceApiAdapter,
    _render_path,
    _resolve_route,
)
from cognitive.registry.registry import InMemoryCapabilityRegistry

TENANT = "tenant-f2b"
CORRELATION = "corr-f2b"
TOKEN = "test-finance-token"


def _capture(status: int = 200, body: dict[str, Any] | None = None):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        seen["body"] = json.loads(request.content) if request.content else None
        return httpx.Response(status, json=body if body is not None else {"ok": True})

    return seen, handler


def _adapter(handler) -> FinanceApiAdapter:
    return FinanceApiAdapter(
        base_url="http://finance.local", token=TOKEN, transport=httpx.MockTransport(handler)
    )


# ─── path params ───────────────────────────────────────────────────────────


class TestPathParams:
    def test_render_path_fills_and_removes_the_param(self):
        path, remaining = _render_path(
            "/api/finance/clarifications/{clarificationId}/resolve",
            {"clarificationId": "clar-1", "freeText": "foi mercado"},
        )
        assert path == "/api/finance/clarifications/clar-1/resolve"
        assert remaining == {"freeText": "foi mercado"}

    def test_render_path_does_not_mutate_the_caller_dict(self):
        arguments = {"clarificationId": "clar-1", "freeText": "x"}
        _render_path("/api/finance/clarifications/{clarificationId}/resolve", arguments)
        assert arguments == {"clarificationId": "clar-1", "freeText": "x"}

    def test_render_path_percent_encodes_hostile_ids(self):
        """Um id com barras não pode escapar do segmento da rota."""
        path, _ = _render_path(
            "/api/finance/corrections/{transactionId}", {"transactionId": "../../admin"}
        )
        assert path == "/api/finance/corrections/..%2F..%2Fadmin"

    @pytest.mark.parametrize("bad", [None, "", "   "])
    def test_missing_path_param_fails_closed(self, bad):
        with pytest.raises(RuntimeError, match="parâmetro de rota"):
            _render_path("/api/finance/clarifications/{clarificationId}/resolve", {"clarificationId": bad})

    async def test_post_with_path_param_does_not_repeat_it_in_the_body(self):
        seen, handler = _capture(200, {"clarification": {"id": "clar-1"}})
        await _adapter(handler).invoke_tool(
            "finance.clarification.resolve",
            {"clarificationId": "clar-1", "freeText": "foi mercado", "resolvedByActorId": "actor-owner"},
            TENANT,
            CORRELATION,
        )
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/finance/clarifications/clar-1/resolve"
        assert "clarificationId" not in seen["body"]
        assert seen["body"] == {"freeText": "foi mercado", "resolvedByActorId": "actor-owner"}

    async def test_get_with_path_param_does_not_repeat_it_in_the_query(self):
        seen, handler = _capture(200, {"corrections": []})
        await _adapter(handler).invoke_tool(
            "finance.correction.apply",
            {"mode": "history", "transactionId": "tx-9"},
            TENANT,
            CORRELATION,
        )
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/finance/corrections/tx-9"
        assert seen["params"] == {}

    async def test_deliver_binds_the_message_id_on_the_clarification_route(self):
        seen, handler = _capture(200, {"clarificationId": "clar-1"})
        await _adapter(handler).invoke_tool(
            "finance.clarification.deliver",
            {"clarificationId": "clar-1", "deliveryMessageId": "wamid.ABC", "deliveryChatId": "grp@g.us"},
            TENANT,
            CORRELATION,
        )
        assert seen["path"] == "/api/finance/clarifications/clar-1/delivery"
        assert seen["body"] == {"deliveryMessageId": "wamid.ABC", "deliveryChatId": "grp@g.us"}

    async def test_clarification_list_propagates_delivery_message_id_and_any(self):
        """F2B durable lookup: GET query deve carregar deliveryMessageId+status=any."""
        clar_a = {
            "id": "clar-A",
            "status": "open",
            "deliveryMessageId": "deliv-A",
        }
        seen, handler = _capture(200, {"clarifications": [clar_a], "total": 1})
        result = await _adapter(handler).invoke_tool(
            "finance.clarification.list",
            {"deliveryMessageId": "deliv-A", "status": "any", "limit": 1},
            TENANT,
            CORRELATION,
        )
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/finance/clarifications"
        assert seen["params"]["deliveryMessageId"] == "deliv-A"
        assert seen["params"]["status"] == "any"
        assert seen["params"]["limit"] == "1"
        assert result["success"] is True
        assert result["data"]["clarifications"][0]["id"] == "clar-A"


# ─── seleção por mode ──────────────────────────────────────────────────────


class TestModeRouteSelection:
    async def test_correction_apply_defaults_to_the_write_route(self):
        seen, handler = _capture(201, {"correction": {"id": "corr-1"}})
        await _adapter(handler).invoke_tool(
            "finance.correction.apply",
            {"transactionId": "tx-1", "field": "category", "value": "Alimentação"},
            TENANT,
            CORRELATION,
        )
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/finance/corrections"
        assert seen["body"] == {"transactionId": "tx-1", "field": "category", "value": "Alimentação"}

    async def test_correction_history_mode_selects_the_read_route(self):
        seen, handler = _capture(200, {"corrections": []})
        await _adapter(handler).invoke_tool(
            "finance.correction.apply", {"mode": "history", "transactionId": "tx-1"}, TENANT, CORRELATION
        )
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/finance/corrections/tx-1"

    @pytest.mark.parametrize(
        "mode,expected_path",
        [("export", "/api/finance/onboarding/export"), ("import", "/api/finance/onboarding/import")],
    )
    async def test_onboarding_batch_routes_by_mode(self, mode, expected_path):
        seen, handler = _capture(200, {"batchId": "b-1"})
        await _adapter(handler).invoke_tool(
            "finance.onboarding.batch", {"mode": mode, "batchId": "b-1"}, TENANT, CORRELATION
        )
        assert seen["path"] == expected_path

    async def test_mode_is_consumed_and_never_forwarded(self):
        """`mode` é seleção de rota, não payload da Finance API."""
        seen, handler = _capture(200, {"batchId": "b-1"})
        await _adapter(handler).invoke_tool(
            "finance.onboarding.batch",
            {"mode": "export", "competenceMonth": "2026-08", "limit": 20},
            TENANT,
            CORRELATION,
        )
        assert "mode" not in seen["body"]
        assert seen["body"] == {"competenceMonth": "2026-08", "limit": 20}

    async def test_invoke_tool_does_not_mutate_the_caller_arguments(self):
        _, handler = _capture(200, {"batchId": "b-1"})
        arguments = {"mode": "export", "limit": 20}
        await _adapter(handler).invoke_tool("finance.onboarding.batch", arguments, TENANT, CORRELATION)
        assert arguments == {"mode": "export", "limit": 20}

    def test_unknown_mode_fails_closed_without_echoing_the_value(self):
        """Modo inválido não vira rota default silenciosa — e o erro não ecoa
        o valor recebido (pode carregar texto do usuário)."""
        with pytest.raises(RuntimeError) as excinfo:
            _resolve_route("finance.onboarding.batch", {"mode": "meu-segredo-<script>"})
        assert "meu-segredo" not in str(excinfo.value)
        assert "'mode'" in str(excinfo.value)

    def test_missing_required_mode_fails_closed(self):
        """finance.onboarding.batch declara `mode` required e não tem default."""
        with pytest.raises(RuntimeError):
            _resolve_route("finance.onboarding.batch", {"batchId": "b-1"})

    def test_unmapped_capability_fails_closed(self):
        with pytest.raises(RuntimeError, match="não mapeada"):
            _resolve_route("finance.inexistente", {})


# ─── contrato adapter <-> registry ────────────────────────────────────────


class TestRoutingContractMatchesTheRegistry:
    def test_every_finance_capability_has_a_route(self):
        registry = InMemoryCapabilityRegistry()
        registry.load_from_yaml()
        finance_ids = {c.id for c in registry.list_all() if c.id.startswith("finance.")}
        routed = set(_ROUTES) | set(_MODE_ROUTES)
        assert finance_ids - routed == set()

    def test_every_route_belongs_to_a_registered_capability(self):
        registry = InMemoryCapabilityRegistry()
        registry.load_from_yaml()
        finance_ids = {c.id for c in registry.list_all() if c.id.startswith("finance.")}
        assert (set(_ROUTES) | set(_MODE_ROUTES)) - finance_ids == set()

    def test_mode_values_come_from_the_yaml_enum_not_from_free_text(self):
        """A fonte da verdade de `mode` é o input_schema do YAML — não há
        caminho por texto livre do usuário."""
        base = "cognitive/registry/capabilities"
        for capability_id, (arg_name, _default, routes) in _MODE_ROUTES.items():
            import pathlib

            path = pathlib.Path(__file__).resolve().parents[2] / base / f"{capability_id}.yaml"
            schema = yaml.safe_load(path.read_text(encoding="utf-8"))["input_schema"]
            declared = schema["properties"][arg_name]
            assert set(declared["enum"]) == set(routes), capability_id
            assert declared["type"] == "string", capability_id
