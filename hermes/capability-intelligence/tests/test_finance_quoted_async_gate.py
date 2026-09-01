"""
tests/test_finance_quoted_async_gate.py — F2B quoted reply async pré-LLM.

Prova o bug real do gateway (event loop ativo + cache frio) e o contrato:

  reply_to → durable lookup awaitable → bind_reply → resolve → persist
  → resposta determinística; LLM_CALLED=NO
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from capability_intelligence.capability_router import (  # noqa: E402
    resolve_specialist_route,
    resolve_turn_toolsets,
)
from capability_intelligence.canonical_finance_actor import (  # noqa: E402
    resolve_canonical_finance_actor,
)
from capability_intelligence.context_envelope import ContextEnvelope  # noqa: E402
from capability_intelligence.finance_quoted_gate import (  # noqa: E402
    SAFE_ERROR_MESSAGE,
    try_handle_quoted_finance_reply,
)
from capability_intelligence.finance_reply_binding import (  # noqa: E402
    BindingStatus,
    FinanceReplyBinding,
    install_router_hook,
    uninstall_router_hook,
)
from capability_intelligence.models import TrustedChannel  # noqa: E402
from capability_intelligence.turn_context import (  # noqa: E402
    envelope_from_session_source,
    trusted_channel_from_envelope,
)

DELIVERY_ID = "wamid.PERGUNTA-TESTE-F2B"
OTHER_DELIVERY = "wamid.OUTRA-PERGUNTA"
REPLY_ID = "wamid.RESPOSTA-MERCADO"
CLAR_A = "clar-a"
CLAR_B = "clar-b"
OWNER_ACTOR = "finance-owner-1"
OWNER_PRINCIPAL = "5519999999999@s.whatsapp.net"
THIRD_PRINCIPAL = "5511888888888@s.whatsapp.net"
STRANGER = "5521777777777@s.whatsapp.net"
FINANCE_GROUP = "finance-group@g.us"
FINANCE_DM = "5519999999999@s.whatsapp.net"
WRONG_GROUP = "familia@g.us"


class FakeCaller:
    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.channels: list[Any] = []
        self._responses = responses or {}

    async def call(
        self,
        capability_id: str,
        params: dict[str, Any],
        *,
        channel: Any = None,
    ) -> dict[str, Any]:
        self.calls.append((capability_id, dict(params)))
        self.channels.append(channel)
        response = self._responses.get(capability_id, {})
        if callable(response):
            return response(params)
        if isinstance(response, Exception):
            raise response
        return response

    def caps(self) -> list[str]:
        return [c for c, _ in self.calls]


def _open(clar_id: str = CLAR_A, **overrides: Any) -> dict[str, Any]:
    base = {
        "clarificationId": clar_id,
        "transactionId": "tx-1",
        "questionType": "CATEGORY",
        "status": "open",
        "merchant": "Supermercado",
    }
    base.update(overrides)
    return base


def _envelope(
    *,
    reply_to: str = DELIVERY_ID,
    user_id: str = OWNER_PRINCIPAL,
    chat_id: str = FINANCE_GROUP,
    is_group: bool = True,
) -> ContextEnvelope:
    return ContextEnvelope(
        conversation_id=chat_id,
        channel_id=chat_id,
        incoming_message_id=REPLY_ID,
        reply_to_message_id=reply_to,
        user_id=user_id,
        is_group=is_group,
    )


@pytest.fixture(autouse=True)
def _clean_hook(monkeypatch):
    uninstall_router_hook()
    monkeypatch.setenv(
        "FINANCE_ACTOR_BINDINGS",
        f"{OWNER_PRINCIPAL}={OWNER_ACTOR}",
    )
    yield
    uninstall_router_hook()


# ─── regressão do bug: loop ativo + cache frio ──────────────────────────────


class TestAsyncColdCacheQuote:
    async def test_running_event_loop_cold_cache_must_detect_quote(self):
        """ASYNC_COLD_CACHE_QUOTE / DURABLE_LOOKUP_IN_RUNNING_LOOP.

        Antes do fix, route_checker() retornava False aqui e o gateway ia
        para NORMAL. O gate async DEVE detectar.
        """
        caller = FakeCaller(
            {
                "finance.clarification.list": {"clarifications": [_open()]},
                "finance.clarification.resolve": {
                    "resolved": True,
                    "clarification": {"id": CLAR_A},
                },
            }
        )
        binding = FinanceReplyBinding(caller)
        # Prova que o checker síncrono AINDA não faz I/O com loop ativo (cache frio).
        assert binding.route_checker()(DELIVERY_ID) is False
        assert caller.calls == []

        result = await try_handle_quoted_finance_reply(
            binding,
            message_text="Mercado",
            envelope=_envelope(),
        )
        assert result.durable_lookup_called is True
        assert result.quoted_finance is True
        assert result.skip_llm is True
        assert result.bind_reply_called is True
        assert "finance.clarification.resolve" in caller.caps()
        assert result.outcome is not None
        assert result.outcome.status is BindingStatus.RESOLVED
        assert result.success_text_emitted is True
        assert "Anotado" in (result.user_message or "")

    async def test_post_restart_cold_process_cache(self):
        """Nova instância = cache vazio; binding só no store/API fake."""
        store = {
            "finance.clarification.list": {"clarifications": [_open()]},
            "finance.clarification.resolve": {"resolved": True},
        }
        binding1 = FinanceReplyBinding(FakeCaller(store))
        # "restart": nova instância, mesmo store durável
        binding2 = FinanceReplyBinding(FakeCaller(store))
        assert binding2._cache.get(DELIVERY_ID) is None

        result = await try_handle_quoted_finance_reply(
            binding2,
            message_text="Mercado",
            envelope=_envelope(),
        )
        assert result.outcome is not None
        assert result.outcome.status is BindingStatus.RESOLVED


# ─── exact bind + persist first ─────────────────────────────────────────────


class TestExactBindAndPersistFirst:
    async def test_exact_binding_among_many_open(self):
        def list_resp(params: dict[str, Any]) -> dict[str, Any]:
            mid = params.get("deliveryMessageId")
            if mid == DELIVERY_ID:
                return {"clarifications": [_open(CLAR_A, merchant="Dalben")]}
            if mid == OTHER_DELIVERY:
                return {"clarifications": [_open(CLAR_B, merchant="Shell")]}
            # loose fallback
            return {
                "clarifications": [
                    _open(CLAR_A, merchant="Dalben"),
                    _open(CLAR_B, merchant="Shell"),
                ]
            }

        caller = FakeCaller(
            {
                "finance.clarification.list": list_resp,
                "finance.clarification.resolve": {"resolved": True},
            }
        )
        result = await try_handle_quoted_finance_reply(
            FinanceReplyBinding(caller),
            message_text="Mercado",
            envelope=_envelope(reply_to=DELIVERY_ID),
        )
        assert result.outcome is not None
        assert result.outcome.clarification_id == CLAR_A
        resolve_calls = [p for c, p in caller.calls if c == "finance.clarification.resolve"]
        assert len(resolve_calls) == 1
        assert resolve_calls[0]["clarificationId"] == CLAR_A
        assert resolve_calls[0]["resolvedByActorId"] == OWNER_ACTOR
        assert OWNER_PRINCIPAL not in resolve_calls[0].values()

    async def test_resolve_fails_emits_no_success_text(self):
        caller = FakeCaller(
            {
                "finance.clarification.list": {"clarifications": [_open()]},
                "finance.clarification.resolve": RuntimeError(
                    "Denied: Acesso financeiro não autorizado"
                ),
            }
        )
        result = await try_handle_quoted_finance_reply(
            FinanceReplyBinding(caller),
            message_text="Mercado",
            envelope=_envelope(),
        )
        assert result.success_text_emitted is False
        assert result.user_message == SAFE_ERROR_MESSAGE
        assert "Anotado" not in (result.user_message or "")
        assert "Atualizei" not in (result.user_message or "")
        assert "Pendência respondida" not in (result.user_message or "")

    async def test_late_reply_idempotent(self):
        caller = FakeCaller(
            {
                "finance.clarification.list": {
                    "clarifications": [
                        _open(status="resolved", resolvedAt="2026-09-01T10:00:00Z")
                    ]
                }
            }
        )
        result = await try_handle_quoted_finance_reply(
            FinanceReplyBinding(caller),
            message_text="Mercado",
            envelope=_envelope(),
        )
        assert result.outcome is not None
        assert result.outcome.status is BindingStatus.ALREADY_RESOLVED
        assert "finance.clarification.resolve" not in caller.caps()
        assert result.success_text_emitted is True  # mensagem de already_resolved ok


# ─── security ───────────────────────────────────────────────────────────────


class TestQuotedSecurity:
    async def test_third_party_quote_deny_no_resolve_success(self):
        def list_ok(_p):
            return {"clarifications": [_open()]}

        def resolve_deny(_p):
            raise RuntimeError("Denied: Acesso financeiro não autorizado")

        caller = FakeCaller(
            {
                "finance.clarification.list": list_ok,
                "finance.clarification.resolve": resolve_deny,
            }
        )
        # Actor canônico do terceiro NÃO está no mapping owner → resolve_canonical
        # retorna None se usarmos principal terceiro... Forçamos bind com actor
        # terceiro explícito para simular mapping errado/extra e ACL deny no resolve.
        result = await try_handle_quoted_finance_reply(
            FinanceReplyBinding(caller),
            message_text="Mercado",
            envelope=_envelope(user_id=THIRD_PRINCIPAL),
            canonical_actor_id="actor-third",
        )
        assert result.success_text_emitted is False
        assert result.user_message == SAFE_ERROR_MESSAGE

    async def test_unknown_principal_no_canonical_actor(self):
        caller = FakeCaller(
            {"finance.clarification.list": {"clarifications": [_open()]}}
        )
        result = await try_handle_quoted_finance_reply(
            FinanceReplyBinding(caller),
            message_text="Mercado",
            envelope=_envelope(user_id=STRANGER),
        )
        assert result.success_text_emitted is False
        assert "finance.clarification.resolve" not in caller.caps()
        assert result.bind_reply_called is False

    async def test_transport_principal_rejected_as_actor(self):
        caller = FakeCaller(
            {"finance.clarification.list": {"clarifications": [_open()]}}
        )
        result = await try_handle_quoted_finance_reply(
            FinanceReplyBinding(caller),
            message_text="Mercado",
            envelope=_envelope(),
            canonical_actor_id=OWNER_PRINCIPAL,  # spoof: JID as actor
        )
        assert result.success_text_emitted is False
        assert "finance.clarification.resolve" not in caller.caps()

    async def test_owner_group_and_dm(self):
        for is_group, chat in ((True, FINANCE_GROUP), (False, FINANCE_DM)):
            caller = FakeCaller(
                {
                    "finance.clarification.list": {"clarifications": [_open()]},
                    "finance.clarification.resolve": {"resolved": True},
                }
            )
            result = await try_handle_quoted_finance_reply(
                FinanceReplyBinding(caller),
                message_text="Mercado",
                envelope=_envelope(chat_id=chat, is_group=is_group),
            )
            assert result.outcome is not None
            assert result.outcome.status is BindingStatus.RESOLVED
            ch = caller.channels[0]
            assert isinstance(ch, TrustedChannel)
            assert ch.is_group is is_group


# ─── gateway-shaped async path ──────────────────────────────────────────────


class TestGatewayRealisticAsyncPath:
    async def test_gateway_shaped_session_source_path(self):
        class SessionSource:
            chat_type = "group"
            chat_id = FINANCE_GROUP
            user_id = OWNER_PRINCIPAL
            message_id = REPLY_ID

        env = envelope_from_session_source(
            SessionSource(),
            incoming_message_id=REPLY_ID,
            reply_to_message_id=DELIVERY_ID,
        )
        assert env.is_group is True
        assert trusted_channel_from_envelope(env) is not None

        caller = FakeCaller(
            {
                "finance.clarification.list": {"clarifications": [_open()]},
                "finance.clarification.resolve": {"resolved": True},
            }
        )
        binding = FinanceReplyBinding(caller)
        install_router_hook(binding)

        result = await try_handle_quoted_finance_reply(
            binding,
            message_text="Mercado",
            envelope=env,
        )
        assert result.route == "FINANCE"
        assert result.skip_llm is True
        assert result.durable_lookup_called is True
        assert result.bind_reply_called is True
        assert "finance.clarification.resolve" in caller.caps()
        assert result.success_text_emitted is True


# ─── router regression ─────────────────────────────────────────────────────


class TestRouterRegression:
    def test_pending_and_normal_routing_unchanged(self):
        assert (
            resolve_specialist_route("Quantas pendências financeiras tenho?")
            == "FINANCE"
        )
        assert resolve_specialist_route("Traga as pendências de agosto.") == "FINANCE"
        assert (
            resolve_specialist_route("Tenho pendências no projeto")
            == "WORK_MANAGEMENT"
        )
        route, tools = resolve_turn_toolsets("Oi, tudo bem?")
        assert route == "NORMAL"
        assert tools == []

    def test_canonical_actor_source_is_finance_actor_directory(self, monkeypatch):
        monkeypatch.setenv(
            "FINANCE_ACTOR_BINDINGS", f"{OWNER_PRINCIPAL}={OWNER_ACTOR}"
        )
        assert resolve_canonical_finance_actor(OWNER_PRINCIPAL) == OWNER_ACTOR
        assert resolve_canonical_finance_actor(STRANGER) is None
        assert resolve_canonical_finance_actor("") is None
