"""
feedback_store.py — Feedback Local (Hermes-side, exclusivo).

Armazena heurísticas de aprendizado do Hermes sobre o uso de Capabilities.
NUNCA é enviado ao Prosperfy Skills.

Feedback Compartilhado (operacional) → vai para Cognitive Register.
Feedback Local (heuristico) → fica aqui.

Dois tipos de feedback:

1. Feedback Compartilhado:
   - duracão, sucesso, rollback, warnings, entities impactadas
   - registrado no Cognitive Register como Events + Artifacts
   - visível para qualquer agente via Cognitive Register

2. Feedback Local (exclusivo do Hermes):
   - histórico de escolhas do Negotiator
   - preferência por determinada Capability
   - heurísticas de score
   - satisfacão do usuário
   - taxa de acerto por intent
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class LocalFeedback:
    """Feedback Local — armazenado exclusivamente no Hermes.

    NUNCA enviado ao Prosperfy Skills.
    """
    capability_id: str
    intent_query_hash: str  # hash da intencão para agrupar
    success: bool
    duration_ms: int = 0
    user_intervention_required: bool = False
    fallback_used: bool = False
    user_satisfaction: int | None = None  # 1-5
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class FeedbackStore:
    """
    Armazena Feedback Local.

    Implementacão inicial: em memória.
    Futuro: SQLite ou arquivo JSON local.
    """

    _feedbacks: list[LocalFeedback] = field(default_factory=list)

    def record(self, feedback: LocalFeedback) -> None:
        """Registra um feedback local."""
        self._feedbacks.append(feedback)

    def get_history(self, capability_id: str) -> list[LocalFeedback]:
        """Retorna feedbacks de uma Capability específica."""
        return [
            f for f in self._feedbacks
            if f.capability_id == capability_id
        ]

    def get_success_rate(self, capability_id: str) -> float:
        """Taxa de sucesso de uma Capability."""
        fb_list = self.get_history(capability_id)
        if not fb_list:
            return 0.0
        return sum(1 for f in fb_list if f.success) / len(fb_list)

    def get_preferred_capability(self, intent_hash: str) -> str | None:
        """Retorna a Capability mais usada para uma intencão."""
        by_intent = [
            f for f in self._feedbacks
            if f.intent_query_hash == intent_hash
        ]
        if not by_intent:
            return None

        from collections import Counter
        counts = Counter(f.capability_id for f in by_intent)
        return counts.most_common(1)[0][0]