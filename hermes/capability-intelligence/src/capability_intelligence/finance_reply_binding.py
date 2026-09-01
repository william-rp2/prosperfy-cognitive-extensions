"""
finance_reply_binding.py — quoted-reply binding do WhatsApp (F2B).

03_WHATSAPP_ACL_AND_CLARIFICATIONS.md §"Reply binding":

    outbound WhatsApp question
    -> persist delivery_message_id + clarification_id
    -> owner quotes/replies to message
    -> inbound reply references quoted message ID
    -> resolve exact clarification

Este módulo é o lado Hermes dessas quatro setas. Ele NÃO reimplementa a
decisão: a lógica determinística vive em
`cognitive.finance.clarification_binding.ClarificationBinder`. Aqui o caller
é o `FinanceService` (Hermes -> CognitiveApiAdapter -> Cognitive ACL -> Finance).

Invariantes:

* O vínculo é METADADO DE TRANSPORTE (ContextEnvelope.reply_to_message_id).
* Capabilities finance.* usadas aqui propagam TrustedChannel do turno.
* Rotear para FINANCE não autoriza NADA — ACL Cognitive decide depois.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import Any, Callable, Protocol

from cognitive.finance.clarification_binding import (
    BindingOutcome,
    BindingStatus,
    ClarificationBinder,
    InboundReply,
)

from .capability_router import set_finance_quoted_reply_checker
from .models import TrustedChannel
from .turn_context import get_turn_envelope, trusted_channel_from_envelope

logger = logging.getLogger(__name__)

CAP_DELIVER = "finance.clarification.deliver"
CAP_LIST = "finance.clarification.list"

DEFAULT_CACHE_SIZE = 512


class CapabilityCaller(Protocol):
    """Mesmo contrato que FinanceService.call — executa uma capability finance.*."""

    async def call(
        self,
        capability_id: str,
        params: dict[str, Any],
        *,
        channel: TrustedChannel | None = None,
    ) -> dict[str, Any]: ...


class _BoundedFlagCache:
    def __init__(self, max_size: int = DEFAULT_CACHE_SIZE) -> None:
        self._max_size = max(1, max_size)
        self._items: OrderedDict[str, bool] = OrderedDict()

    def get(self, key: str) -> bool | None:
        if key not in self._items:
            return None
        self._items.move_to_end(key)
        return self._items[key]

    def put(self, key: str, value: bool) -> None:
        if not key:
            return
        self._items[key] = value
        self._items.move_to_end(key)
        while len(self._items) > self._max_size:
            self._items.popitem(last=False)


def _resolve_channel(
    channel: TrustedChannel | None = None,
    envelope: Any = None,
) -> TrustedChannel | None:
    if channel is not None:
        return channel
    if envelope is not None:
        return trusted_channel_from_envelope(envelope)
    return trusted_channel_from_envelope(get_turn_envelope())


class FinanceReplyBinding:
    """Registra entrega de perguntas e amarra a resposta citada na clarification certa."""

    def __init__(
        self,
        caller: CapabilityCaller,
        binder: ClarificationBinder | None = None,
        cache_size: int = DEFAULT_CACHE_SIZE,
    ) -> None:
        self._caller = caller
        self._binder = binder if binder is not None else ClarificationBinder(caller)
        self._cache = _BoundedFlagCache(cache_size)

    async def register_delivery(
        self,
        clarification_id: str,
        delivery_message_id: str,
        delivery_chat_id: str = "",
        delivered_at: str = "",
        *,
        channel: TrustedChannel | None = None,
    ) -> dict[str, Any]:
        if not clarification_id or not delivery_message_id:
            raise ValueError(
                "register_delivery exige clarification_id e delivery_message_id"
            )

        params: dict[str, Any] = {
            "clarificationId": clarification_id,
            "deliveryMessageId": delivery_message_id,
        }
        if delivery_chat_id:
            params["deliveryChatId"] = delivery_chat_id
        if delivered_at:
            params["deliveredAt"] = delivered_at

        data = await self._caller.call(
            CAP_DELIVER, params, channel=_resolve_channel(channel)
        )
        self._cache.put(delivery_message_id, True)
        return data

    async def is_quoted_finance_question(
        self,
        message_id: str,
        *,
        channel: TrustedChannel | None = None,
    ) -> bool:
        if not message_id:
            return False

        cached = self._cache.get(message_id)
        if cached is not None:
            return cached

        data = await self._caller.call(
            CAP_LIST,
            {"deliveryMessageId": message_id, "status": "any", "limit": 1},
            channel=_resolve_channel(channel),
        )
        found = bool(data.get("clarifications"))
        self._cache.put(message_id, found)
        return found

    async def bind_reply(
        self,
        envelope: Any,
        actor_id: str,
        text: str | None = None,
        competence_month: str = "",
        account: str = "",
        *,
        channel: TrustedChannel | None = None,
    ) -> BindingOutcome:
        if not actor_id:
            raise ValueError(
                "bind_reply exige o actor canônico — principal de transporte não serve"
            )

        # Propaga channel trusted do turno para lookups do binder via caller.
        # ClarificationBinder chama caller.call(cap, params) — FinanceService
        # aceita channel kw-only; o Protocol FakeCaller dos testes também.
        # Aqui amarramos o envelope no contextvar se ainda não estiver ligado.
        resolved = _resolve_channel(channel, envelope)

        reply = InboundReply(
            text=text if text is not None else "",
            reply_to_message_id=getattr(envelope, "reply_to_message_id", "") or "",
            incoming_message_id=getattr(envelope, "incoming_message_id", "") or "",
            actor_id=actor_id,
            competence_month=competence_month,
            account=account,
        )

        # Wrap caller so binder's internal calls carry channel without changing
        # ClarificationBinder's CapabilityCaller Protocol (positional-only).
        original = self._caller

        class _ChannelCaller:
            async def call(self, capability_id: str, params: dict[str, Any]) -> dict[str, Any]:
                return await original.call(capability_id, params, channel=resolved)

        previous_binder_caller = getattr(self._binder, "_caller", None)
        try:
            if hasattr(self._binder, "_caller"):
                self._binder._caller = _ChannelCaller()  # type: ignore[attr-defined]
            outcome = await self._binder.bind(reply)
        finally:
            if previous_binder_caller is not None:
                self._binder._caller = previous_binder_caller  # type: ignore[attr-defined]

        logger.info(
            "finance reply binding status=%s quoted=%s",
            outcome.status.value,
            bool(reply.reply_to_message_id),
        )
        return outcome

    def route_checker(self) -> Callable[..., bool]:
        """Predicado síncrono: (message_id, context_envelope=None) -> bool.

        Fail-closed em direção a NORMAL. Aceita envelope trusted opcional
        (segundo arg posicional ou kw) para propagar channel no lookup.
        """

        def check(message_id: str, context_envelope: Any = None) -> bool:
            if not message_id:
                return False

            cached = self._cache.get(message_id)
            if cached is not None:
                return cached

            try:
                asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                logger.debug(
                    "route_checker sem lookup durável (event loop ativo) — caindo para heurística de texto"
                )
                return False

            channel = _resolve_channel(None, context_envelope)
            try:
                return asyncio.run(
                    self.is_quoted_finance_question(message_id, channel=channel)
                )
            except Exception as exc:
                logger.warning(
                    "route_checker falhou (%s) — caindo para heurística de texto",
                    type(exc).__name__,
                )
                return False

        return check


def install_router_hook(binding: FinanceReplyBinding) -> None:
    """Liga o binding ao boundary de roteamento pré-LLM do Hermes."""
    set_finance_quoted_reply_checker(binding.route_checker())


def uninstall_router_hook() -> None:
    """Volta ao comportamento pré-F2B (só heurística de texto)."""
    set_finance_quoted_reply_checker(None)


__all__ = [
    "BindingOutcome",
    "BindingStatus",
    "CapabilityCaller",
    "FinanceReplyBinding",
    "install_router_hook",
    "uninstall_router_hook",
]
