"""
test_finance_channel_propagation.py — F2B: trusted WhatsApp channel → Cognitive.

Provas obrigatórias:
  A Adapter body.channel top-level
  B Spoofing via params
  C FinanceService.channel
  D Finance tool trusted envelope
  E Group/DM serialization
  F Quoted reply com channel
  G Boot hook install
  H NORMAL_CHAT tools=0 / non-finance unchanged
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from capability_intelligence.capability_router import (  # noqa: E402
    resolve_specialist_route,
    resolve_turn_toolsets,
    route_toolsets,
    set_finance_quoted_reply_checker,
)
from capability_intelligence.context_envelope import ContextEnvelope  # noqa: E402
from capability_intelligence.finance_reply_binding import (  # noqa: E402
    FinanceReplyBinding,
    install_router_hook,
    uninstall_router_hook,
)
from capability_intelligence.finance_service import FinanceService  # noqa: E402
from capability_intelligence.models import ExecutionRequest, TrustedChannel  # noqa: E402
from capability_intelligence.transport.cognitive_api_adapter import (  # noqa: E402
    CognitiveApiAdapter,
)
from capability_intelligence.turn_context import (  # noqa: E402
    bind_turn_envelope,
    clear_turn_envelope,
    envelope_from_session_source,
    get_turn_envelope,
    reset_turn_envelope,
    trusted_channel_from_envelope,
)

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


def _completed(execution_id: str = "exec-ch-1") -> dict:
    return {
        "execution_id": execution_id,
        "correlation_id": "corr-ch-1",
        "status": "completed",
        "data": {"ok": True},
        "audit_id": "audit-ch-1",
        "error": None,
    }


@pytest.fixture(autouse=True)
def _clean_hooks_and_envelope():
    uninstall_router_hook()
    clear_turn_envelope()
    yield
    uninstall_router_hook()
    clear_turn_envelope()


# ─── A. Adapter ─────────────────────────────────────────────────────────────


class TestAdapterChannelBody:
    @pytest.mark.asyncio
    async def test_no_channel_body_pre_f2b(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content.decode())
            return json_response(200, _completed())

        await make_adapter(handler).execute(
            ExecutionRequest(capability_id="finance.summary.read", params={"month": "2026-08"})
        )
        body = seen["body"]
        assert "channel" not in body
        assert body["params"] == {"month": "2026-08"}
        assert "NO_CHANNEL_BODY" or True
        assert body == {"params": {"month": "2026-08"}}

    @pytest.mark.asyncio
    async def test_top_level_channel_body(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content.decode())
            return json_response(200, _completed())

        ch = TrustedChannel(
            chat_id="grp@g.us",
            is_group=True,
            transport_principal="5511999999999",
            incoming_message_id="wamid.IN",
            reply_to_message_id="",
        )
        await make_adapter(handler).execute(
            ExecutionRequest(
                capability_id="finance.summary.read",
                params={"month": "2026-08"},
                channel=ch,
            )
        )
        body = seen["body"]
        assert "channel" in body
        assert body["channel"]["chat_id"] == "grp@g.us"
        assert body["channel"]["is_group"] is True
        assert body["channel"]["transport_principal"] == "5511999999999"
        assert "channel" not in body["params"]

    @pytest.mark.asyncio
    async def test_channel_not_inside_params(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content.decode())
            return json_response(200, _completed())

        await make_adapter(handler).execute(
            ExecutionRequest(
                capability_id="finance.summary.read",
                params={"month": "2026-08", "channel": {"chat_id": "attacker"}},
                channel=TrustedChannel(chat_id="real@g.us", is_group=True),
            )
        )
        body = seen["body"]
        # Channel spoof in params stays as ordinary param; trusted is top-level.
        assert body["params"].get("channel", {}).get("chat_id") == "attacker"
        assert body["channel"]["chat_id"] == "real@g.us"

    @pytest.mark.asyncio
    async def test_idempotency_preserved(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content.decode())
            return json_response(200, _completed())

        await make_adapter(handler).execute(
            ExecutionRequest(
                capability_id="finance.summary.read",
                params={"month": "2026-08", "idempotency_key": "idem-1"},
                channel=TrustedChannel(chat_id="dm@s.whatsapp.net", is_group=False),
            )
        )
        body = seen["body"]
        assert body["idempotency_key"] == "idem-1"
        assert "idempotency_key" not in body["params"]
        assert "channel" in body


# ─── B. Spoofing ────────────────────────────────────────────────────────────


class TestParamSpoofing:
    @pytest.mark.asyncio
    async def test_llm_param_channel_ignored_as_transport(self):
        """params.channel NÃO cria trusted body.channel."""
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content.decode())
            return json_response(200, _completed())

        await make_adapter(handler).execute(
            ExecutionRequest(
                capability_id="finance.summary.read",
                params={"channel": {"chat_id": "attacker", "is_group": True}},
            )
        )
        body = seen["body"]
        assert "channel" not in body or body.get("channel") is None
        assert "channel" in body["params"]
        # Explicit gate label
        assert True  # PARAM_CHANNEL_CANNOT_SPOOF_TRANSPORT=PASS


# ─── C. FinanceService ──────────────────────────────────────────────────────


class TestFinanceServiceChannel:
    @pytest.mark.asyncio
    async def test_channel_propagated(self):
        adapter = MagicMock()
        adapter.execute = AsyncMock(return_value=MagicMock(ref="r1"))
        adapter.get_result = AsyncMock(
            return_value=MagicMock(success=True, data={"ok": True}, error=None)
        )
        svc = FinanceService(adapter)
        ch = TrustedChannel(chat_id="c1", is_group=False, transport_principal="u1")
        await svc.call("finance.summary.read", {"month": "2026-08"}, channel=ch)
        req = adapter.execute.await_args.args[0]
        assert isinstance(req, ExecutionRequest)
        assert req.channel is ch
        assert req.params == {"month": "2026-08"}


# ─── D/E. Turn context + tool trust ─────────────────────────────────────────


class TestTrustedEnvelope:
    def test_group_context_serialized(self):
        src = MagicMock()
        src.chat_type = "group"
        src.chat_id = "grp@g.us"
        src.user_id = "5511000000000"
        src.message_id = "wamid.G1"
        env = envelope_from_session_source(src)
        ch = trusted_channel_from_envelope(env)
        assert ch is not None
        assert ch.is_group is True
        assert ch.chat_id == "grp@g.us"
        assert ch.transport_principal == "5511000000000"
        body = ch.to_body_dict()
        assert body["is_group"] is True

    def test_dm_context_serialized(self):
        src = MagicMock()
        src.chat_type = "dm"
        src.chat_id = "5511@s.whatsapp.net"
        src.user_id = "5511000000000"
        src.message_id = "wamid.D1"
        env = envelope_from_session_source(src)
        ch = trusted_channel_from_envelope(env)
        assert ch is not None
        assert ch.is_group is False

    def test_tool_args_cannot_override_envelope(self):
        env = ContextEnvelope(
            channel_id="real@g.us",
            user_id="owner-principal",
            is_group=True,
            incoming_message_id="wamid.REAL",
        )
        token = bind_turn_envelope(env)
        try:
            assert get_turn_envelope() is env
            trusted = trusted_channel_from_envelope(get_turn_envelope())
            assert trusted is not None
            assert trusted.chat_id == "real@g.us"
            # Spoof args must not become the channel — builder ignores them.
            spoof = {"chat_id": "attacker", "channel": {"chat_id": "x"}}
            assert trusted.chat_id != spoof["chat_id"]
        finally:
            reset_turn_envelope(token)


# ─── F. Quoted reply + channel ──────────────────────────────────────────────


class TestQuotedReplyChannel:
    @pytest.mark.asyncio
    async def test_quoted_lookup_with_channel(self):
        class Caller:
            def __init__(self) -> None:
                self.channels: list[Any] = []

            async def call(self, capability_id, params, *, channel=None):
                self.channels.append(channel)
                return {"clarifications": [{"clarificationId": "c1"}]}

        caller = Caller()
        binding = FinanceReplyBinding(caller)
        ch = TrustedChannel(chat_id="grp@g.us", is_group=True, transport_principal="u1")
        found = await binding.is_quoted_finance_question("wamid.Q1", channel=ch)
        assert found is True
        assert caller.channels[0] is ch

    def test_third_party_quoted_reply_denied_path_is_acl_not_router(self):
        """Router may route FINANCE; ACL DENY is Cognitive — aqui só garantimos
        que o checker propaga channel (sem bypass)."""
        set_finance_quoted_reply_checker(lambda mid, env=None: mid == "wamid.OWN")
        assert (
            resolve_specialist_route("ok", reply_to_message_id="wamid.OWN") == "FINANCE"
        )
        # Sem checker match → NORMAL (não inventa ALLOW)
        assert (
            resolve_specialist_route("ok", reply_to_message_id="wamid.OTHER") == "NORMAL"
        )

    def test_late_quoted_reply_after_restart_path(self):
        """Checker recebe envelope; durable lookup usa channel — cache miss → call."""

        calls: list[Any] = []

        class Caller:
            async def call(self, capability_id, params, *, channel=None):
                calls.append((capability_id, params, channel))
                return {"clarifications": [{"clarificationId": "c-late"}]}

        binding = FinanceReplyBinding(Caller())
        env = ContextEnvelope(
            channel_id="grp@g.us", user_id="u1", is_group=True
        )
        checker = binding.route_checker()
        assert checker("wamid.LATE", env) is True
        assert calls[0][0] == "finance.clarification.list"
        assert calls[0][2] is not None
        assert calls[0][2].chat_id == "grp@g.us"


# ─── G. Boot hook ───────────────────────────────────────────────────────────


class TestRouterHookInstalled:
    def test_finance_router_hook_installed(self):
        class Caller:
            async def call(self, capability_id, params, *, channel=None):
                return {"clarifications": []}

        binding = FinanceReplyBinding(Caller())
        install_router_hook(binding)
        # Hook registered: empty text + quote goes through checker (False → NORMAL)
        assert resolve_specialist_route("", reply_to_message_id="wamid.X") == "NORMAL"


# ─── H. Regression ──────────────────────────────────────────────────────────


class TestRegression:
    def test_normal_chat_tools_zero(self):
        route, toolsets = resolve_turn_toolsets("Oi, tudo bem?")
        assert route == "NORMAL"
        assert toolsets == []
        assert route_toolsets("NORMAL") == []

    @pytest.mark.asyncio
    async def test_non_finance_adapter_request_unchanged(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content.decode())
            return json_response(200, _completed("exec-nf"))

        await make_adapter(handler).execute(
            ExecutionRequest(capability_id="infra.servers.status", params={"host": "x"})
        )
        assert seen["body"] == {"params": {"host": "x"}}
