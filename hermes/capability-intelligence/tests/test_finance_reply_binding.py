"""
tests/test_finance_reply_binding.py — F2B, quoted-reply binding do WhatsApp.

03_WHATSAPP_ACL_AND_CLARIFICATIONS.md §"Reply binding" / §"Loose reply
fallback" / §"Late reply". Propriedades provadas aqui:

* a resposta CITADA amarra na clarification exata pelo provider_message_id —
  metadado de transporte, nunca texto, nunca memória do LLM;
* o roteamento pré-LLM reconhece o turno mesmo quando o texto não tem
  nenhuma palavra de finanças (e mesmo quando não tem texto algum);
* o vínculo é durável: o lookup vai à Finance API, não a estado de processo;
* fail-closed no roteamento: qualquer incerteza volta para NORMAL;
* resposta tardia não duplica mutação; ambiguidade não resolve nada.
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
    set_finance_quoted_reply_checker,
)
from capability_intelligence.context_envelope import ContextEnvelope  # noqa: E402
from capability_intelligence.finance_reply_binding import (  # noqa: E402
    BindingStatus,
    FinanceReplyBinding,
    install_router_hook,
    uninstall_router_hook,
)

DELIVERY_ID = "wamid.PERGUNTA-1"
REPLY_ID = "wamid.RESPOSTA-1"
CLARIFICATION_ID = "clar-42"
OWNER_ACTOR = "actor-owner"


class FakeCaller:
    """CapabilityCaller de teste. Registra toda chamada — os testes provam
    tanto o que É chamado quanto o que NÃO é."""

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
        return response

    def capabilities_called(self) -> list[str]:
        return [cap for cap, _ in self.calls]


def _open_clarification(**overrides: Any) -> dict[str, Any]:
    base = {
        "clarificationId": CLARIFICATION_ID,
        "transactionId": "tx-1",
        "questionType": "CATEGORY",
        "status": "open",
        "merchant": "Supermercado Dalben",
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _clean_router_hook():
    uninstall_router_hook()
    yield
    uninstall_router_hook()


# ─── roteamento pré-LLM ────────────────────────────────────────────────────


class TestQuotedReplyRouting:
    def test_quoted_reply_routes_to_finance_even_without_finance_words(self):
        """"foi mercado" não tem nenhuma keyword de finanças — só o quote salva."""
        set_finance_quoted_reply_checker(lambda mid: mid == DELIVERY_ID)
        assert resolve_specialist_route("foi mercado", reply_to_message_id=DELIVERY_ID) == "FINANCE"

    def test_quoted_reply_routes_to_finance_even_with_empty_text(self):
        """Resposta citada pode ser só um emoji/sticker."""
        set_finance_quoted_reply_checker(lambda mid: mid == DELIVERY_ID)
        assert resolve_specialist_route("", reply_to_message_id=DELIVERY_ID) == "FINANCE"

    def test_quote_of_an_unrelated_message_does_not_route_to_finance(self):
        set_finance_quoted_reply_checker(lambda mid: mid == DELIVERY_ID)
        assert resolve_specialist_route("foi mercado", reply_to_message_id="wamid.OUTRA") == "NORMAL"

    def test_without_checker_behaviour_is_pre_f2b(self):
        assert resolve_specialist_route("foi mercado", reply_to_message_id=DELIVERY_ID) == "NORMAL"

    def test_text_heuristics_still_work_without_a_quote(self):
        set_finance_quoted_reply_checker(lambda mid: True)
        assert resolve_specialist_route("quanto gastei esse mês?") == "FINANCE"

    def test_toolsets_follow_the_quoted_route(self):
        set_finance_quoted_reply_checker(lambda mid: mid == DELIVERY_ID)
        route, toolsets = resolve_turn_toolsets("foi mercado", reply_to_message_id=DELIVERY_ID)
        assert route == "FINANCE"
        assert toolsets == ["finance"]


# ─── seta 1: persistir delivery_message_id + clarification_id ─────────────


class TestRegisterDelivery:
    async def test_register_delivery_persists_the_binding(self):
        caller = FakeCaller({"finance.clarification.deliver": {"clarificationId": CLARIFICATION_ID}})
        binding = FinanceReplyBinding(caller)

        await binding.register_delivery(CLARIFICATION_ID, DELIVERY_ID, delivery_chat_id="grp@g.us")

        assert caller.calls == [
            (
                "finance.clarification.deliver",
                {
                    "clarificationId": CLARIFICATION_ID,
                    "deliveryMessageId": DELIVERY_ID,
                    "deliveryChatId": "grp@g.us",
                },
            )
        ]

    async def test_register_delivery_requires_both_ids(self):
        binding = FinanceReplyBinding(FakeCaller())
        with pytest.raises(ValueError):
            await binding.register_delivery("", DELIVERY_ID)
        with pytest.raises(ValueError):
            await binding.register_delivery(CLARIFICATION_ID, "")

    async def test_registered_delivery_is_recognised_by_the_router_without_a_new_lookup(self):
        caller = FakeCaller({"finance.clarification.deliver": {}})
        binding = FinanceReplyBinding(caller)
        await binding.register_delivery(CLARIFICATION_ID, DELIVERY_ID)

        assert await binding.is_quoted_finance_question(DELIVERY_ID) is True
        assert caller.capabilities_called() == ["finance.clarification.deliver"]


class TestDurableLookup:
    async def test_lookup_goes_to_the_finance_api_not_to_process_state(self):
        """Processo novo (cache frio), pergunta entregue dias atrás: ainda liga."""
        caller = FakeCaller(
            {"finance.clarification.list": {"clarifications": [_open_clarification()]}}
        )
        binding = FinanceReplyBinding(caller)

        assert await binding.is_quoted_finance_question(DELIVERY_ID) is True
        assert caller.calls[0] == (
            "finance.clarification.list",
            {"deliveryMessageId": DELIVERY_ID, "status": "any", "limit": 1},
        )

    async def test_unknown_message_id_is_not_a_finance_question(self):
        caller = FakeCaller({"finance.clarification.list": {"clarifications": []}})
        assert await FinanceReplyBinding(caller).is_quoted_finance_question("wamid.X") is False

    async def test_empty_message_id_never_queries(self):
        caller = FakeCaller()
        assert await FinanceReplyBinding(caller).is_quoted_finance_question("") is False
        assert caller.calls == []

    async def test_positive_lookup_result_is_cached(self):
        caller = FakeCaller(
            {"finance.clarification.list": {"clarifications": [_open_clarification()]}}
        )
        binding = FinanceReplyBinding(caller)
        await binding.is_quoted_finance_question(DELIVERY_ID)
        await binding.is_quoted_finance_question(DELIVERY_ID)
        assert len(caller.calls) == 1

    async def test_miss_is_not_cached_recovers_without_restart(self):
        """Live bug: MISS transitório (API quebrada) NÃO pode envenenar até restart."""
        store: dict[str, Any] = {"clarifications": []}

        def list_resp(_params: dict[str, Any]) -> dict[str, Any]:
            return {"clarifications": list(store["clarifications"])}

        caller = FakeCaller({"finance.clarification.list": list_resp})
        binding = FinanceReplyBinding(caller)

        assert await binding.is_quoted_finance_question(DELIVERY_ID) is False
        assert len(caller.calls) == 1

        # Backend corrigido / binding passou a existir — MESMA instância Hermes.
        store["clarifications"] = [_open_clarification()]
        assert await binding.is_quoted_finance_question(DELIVERY_ID) is True
        assert len(caller.calls) == 2
        assert binding._cache.get(DELIVERY_ID) is True

    async def test_unknown_quote_requeries_each_time_remains_normal(self):
        caller = FakeCaller({"finance.clarification.list": {"clarifications": []}})
        binding = FinanceReplyBinding(caller)
        assert await binding.is_quoted_finance_question("wamid.NEVER-FINANCE") is False
        assert await binding.is_quoted_finance_question("wamid.NEVER-FINANCE") is False
        assert len(caller.calls) == 2
        assert binding._cache.get("wamid.NEVER-FINANCE") is None

    async def test_transient_list_error_does_not_poison_cache(self):
        attempts = {"n": 0}

        def list_resp(_params: dict[str, Any]) -> dict[str, Any]:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("Finance API transient")
            return {"clarifications": [_open_clarification()]}

        caller = FakeCaller({"finance.clarification.list": list_resp})
        binding = FinanceReplyBinding(caller)

        with pytest.raises(RuntimeError):
            await binding.is_quoted_finance_question(DELIVERY_ID)
        assert binding._cache.get(DELIVERY_ID) is None

        assert await binding.is_quoted_finance_question(DELIVERY_ID) is True
        assert len(caller.calls) == 2


class TestRouteCheckerFailsClosed:
    def test_transport_failure_falls_back_to_text_heuristics(self):
        class Exploding:
            async def call(self, capability_id, params):
                raise RuntimeError("Finance API inacessível")

        binding = FinanceReplyBinding(Exploding())
        install_router_hook(binding)
        assert resolve_specialist_route("foi mercado", reply_to_message_id=DELIVERY_ID) == "NORMAL"

    async def test_checker_does_not_block_a_running_event_loop(self):
        """Cache miss + loop ativo: checker síncrono NÃO faz I/O (gate async faz)."""
        caller = FakeCaller(
            {"finance.clarification.list": {"clarifications": [_open_clarification()]}}
        )
        binding = FinanceReplyBinding(caller)
        assert binding.route_checker()(DELIVERY_ID) is False
        assert caller.calls == []

    async def test_warm_cache_answers_even_with_a_running_loop(self):
        caller = FakeCaller({"finance.clarification.deliver": {}})
        binding = FinanceReplyBinding(caller)
        await binding.register_delivery(CLARIFICATION_ID, DELIVERY_ID)
        assert binding.route_checker()(DELIVERY_ID) is True

    def test_empty_message_id_is_never_finance(self):
        binding = FinanceReplyBinding(FakeCaller())
        assert binding.route_checker()("") is False


# ─── setas 3/4: resolver a clarification exata ────────────────────────────


def _envelope(reply_to: str = DELIVERY_ID) -> ContextEnvelope:
    return ContextEnvelope(
        conversation_id="conv-1",
        channel_id="whatsapp",
        incoming_message_id=REPLY_ID,
        reply_to_message_id=reply_to,
        user_id="5519999999999@s.whatsapp.net",
    )


class TestBindReply:
    async def test_quoted_reply_resolves_the_exact_clarification(self):
        caller = FakeCaller(
            {
                "finance.clarification.list": {"clarifications": [_open_clarification()]},
                "finance.clarification.resolve": {"clarification": {"id": CLARIFICATION_ID}},
            }
        )
        outcome = await FinanceReplyBinding(caller).bind_reply(
            _envelope(), actor_id=OWNER_ACTOR, text="foi mercado"
        )

        assert outcome.status is BindingStatus.RESOLVED
        assert outcome.clarification_id == CLARIFICATION_ID

        lookup = caller.calls[0][1]
        assert lookup["deliveryMessageId"] == DELIVERY_ID

        resolve_cap, resolve_params = caller.calls[1]
        assert resolve_cap == "finance.clarification.resolve"
        assert resolve_params["clarificationId"] == CLARIFICATION_ID
        # Auditoria do que foi citado/respondido — as duas pontas do vínculo.
        assert resolve_params["replyMessageId"] == REPLY_ID
        assert resolve_params["resolvedByActorId"] == OWNER_ACTOR

    async def test_late_reply_to_a_resolved_question_does_not_mutate_again(self):
        caller = FakeCaller(
            {
                "finance.clarification.list": {
                    "clarifications": [_open_clarification(status="resolved", resolvedAt="2026-08-01T10:00:00Z")]
                }
            }
        )
        outcome = await FinanceReplyBinding(caller).bind_reply(
            _envelope(), actor_id=OWNER_ACTOR, text="foi mercado"
        )

        assert outcome.status is BindingStatus.ALREADY_RESOLVED
        assert "finance.clarification.resolve" not in caller.capabilities_called()

    async def test_reply_without_quote_and_many_candidates_asks_instead_of_guessing(self):
        caller = FakeCaller(
            {
                "finance.clarification.list": {
                    "clarifications": [
                        _open_clarification(clarificationId="clar-1", transactionId="tx-1", merchant="Posto Shell"),
                        _open_clarification(clarificationId="clar-2", transactionId="tx-2", merchant="Farmácia São Paulo"),
                    ]
                }
            }
        )
        outcome = await FinanceReplyBinding(caller).bind_reply(
            _envelope(reply_to=""), actor_id=OWNER_ACTOR, text="pode deixar"
        )

        assert outcome.status is BindingStatus.AMBIGUOUS
        assert "finance.clarification.resolve" not in caller.capabilities_called()
        assert len(outcome.candidates) == 2

    async def test_reply_without_quote_and_no_pending_question_resolves_nothing(self):
        caller = FakeCaller({"finance.clarification.list": {"clarifications": []}})
        outcome = await FinanceReplyBinding(caller).bind_reply(
            _envelope(reply_to=""), actor_id=OWNER_ACTOR, text="foi mercado"
        )
        assert outcome.status is BindingStatus.NO_CANDIDATES
        assert "finance.clarification.resolve" not in caller.capabilities_called()

    async def test_quote_of_an_unknown_message_falls_back_and_never_guesses(self):
        """Quote sem clarification correspondente cai no fallback solto — que
        com duas pendências PERGUNTA em vez de escolher uma transação."""
        responses = {
            "finance.clarification.list": lambda params: (
                {"clarifications": []}
                if params.get("deliveryMessageId")
                else {
                    "clarifications": [
                        _open_clarification(clarificationId="clar-1", transactionId="tx-1", merchant="Posto Shell"),
                        _open_clarification(clarificationId="clar-2", transactionId="tx-2", merchant="Padaria Central"),
                    ]
                }
            )
        }
        caller = FakeCaller(responses)
        outcome = await FinanceReplyBinding(caller).bind_reply(
            _envelope(), actor_id=OWNER_ACTOR, text="ok"
        )
        assert outcome.status is BindingStatus.AMBIGUOUS
        assert "finance.clarification.resolve" not in caller.capabilities_called()

    async def test_canonical_actor_is_mandatory(self):
        """O principal de transporte (envelope.user_id) não serve como ator."""
        binding = FinanceReplyBinding(FakeCaller())
        with pytest.raises(ValueError):
            await binding.bind_reply(_envelope(), actor_id="", text="foi mercado")

    async def test_binding_reads_only_transport_metadata_from_the_envelope(self):
        caller = FakeCaller(
            {
                "finance.clarification.list": {"clarifications": [_open_clarification()]},
                "finance.clarification.resolve": {},
            }
        )
        await FinanceReplyBinding(caller).bind_reply(
            _envelope(), actor_id=OWNER_ACTOR, text="foi mercado"
        )
        resolve_params = caller.calls[1][1]
        # user_id (principal de transporte) jamais vira atribuição de autoria.
        assert "5519999999999@s.whatsapp.net" not in resolve_params.values()


# ─── Cognitive result envelope {success, data} (human forensic 22:49) ──────


def _cognitive_envelope(business: dict[str, Any]) -> dict[str, Any]:
    return {"success": True, "data": business}


class TestCognitiveResultEnvelope:
    async def test_real_cognitive_envelope_lookup_hit(self):
        caller = FakeCaller(
            {
                "finance.clarification.list": _cognitive_envelope(
                    {
                        "clarifications": [_open_clarification()],
                        "total": 1,
                    }
                )
            }
        )
        binding = FinanceReplyBinding(caller)
        assert await binding.is_quoted_finance_question(DELIVERY_ID) is True
        assert binding._cache.get(DELIVERY_ID) is True

    async def test_real_cognitive_empty_envelope_miss_no_negative_cache(self):
        caller = FakeCaller(
            {
                "finance.clarification.list": _cognitive_envelope(
                    {"clarifications": [], "total": 0}
                )
            }
        )
        binding = FinanceReplyBinding(caller)
        assert await binding.is_quoted_finance_question(DELIVERY_ID) is False
        assert binding._cache.get(DELIVERY_ID) is None

    async def test_direct_payload_backcompat(self):
        caller = FakeCaller(
            {"finance.clarification.list": {"clarifications": [_open_clarification()]}}
        )
        assert await FinanceReplyBinding(caller).is_quoted_finance_question(DELIVERY_ID) is True

    async def test_failed_delivery_not_cached(self):
        caller = FakeCaller(
            {"finance.clarification.deliver": {"success": False, "error": {"code": "x"}}}
        )
        binding = FinanceReplyBinding(caller)
        with pytest.raises(RuntimeError, match="unsuccessful result") as excinfo:
            await binding.register_delivery(CLARIFICATION_ID, DELIVERY_ID)
        assert "code" not in str(excinfo.value)
        assert binding._cache.get(DELIVERY_ID) is None

    async def test_unsuccessful_list_fail_closed(self):
        caller = FakeCaller(
            {"finance.clarification.list": {"success": False, "error": {"msg": "secret"}}}
        )
        binding = FinanceReplyBinding(caller)
        with pytest.raises(RuntimeError) as excinfo:
            await binding.is_quoted_finance_question(DELIVERY_ID)
        assert "secret" not in str(excinfo.value)
        assert binding._cache.get(DELIVERY_ID) is None

    async def test_unsuccessful_resolve_not_reported_as_success(self):
        caller = FakeCaller(
            {
                "finance.clarification.list": _cognitive_envelope(
                    {"clarifications": [_open_clarification()], "total": 1}
                ),
                "finance.clarification.resolve": {
                    "success": False,
                    "error": {"denied": True},
                },
            }
        )
        with pytest.raises(RuntimeError, match="unsuccessful result"):
            await FinanceReplyBinding(caller).bind_reply(
                _envelope(), actor_id=OWNER_ACTOR, text="Mercado"
            )

    async def test_real_envelope_bind_reply_and_resolve(self):
        caller = FakeCaller(
            {
                "finance.clarification.list": _cognitive_envelope(
                    {
                        "clarifications": [_open_clarification()],
                        "total": 1,
                    }
                ),
                "finance.clarification.resolve": _cognitive_envelope(
                    {"clarification": {"id": CLARIFICATION_ID}}
                ),
            }
        )
        outcome = await FinanceReplyBinding(caller).bind_reply(
            _envelope(), actor_id=OWNER_ACTOR, text="Mercado"
        )
        assert outcome.status is BindingStatus.RESOLVED
        assert outcome.clarification_id == CLARIFICATION_ID
        assert "Atualizei" in outcome.message
        assert caller.calls[0] == (
            "finance.clarification.list",
            {"deliveryMessageId": DELIVERY_ID, "status": "any", "limit": 2},
        )
        resolve_cap, resolve_params = caller.calls[1]
        assert resolve_cap == "finance.clarification.resolve"
        assert resolve_params["clarificationId"] == CLARIFICATION_ID
        assert resolve_params["freeText"] == "Mercado"
        assert resolve_params["replyMessageId"] == REPLY_ID
        assert resolve_params["resolvedByActorId"] == OWNER_ACTOR

    async def test_real_envelope_late_reply_idempotent(self):
        caller = FakeCaller(
            {
                "finance.clarification.list": _cognitive_envelope(
                    {
                        "clarifications": [
                            _open_clarification(
                                status="resolved", resolvedAt="2026-09-01T10:00:00Z"
                            )
                        ],
                        "total": 1,
                    }
                )
            }
        )
        outcome = await FinanceReplyBinding(caller).bind_reply(
            _envelope(), actor_id=OWNER_ACTOR, text="Mercado"
        )
        assert outcome.status is BindingStatus.ALREADY_RESOLVED
        assert "finance.clarification.resolve" not in caller.capabilities_called()
