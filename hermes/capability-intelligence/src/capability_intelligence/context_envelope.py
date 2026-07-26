"""
context_envelope.py — ContextEnvelope imutável para isolamento de contexto.

Criado para cada mensagem recebida, garantindo que o contexto de uma conversa
não contamine outra e que tools de domínio irrelevante sejam bloqueadas.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class IntentDomain(Enum):
    """Domínios de intenção para classificação de mensagens."""
    CONTACT_INFO = "contact_info"
    FOLLOW_UP = "follow_up"
    INFRASTRUCTURE = "infrastructure"
    DEVELOPMENT = "development"
    MARKETING = "marketing"
    GENERAL = "general"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ContextEnvelope:
    """Envelope imutável de contexto para cada mensagem recebida.

    Criado no momento da recepção da mensagem e NUNCA alterado.
    Todo processamento subsequente deve referenciar este envelope.
    """

    conversation_id: str = ""
    channel_id: str = ""
    incoming_message_id: str = ""
    reply_to_message_id: str = ""
    user_id: str = ""
    tenant_id: str = ""
    session_id: str = ""
    turn_id: str = ""
    correlation_id: str = ""
    execution_id: str = ""
    active_intent: str = ""
    active_entities: list[str] = field(default_factory=list)
    referenced_follow_up_ids: list[str] = field(default_factory=list)
    referenced_job_ids: list[str] = field(default_factory=list)
    allowed_context_sources: list[str] = field(default_factory=lambda: ["current_conversation"])
    allowed_tool_domains: list[str] = field(default_factory=list)
    blocked_tool_domains: list[str] = field(default_factory=list)
    intent_domain: str = "general"
    created_at: str = ""

    def __post_init__(self):
        # Usar object.__setattr__ porque o dataclass é frozen
        if not self.correlation_id:
            object.__setattr__(self, "correlation_id", uuid.uuid4().hex[:16])
        if not self.turn_id:
            object.__setattr__(self, "turn_id", uuid.uuid4().hex[:12])
        if not self.created_at:
            object.__setattr__(self, "created_at", datetime.now(timezone.utc).isoformat())


class ContextEnvelopeBuilder:
    """Construtor fluente para ContextEnvelope."""

    def __init__(self):
        self._data = {}

    def with_conversation(self, conv_id: str) -> "ContextEnvelopeBuilder":
        self._data["conversation_id"] = conv_id
        return self

    def with_message(self, msg_id: str, reply_to: str = "") -> "ContextEnvelopeBuilder":
        self._data["incoming_message_id"] = msg_id
        self._data["reply_to_message_id"] = reply_to
        return self

    def with_user(self, user_id: str) -> "ContextEnvelopeBuilder":
        self._data["user_id"] = user_id
        return self

    def with_session(self, session_id: str) -> "ContextEnvelopeBuilder":
        self._data["session_id"] = session_id
        return self

    def with_intent(self, intent: str, domain: str = "general") -> "ContextEnvelopeBuilder":
        self._data["active_intent"] = intent
        self._data["intent_domain"] = domain
        return self

    def with_entities(self, entities: list[str]) -> "ContextEnvelopeBuilder":
        self._data["active_entities"] = entities
        return self

    def with_allowed_tools(self, domains: list[str]) -> "ContextEnvelopeBuilder":
        self._data["allowed_tool_domains"] = domains
        return self

    def with_blocked_tools(self, domains: list[str]) -> "ContextEnvelopeBuilder":
        self._data["blocked_tool_domains"] = domains
        return self

    def with_follow_ups(self, fu_ids: list[str]) -> "ContextEnvelopeBuilder":
        self._data["referenced_follow_up_ids"] = fu_ids
        return self

    def build(self) -> ContextEnvelope:
        return ContextEnvelope(**self._data)


class ContextRetrievalScorer:
    """Avalia relevância de contexto recuperado."""

    @staticmethod
    def score(
        source_conversation_id: str,
        current_conversation_id: str,
        source_entities: list[str],
        current_entities: list[str],
        source_intent: str,
        current_intent: str,
    ) -> dict:
        """Calcula score de relevância do contexto recuperado.

        Returns:
            dict com scores e decisão de uso
        """
        # 1. Mesma conversa é sempre relevante
        if source_conversation_id == current_conversation_id:
            return {"score": 1.0, "use": True, "reason": "same_conversation"}

        # 2. Entity overlap
        entity_overlap = len(set(source_entities) & set(current_entities))
        entity_score = min(entity_overlap / max(len(current_entities), 1), 1.0) if current_entities else 0.0

        # 3. Intent overlap
        intent_match = 1.0 if source_intent == current_intent else 0.0

        # 4. Score composto
        score = entity_score * 0.6 + intent_match * 0.4

        return {
            "score": round(score, 2),
            "entity_overlap": entity_overlap,
            "entity_score": entity_score,
            "intent_match": intent_match,
            "use": score >= 0.3,
            "reason": "entity_or_intent_overlap" if score >= 0.3 else "no_overlap",
        }


# Mapeamento de domínios de intenção para domínios de tool permitidos
INTENT_TO_TOOL_DOMAINS = {
    "contact_info": ["entity_lookup", "cognitive_search", "conversation_history", "follow_up_management"],
    "follow_up": ["follow_up_management", "entity_lookup", "conversation_history"],
    "infrastructure": ["infra", "vps", "cloud", "terminal"],
    "development": ["code", "terminal", "github", "deployment"],
    "marketing": ["content", "media", "scheduling", "notifications"],
    "general": [],  # sem restrição
    "unknown": [],  # sem restrição
}

# Domínios de tool que NUNCA devem ser permitidos para intenções de contato
BLOCKED_TOOL_DOMAINS_FOR_CONTACT = [
    "github", "git", "deployment", "infra", "vps", "cloudflare",
    "composio", "kanban", "terminal",
]