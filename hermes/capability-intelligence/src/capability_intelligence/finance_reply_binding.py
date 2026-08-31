"""
finance_reply_binding.py — quoted-reply binding do WhatsApp (F2B).

03_WHATSAPP_ACL_AND_CLARIFICATIONS.md §"Reply binding":

    outbound WhatsApp question
    -> persist delivery_message_id + clarification_id
    -> owner quotes/replies to message
    -> inbound reply references quoted message ID
    -> resolve exact clarification

Este módulo é o lado Hermes dessas quatro setas. Ele NÃO reimplementa a
decisão: a lógica determinística (caminho exato por quote, fallback solto com
confiança forte, resposta tardia sem mutação duplicada) vive em
`cognitive.finance.clarification_binding.ClarificationBinder`, que fala apenas
com um `CapabilityCaller`. Aqui o caller é o `FinanceService` que o Hermes já
usa (Hermes -> FinanceService -> CognitiveApiAdapter -> Cognitive -> policy/ACL
-> FinanceApiAdapter -> Finance API), então nenhum transporte novo é criado e
nenhum bypass de policy existe.

Invariantes:

* O vínculo é METADADO DE TRANSPORTE. O identificador citado vem de
  ContextEnvelope.reply_to_message_id — nunca do texto da mensagem, nunca de
  memória conversacional do LLM, nunca de nome de exibição.
* O vínculo é DURÁVEL. delivery_message_id -> clarification_id é persistido na
  Finance API por `finance.clarification.deliver` e relido por
  `finance.clarification.list?deliveryMessageId=...`. Funciona horas ou dias
  depois e sobrevive a restart do processo. O cache local é só atalho de
  roteamento — nunca fonte da verdade e nunca autorização.
* Rotear para FINANCE não autoriza NADA. A autorização é decidida depois, na
  ACL determinística do Cognitive (policy/finance_acl.py), sobre a identidade
  canônica do ator. Um terceiro que cite a mensagem cai em DENY lá.
* Nada aqui dispara mensagem: este módulo só registra entrega de perguntas já
  enviadas e resolve respostas recebidas.
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

logger = logging.getLogger(__name__)

CAP_DELIVER = "finance.clarification.deliver"
CAP_LIST = "finance.clarification.list"

# Teto do cache de roteamento. Pequeno de propósito: é um atalho, não um
# índice — a verdade está no banco da Finance API.
DEFAULT_CACHE_SIZE = 512


class CapabilityCaller(Protocol):
    """Mesmo contrato que FinanceService.call — executa uma capability finance.*."""

    async def call(self, capability_id: str, params: dict[str, Any]) -> dict[str, Any]: ...


class _BoundedFlagCache:
    """Cache LRU minúsculo de message_id -> 'é pergunta financeira?'.

    Guarda positivo e negativo. Ambos são estáveis por construção: um
    provider_message_id outbound ou já é a entrega de uma clarification no
    momento em que foi enviado, ou nunca será.
    """

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

    # ---- seta 1: persistir delivery_message_id + clarification_id --------

    async def register_delivery(
        self,
        clarification_id: str,
        delivery_message_id: str,
        delivery_chat_id: str = "",
        delivered_at: str = "",
    ) -> dict[str, Any]:
        """Chamado logo APÓS o envio da pergunta, com o provider_message_id devolvido
        pelo canal. Sem esta chamada o caminho por quote não existe."""
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

        data = await self._caller.call(CAP_DELIVER, params)
        # Atalho de roteamento para os turnos seguintes deste processo. Uma
        # falha do cache nunca quebra o binding: o lookup durável continua
        # existindo.
        self._cache.put(delivery_message_id, True)
        return data

    # ---- seta 3/4: o id citado é uma pergunta financeira? ----------------

    async def is_quoted_finance_question(self, message_id: str) -> bool:
        """Lookup durável (Finance API). Usado pelo router pré-LLM."""
        if not message_id:
            return False

        cached = self._cache.get(message_id)
        if cached is not None:
            return cached

        data = await self._caller.call(
            CAP_LIST,
            {"deliveryMessageId": message_id, "status": "any", "limit": 1},
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
    ) -> BindingOutcome:
        """Resolve a clarification correspondente à resposta do owner.

        envelope:  ContextEnvelope (só metadados de transporte são lidos:
                   reply_to_message_id / incoming_message_id).
        actor_id:  ACTOR CANÔNICO já resolvido pela identidade. Nunca
                   envelope.user_id cru — aquilo é principal de transporte, e
                   autorização/atribuição jamais dependem dele aqui.
        """
        if not actor_id:
            raise ValueError(
                "bind_reply exige o actor canônico — principal de transporte não serve"
            )

        reply = InboundReply(
            text=text if text is not None else "",
            reply_to_message_id=getattr(envelope, "reply_to_message_id", "") or "",
            incoming_message_id=getattr(envelope, "incoming_message_id", "") or "",
            actor_id=actor_id,
            competence_month=competence_month,
            account=account,
        )
        outcome = await self._binder.bind(reply)
        logger.info(
            "finance reply binding status=%s quoted=%s",
            outcome.status.value,
            bool(reply.reply_to_message_id),
        )
        return outcome

    # ---- wiring do router (pré-LLM, síncrono, sem I/O no router) ---------

    def route_checker(self) -> Callable[[str], bool]:
        """Predicado síncrono para `set_finance_quoted_reply_checker`.

        Fail-closed em direção a NORMAL: qualquer incerteza (erro de
        transporte, loop asyncio já rodando) devolve False e o turno volta a
        depender da heurística de texto. Nunca devolve True por suposição.
        """

        def check(message_id: str) -> bool:
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
                # Já existe loop neste thread: bloquear aqui travaria o
                # processo. Sem resposta durável, não afirma nada.
                logger.debug(
                    "route_checker sem lookup durável (event loop ativo) — caindo para heurística de texto"
                )
                return False

            try:
                return asyncio.run(self.is_quoted_finance_question(message_id))
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
