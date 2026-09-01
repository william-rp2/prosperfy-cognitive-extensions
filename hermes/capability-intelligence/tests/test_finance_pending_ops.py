"""F2B — pending_count / pending_list map to finance.clarification.list."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

# Stub Hermes tool registry before importing finance_tools (registers at import).
_fake_registry = types.SimpleNamespace(register=lambda **kwargs: None)


def _tool_error(msg, **extra):
    return json.dumps({"error": msg, **extra}, ensure_ascii=False)


sys.modules.setdefault(
    "tools.registry",
    types.SimpleNamespace(registry=_fake_registry, tool_error=_tool_error),
)
sys.modules.setdefault("tools", types.ModuleType("tools"))
sys.modules["tools"].registry = sys.modules["tools.registry"]  # type: ignore[attr-defined]
sys.modules.setdefault(
    "utils",
    types.SimpleNamespace(env_var_enabled=lambda *_a, **_k: True),
)

_TOOLS_DIR = Path(__file__).resolve().parents[2] / "p2-finance-whatsapp"
sys.path.insert(0, str(_TOOLS_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from capability_intelligence.capability_router import (  # noqa: E402
    resolve_specialist_route,
    resolve_turn_toolsets,
    route_toolsets,
)


def test_pending_phrases_route_finance_without_llm():
    assert resolve_specialist_route("Quantas pendências financeiras tenho?") == "FINANCE"
    assert resolve_specialist_route("Traga as pendências de agosto.") == "FINANCE"
    assert resolve_specialist_route("Tenho pendências no projeto") != "FINANCE"


def test_finance_toolsets_exclude_bash():
    assert route_toolsets("FINANCE") == ["finance"]
    assert "bash" not in route_toolsets("FINANCE")
    route, toolsets = resolve_turn_toolsets("Quantas pendências financeiras tenho?")
    assert route == "FINANCE"
    assert toolsets == ["finance"]
    assert "bash" not in toolsets


def test_normal_chat_has_no_finance_tool():
    route, toolsets = resolve_turn_toolsets("Oi, tudo bem?")
    assert route == "NORMAL"
    assert toolsets == []
    assert "finance" not in toolsets


def test_pending_count_maps_to_clarification_list():
    import finance_tools as ft

    captured: dict = {}

    def fake_call(capability_id, params):
        captured["capability_id"] = capability_id
        captured["params"] = params
        return {"clarifications": [], "total": 7}

    with patch.object(ft, "_call", side_effect=fake_call):
        raw = ft.finance(operation="pending_count")
    body = json.loads(raw)
    assert body["ok"] is True
    assert body["capability"] == "finance.clarification.list"
    assert body["operation"] == "pending_count"
    assert captured["capability_id"] == "finance.clarification.list"
    assert captured["params"]["status"] == "open"
    assert captured["params"]["limit"] == 1
    assert body["data"]["total"] == 7


def test_pending_list_month_alias_to_competence_month():
    import finance_tools as ft

    captured: dict = {}

    def fake_call(capability_id, params):
        captured["capability_id"] = capability_id
        captured["params"] = params
        return {"clarifications": [{"id": "c1"}], "total": 1}

    with patch.object(ft, "_call", side_effect=fake_call):
        raw = ft.finance(operation="pending_list", month="2026-08", limit=20)
    body = json.loads(raw)
    assert body["capability"] == "finance.clarification.list"
    assert captured["params"]["competenceMonth"] == "2026-08"
    assert "month" not in captured["params"]
    assert captured["params"]["status"] == "open"
    assert captured["params"]["limit"] == 20


def test_pending_list_prefers_explicit_competence_month():
    import finance_tools as ft

    captured: dict = {}

    def fake_call(capability_id, params):
        captured["params"] = params
        return {"clarifications": [], "total": 0}

    with patch.object(ft, "_call", side_effect=fake_call):
        ft.finance(
            operation="pending_list",
            month="2026-01",
            competenceMonth="2026-08",
        )
    assert captured["params"]["competenceMonth"] == "2026-08"
    assert "month" not in captured["params"]


def test_transport_spoof_stripped_on_pending():
    import finance_tools as ft

    captured: dict = {}

    def fake_call(capability_id, params):
        captured["params"] = params
        return {"clarifications": [], "total": 0}

    with patch.object(ft, "_call", side_effect=fake_call):
        ft.finance(
            operation="pending_count",
            chat_id="spoof@g.us",
            transport_principal="attacker",
            channel={"chat_id": "spoof"},
        )
    assert "chat_id" not in captured["params"]
    assert "transport_principal" not in captured["params"]
    assert "channel" not in captured["params"]


def test_ops_table_pending_capabilities():
    import finance_tools as ft

    assert ft._OPS["pending_count"][0] == "finance.clarification.list"
    assert ft._OPS["pending_list"][0] == "finance.clarification.list"
    enum = ft.FINANCE_SCHEMA["parameters"]["properties"]["operation"]["enum"]
    assert "pending_count" in enum
    assert "pending_list" in enum
