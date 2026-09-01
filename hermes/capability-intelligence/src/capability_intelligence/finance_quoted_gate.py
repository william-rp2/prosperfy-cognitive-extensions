"""
finance_quoted_gate.py — gate assíncrono pré-LLM para quoted finance reply.

INBOUND MESSAGE
→ ContextEnvelope trusted
→ SE reply_to_message_id: await durable lookup
→ se delivery binding Finance: bind_reply determinístico (persist first)
→ resposta pt-BR; LLM NÃO é chamado para resolução exata

Não transforma capability_router em async. NORMAL/CRON/INFRA seguem síncronos.

Observabilidade: um QUOTED_GATE_OUTCOME por inbound quoted + etapas F2B_*
com fingerprints (sem JID/actor/delivery crus).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from cognitive.finance.clarification_binding import BindingOutcome, BindingStatus

from .canonical_finance_actor import resolve_canonical_finance_actor
from .context_envelope import ContextEnvelope
from .finance_quoted_boot import f2b_fingerprint
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

# Exactly one outcome string per quoted inbound (gateway / Host Executor).
OUTCOME_NO_REPLY_ID = "NO_REPLY_ID"
OUTCOME_NON_FINANCE = "NON_FINANCE"
OUTCOME_FINANCE_RESOLVED = "FINANCE_RESOLVED"
OUTCOME_FINANCE_ALREADY_RESOLVED = "FINANCE_ALREADY_RESOLVED"
OUTCOME_FINANCE_DENIED = "FINANCE_DENIED"
OUTCOME_FINANCE_ERROR = "FINANCE_ERROR"
OUTCOME_BINDING_NOT_READY = "BINDING_NOT_READY"

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
    gate_outcome: str = ""
    fallthrough_reason: str = ""


def _corr(envelope: Any, reply_to: str) -> str:
    incoming = str(getattr(envelope, "incoming_message_id", "") or "")
    return f2b_fingerprint(incoming or reply_to)


def _log(event: str, corr: str, **fields: Any) -> None:
    extras = " ".join(f"{k}={v}" for k, v in fields.items())
    if extras:
        logger.info("%s corr=%s %s", event, corr, extras)
    else:
        logger.info("%s corr=%s", event, corr)


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
    corr = _corr(envelope, reply_to)
    _log("F2B_QUOTE_GATE_START", corr)
    _log("F2B_REPLY_TO_PRESENT", corr, present="YES" if reply_to else "NO")
    _log("F2B_ACTIVE_BINDING_PRESENT", corr, present="YES")

    if not reply_to:
        _log("QUOTED_GATE_OUTCOME", corr, outcome=OUTCOME_NO_REPLY_ID)
        return QuotedReplyGateResult(
            handled=False,
            gate_outcome=OUTCOME_NO_REPLY_ID,
            fallthrough_reason="NO_REPLY_ID",
        )

    channel = trusted_channel_from_envelope(envelope)
    _log("F2B_LOOKUP_START", corr, reply_fp=f2b_fingerprint(reply_to))
    try:
        is_finance = await binding.is_quoted_finance_question(
            reply_to, channel=channel
        )
    except Exception as exc:  # noqa: BLE001 — fail-closed; ACL DENY no list
        _log(
            "F2B_GATE_EXCEPTION",
            corr,
            type=type(exc).__name__,
            stage="durable_lookup",
        )
        _log("QUOTED_GATE_OUTCOME", corr, outcome=OUTCOME_FINANCE_DENIED)
        return QuotedReplyGateResult(
            handled=False,
            durable_lookup_called=True,
            success_text_emitted=False,
            gate_outcome=OUTCOME_FINANCE_DENIED,
            fallthrough_reason="LOOKUP_EXCEPTION",
        )

    _log("F2B_LOOKUP_RESULT", corr, hit="YES" if is_finance else "NO")
    if not is_finance:
        _log("QUOTED_GATE_OUTCOME", corr, outcome=OUTCOME_NON_FINANCE)
        _log(
            "F2B_FALLTHROUGH_REASON",
            corr,
            reason="NON_FINANCE",
        )
        return QuotedReplyGateResult(
            handled=False,
            durable_lookup_called=True,
            gate_outcome=OUTCOME_NON_FINANCE,
            fallthrough_reason="NON_FINANCE",
        )

    transport_principal = str(getattr(envelope, "user_id", "") or "").strip()
    actor_id = (canonical_actor_id or "").strip() or (
        resolve_canonical_finance_actor(transport_principal) or ""
    )
    actor_ok = bool(actor_id) and actor_id != transport_principal
    _log(
        "F2B_CANONICAL_ACTOR_RESULT",
        corr,
        resolved="YES" if actor_ok else "NO",
        actor_fp=f2b_fingerprint(actor_id) if actor_ok else "none",
    )
    if not actor_ok:
        _log("QUOTED_GATE_OUTCOME", corr, outcome=OUTCOME_FINANCE_DENIED)
        return QuotedReplyGateResult(
            handled=True,
            quoted_finance=True,
            route="FINANCE",
            user_message=IDENTITY_ERROR_MESSAGE,
            skip_llm=True,
            durable_lookup_called=True,
            success_text_emitted=False,
            gate_outcome=OUTCOME_FINANCE_DENIED,
            fallthrough_reason="CANONICAL_ACTOR_MISSING",
        )

    _log("F2B_BIND_START", corr)
    try:
        outcome = await binding.bind_reply(
            envelope,
            actor_id=actor_id,
            text=message_text if message_text is not None else "",
            channel=channel,
        )
    except Exception as exc:  # noqa: BLE001 — ACL DENY / resolve fail
        _log(
            "F2B_GATE_EXCEPTION",
            corr,
            type=type(exc).__name__,
            stage="bind_reply",
        )
        _log("QUOTED_GATE_OUTCOME", corr, outcome=OUTCOME_FINANCE_ERROR)
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
            gate_outcome=OUTCOME_FINANCE_ERROR,
            fallthrough_reason="BIND_EXCEPTION",
        )

    success = outcome.status in _SUCCESS_STATUSES
    if outcome.status is BindingStatus.RESOLVED:
        gate_outcome = OUTCOME_FINANCE_RESOLVED
    elif outcome.status is BindingStatus.ALREADY_RESOLVED:
        gate_outcome = OUTCOME_FINANCE_ALREADY_RESOLVED
    else:
        gate_outcome = OUTCOME_FINANCE_ERROR

    resolve_attempted = outcome.status in {
        BindingStatus.RESOLVED,
        BindingStatus.ALREADY_RESOLVED,
        BindingStatus.UNBOUND_QUOTE,
    } or bool(outcome.clarification_id)

    _log(
        "F2B_BIND_OUTCOME",
        corr,
        status=outcome.status.value,
        clar_fp=f2b_fingerprint(outcome.clarification_id or ""),
    )
    _log(
        "F2B_RESOLVE_ATTEMPTED",
        corr,
        attempted="YES" if resolve_attempted else "NO",
    )

    msg = (outcome.message or "").strip() or (
        SAFE_ERROR_MESSAGE if not success else "Anotado, obrigado. Atualizei o lançamento."
    )
    if success and not msg:
        msg = "Anotado, obrigado. Atualizei o lançamento."

    _log("F2B_SKIP_LLM", corr, skip="YES")
    _log("QUOTED_GATE_OUTCOME", corr, outcome=gate_outcome)

    return QuotedReplyGateResult(
        handled=True,
        quoted_finance=True,
        route="FINANCE",
        user_message=msg,
        skip_llm=True,
        outcome=outcome,
        durable_lookup_called=True,
        bind_reply_called=True,
        resolve_attempted=resolve_attempted,
        success_text_emitted=success,
        gate_outcome=gate_outcome,
    )


__all__ = [
    "QuotedReplyGateResult",
    "SAFE_ERROR_MESSAGE",
    "IDENTITY_ERROR_MESSAGE",
    "OUTCOME_NO_REPLY_ID",
    "OUTCOME_NON_FINANCE",
    "OUTCOME_FINANCE_RESOLVED",
    "OUTCOME_FINANCE_ALREADY_RESOLVED",
    "OUTCOME_FINANCE_DENIED",
    "OUTCOME_FINANCE_ERROR",
    "OUTCOME_BINDING_NOT_READY",
    "try_handle_quoted_finance_reply",
]
