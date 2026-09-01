"""
turn_context.py — contexto de transporte autenticado do turno atual.

O registry Hermes passa (args, **kw) com task_id/session_id, mas NÃO o
MessageEvent. O envelope trusted do turno é ligado aqui (ContextVar) pela
boundary de gateway no início do `_run_agent_inner` e lido pelas tools
finance / FinanceReplyBinding.

Não é identidade canônica. Não é LLM args. É metadado de transporte.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any, Optional

from .context_envelope import ContextEnvelope
from .models import TrustedChannel

_turn_envelope: ContextVar[Optional[ContextEnvelope]] = ContextVar(
    "hermes_finance_turn_envelope", default=None
)


def bind_turn_envelope(envelope: ContextEnvelope | None) -> Token:
    """Liga o envelope trusted do turno. Retorna token para reset."""
    return _turn_envelope.set(envelope)


def reset_turn_envelope(token: Token) -> None:
    _turn_envelope.reset(token)


def clear_turn_envelope() -> None:
    _turn_envelope.set(None)


def get_turn_envelope() -> ContextEnvelope | None:
    return _turn_envelope.get()


def is_group_from_chat_type(chat_type: str | None) -> bool:
    """Deriva is_group SOMENTE do discriminator estável do SessionSource."""
    return (chat_type or "").strip().lower() in {"group", "channel", "forum"}


def envelope_from_session_source(
    source: Any,
    *,
    incoming_message_id: str = "",
    reply_to_message_id: str = "",
) -> ContextEnvelope:
    """Monta ContextEnvelope a partir do SessionSource autenticado do gateway.

    Preferido: chat_type do transporte. Nunca texto/LLM/nome.
    """
    chat_type = str(getattr(source, "chat_type", "") or "")
    chat_id = str(getattr(source, "chat_id", "") or "")
    user_id = str(getattr(source, "user_id", "") or "")
    incoming = incoming_message_id or str(getattr(source, "message_id", "") or "")
    return ContextEnvelope(
        conversation_id=chat_id,
        channel_id=chat_id,
        incoming_message_id=incoming,
        reply_to_message_id=reply_to_message_id or "",
        user_id=user_id,
        is_group=is_group_from_chat_type(chat_type),
    )


def trusted_channel_from_envelope(envelope: ContextEnvelope | None) -> TrustedChannel | None:
    """ContextEnvelope autenticado → TrustedChannel para ExecutionRequest.

    transport_principal = envelope.user_id (principal REAL do transporte).
    NUNCA actor canônico — a ACL faz binding depois.
    """
    if envelope is None:
        return None
    chat_id = (envelope.channel_id or "").strip()
    principal = (envelope.user_id or "").strip()
    if not chat_id and not principal:
        return None
    return TrustedChannel(
        chat_id=chat_id,
        is_group=bool(getattr(envelope, "is_group", False)),
        transport_principal=principal,
        incoming_message_id=(envelope.incoming_message_id or "").strip(),
        reply_to_message_id=(envelope.reply_to_message_id or "").strip(),
    )


__all__ = [
    "bind_turn_envelope",
    "clear_turn_envelope",
    "envelope_from_session_source",
    "get_turn_envelope",
    "is_group_from_chat_type",
    "reset_turn_envelope",
    "trusted_channel_from_envelope",
]
