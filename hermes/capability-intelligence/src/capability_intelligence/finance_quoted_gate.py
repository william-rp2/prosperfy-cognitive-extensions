"""
finance_quoted_gate.py — gate assíncrono pré-LLM para quoted finance reply.

INBOUND MESSAGE
→ ContextEnvelope trusted
→ SE reply_to_message_id: await durable lookup
→ se delivery binding Finance: bind_reply determinístico (persist first)
→ resposta pt-BR; LLM NÃO é chamado para resolução exata

Não transforma capability_router em async. NORMAL/CRON/INFRA seguem síncronos.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from cognitive.finance.clarification_binding import BindingOutcome, BindingStatus

from .canonical_finance_actor import resolve_canonical_finance_actor
from .context_envelope import ContextEnvelope
from .finance_reply_binding import FinanceReplyBinding
from .turn_context import trusted_channel_from_envelope

logger = logging.getLogger(__name__)

SAFE_ERROR_MESSAGE = (
    "Não consegui registrar essa resposta financeira agora. "
    "Tente de novo em instantes."
)
IDENTITY_ERROR_MESSAGE = (
    "Não consegui confirmar sua identidade financeira para registrar essa resposta."
)

_SUCCESS_STATUSES = frozenset(
    {BindingStatus.RESOLVED, BindingStatus.ALREADY_RESOLVED}
)


@dataclass(frozen=True)
class QuotedReplyGateResult:
    """Resultado do gate. skip_llm=True ⇒ gateway deve responder e não chamar LLM."""

    handled: bool
    quoted_finance: bool = False
    route: str = ""
    user_message: str | None = None
    skip_llm: bool = False
    outcome: BindingOutcome | None = None
    durable_lookup_called: bool = False
    bind_reply_called: bool = False
    resolve_attempted: bool = False
    success_text_emitted: bool = False


async def try_handle_quoted_finance_reply(
    binding: FinanceReplyBinding,
    *,
    message_text: str,
    envelope: ContextEnvelope | Any,
    canonical_actor_id: str | None = None,
) -> QuotedReplyGateResult:
    """Processa quoted finance reply de forma determinística e awaitable.

    Channel vem SOMENTE do envelope trusted. Actor canônico via
    FinanceActorDirectory / parâmetro já resolvido — nunca transport principal.
    """
    reply_to = str(getattr(envelope, "reply_to_message_id", "") or "").strip()
    if not reply_to:
        return QuotedReplyGateResult(handled=False)

    channel = trusted_channel_from_envelope(envelope)
    try:
        is_finance = await binding.is_quoted_finance_question(
            reply_to, channel=channel
        )
    except Exception as exc:  # noqa: BLE001 — fail-closed; ACL DENY no list
        logger.info(
            "quoted finance durable lookup denied/failed (%s) — not claiming finance quote",
            type(exc).__name__,
        )
        return QuotedReplyGateResult(
            handled=False,
            durable_lookup_called=True,
            success_text_emitted=False,
        )

    if not is_finance:
        return QuotedReplyGateResult(
            handled=False,
            durable_lookup_called=True,
        )

    transport_principal = str(getattr(envelope, "user_id", "") or "").strip()
    actor_id = (canonical_actor_id or "").strip() or (
        resolve_canonical_finance_actor(transport_principal) or ""
    )
    if not actor_id:
        return QuotedReplyGateResult(
            handled=True,
            quoted_finance=True,
            route="FINANCE",
            user_message=IDENTITY_ERROR_MESSAGE,
            skip_llm=True,
            durable_lookup_called=True,
            success_text_emitted=False,
        )

    # Nunca passar transport principal como actor.
    if actor_id == transport_principal:
        return QuotedReplyGateResult(
            handled=True,
            quoted_finance=True,
            route="FINANCE",
            user_message=IDENTITY_ERROR_MESSAGE,
            skip_llm=True,
            durable_lookup_called=True,
            success_text_emitted=False,
        )

    try:
        outcome = await binding.bind_reply(
            envelope,
            actor_id=actor_id,
            text=message_text if message_text is not None else "",
            channel=channel,
        )
    except Exception as exc:  # noqa: BLE001 — ACL DENY / resolve fail
        logger.info(
            "quoted finance bind_reply failed (%s) — no success text",
            type(exc).__name__,
        )
        return QuotedReplyGateResult(
            handled=True,
            quoted_finance=True,
            route="FINANCE",
            user_message=SAFE_ERROR_MESSAGE,
            skip_llm=True,
            durable_lookup_called=True,
            bind_reply_called=True,
            resolve_attempted=True,
            success_text_emitted=False,
        )

    success = outcome.status in _SUCCESS_STATUSES
    # Persist-first: só emite texto de sucesso se o binder confirmou resolução
    # (RESOLVED / ALREADY_RESOLVED). AMBIGUOUS/NO_CANDIDATES usam message do binder
    # (não afirmam "atualizei").
    msg = (outcome.message or "").strip() or (
        SAFE_ERROR_MESSAGE if not success else "Anotado, obrigado. Atualizei o lançamento."
    )
    if success and not msg:
        msg = "Anotado, obrigado. Atualizei o lançamento."

    return QuotedReplyGateResult(
        handled=True,
        quoted_finance=True,
        route="FINANCE",
        user_message=msg,
        skip_llm=True,
        outcome=outcome,
        durable_lookup_called=True,
        bind_reply_called=True,
        resolve_attempted=outcome.status
        in {BindingStatus.RESOLVED, BindingStatus.ALREADY_RESOLVED, BindingStatus.UNBOUND_QUOTE}
        or bool(outcome.clarification_id),
        success_text_emitted=success,
    )


__all__ = [
    "QuotedReplyGateResult",
    "SAFE_ERROR_MESSAGE",
    "IDENTITY_ERROR_MESSAGE",
    "try_handle_quoted_finance_reply",
]
