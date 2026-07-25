"""
negotiator.py — Seleciona a melhor Capability entre os candidatos.

Usa o Feedback Local (Hermes-side) para ajustar scores do Catálogo
e escolher a Capability mais adequada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from .models import (
    CapabilityFeedback,
    CatalogMatch,
    CatalogResult,
)


# Thresholds de decisão
SCORE_GAP_AUTO: float = 0.30  # diferença mínima para auto-select
SCORE_MIN_CONFIDENCE: float = 0.50  # score mínimo para considerar


@dataclass
class Negotiator:
    """Seleciona a melhor Capability usando Catálogo + Feedback histórico."""

    feedback_history: list[CapabilityFeedback] = field(default_factory=list)

    def select(self, catalog_result: CatalogResult) -> CatalogMatch | None:
        """
        Ajusta scores com Feedback Local e retorna a melhor opção.

        Regras:
        1. Score < SCORE_MIN_CONFIDENCE → gap detection
        2. Top2 gap > SCORE_GAP_AUTO → auto-select
        3. Top2 gap <= SCORE_GAP_AUTO → ambiguidade (pergunta ao usuário)
        4. Feedback histórico ajusta scores (penaliza falhas, bonifica acertos)
        """
        matches = catalog_result.matches
        if not matches:
            return None

        # Ajusta scores com feedback histórico
        self._apply_feedback(matches)

        # Reordena por score ajustado
        matches.sort(key=lambda m: m.score, reverse=True)

        best = matches[0]

        # Gap detection: score muito baixo
        if best.score < SCORE_MIN_CONFIDENCE:
            return None

        # Auto-select vs ambiguity
        if len(matches) > 1:
            gap = best.score - matches[1].score
            if gap <= SCORE_GAP_AUTO:
                # Marca para disambiguation (será resolvido pelo caller)
                catalog_result.disambiguation = True

        return best

    def _apply_feedback(self, matches: list[CatalogMatch]) -> None:
        """Ajusta scores com base em feedback histórico."""
        if not self.feedback_history:
            return

        for match in matches:
            fb_list = [f for f in self.feedback_history
                       if f.capability_id == match.capability_id
                       and f.success is not None]
            if not fb_list:
                continue

            success_rate = mean(1 for f in fb_list if f.success)
            interventions = sum(1 for f in fb_list if f.user_intervention_required)
            intervention_rate = interventions / len(fb_list)

            # Penaliza falhas frequentes
            if success_rate < 0.8:
                match.score *= 0.90

            # Penaliza intervencões frequentes
            if intervention_rate > 0.3:
                match.score *= 0.85

            # Bonifica confiabilidade
            durations = [f.duration_ms for f in fb_list if f.duration_ms]
            if durations:
                avg_duration = mean(durations)
                expected = (match.metadata.avg_duration_seconds * 1000
                            if isinstance(match.metadata, dict)
                            and match.metadata.get("avg_duration_seconds")
                            else 0)
                if success_rate > 0.95 and expected > 0 and avg_duration <= expected:
                    match.score *= 1.05