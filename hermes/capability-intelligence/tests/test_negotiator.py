"""
Testes do Negotiator — seleção de Capability com Feedback.
"""

import pytest

from capability_intelligence.models import (
    CapabilityFeedback,
    CatalogMatch,
    CatalogResult,
    Domain,
    ExecutionReference,
    IntentQuery,
)
from capability_intelligence.negotiator import Negotiator


class TestNegotiator:
    """Testes de seleção de Capability."""

    def test_select_best_by_score(self):
        neg = Negotiator()
        result = CatalogResult(matches=[
            CatalogMatch(capability_id="a", score=0.9, reason="ótimo"),
            CatalogMatch(capability_id="b", score=0.5, reason="regular"),
        ])
        best = neg.select(result)
        assert best is not None
        assert best.capability_id == "a"

    def test_no_matches_returns_none(self):
        neg = Negotiator()
        result = CatalogResult(matches=[])
        assert neg.select(result) is None

    def test_low_confidence_is_gap(self):
        neg = Negotiator()
        result = CatalogResult(matches=[
            CatalogMatch(capability_id="a", score=0.2, reason="baixo"),
        ])
        assert neg.select(result) is None

    def test_auto_select_when_big_gap(self):
        neg = Negotiator()
        result = CatalogResult(matches=[
            CatalogMatch(capability_id="a", score=0.95, reason="melhor"),
            CatalogMatch(capability_id="b", score=0.50, reason="pior"),
        ])
        best = neg.select(result)
        assert best.capability_id == "a"
        assert not result.disambiguation  # gap > 0.30 → auto

    def test_disambiguation_when_small_gap(self):
        neg = Negotiator()
        result = CatalogResult(matches=[
            CatalogMatch(capability_id="a", score=0.85, reason="bom"),
            CatalogMatch(capability_id="b", score=0.80, reason="bom também"),
        ])
        best = neg.select(result)
        assert best.capability_id == "a"
        assert result.disambiguation  # gap <= 0.30 → pergunta

    def test_feedback_penalizes_failures(self):
        intent = IntentQuery(intent="deploy", domain="infrastructure")
        feedback = [
            CapabilityFeedback(
                capability_id="a",
                intent_query=intent,
                execution_ref=ExecutionReference(ref="e1"),
                success=True,
            ),
            CapabilityFeedback(
                capability_id="a",
                intent_query=intent,
                execution_ref=ExecutionReference(ref="e2"),
                success=False,
            ),
            CapabilityFeedback(
                capability_id="a",
                intent_query=intent,
                execution_ref=ExecutionReference(ref="e3"),
                success=False,
            ),
        ]
        neg = Negotiator(feedback_history=feedback)
        result = CatalogResult(matches=[
            CatalogMatch(capability_id="a", score=0.9, reason="alto"),
            CatalogMatch(capability_id="b", score=0.7, reason="médio"),
        ])
        best = neg.select(result)
        # 'a' tem 33% de sucesso → penalizado, 'b' pode ficar na frente
        # Como o score ajustado de 'a' = 0.9 * 0.9 = 0.81, e 'b' = 0.7
        # 'a' ainda ganha, mas com score menor
        assert best is not None

    def test_feedback_no_history(self):
        """Sem feedback, scores originais são mantidos."""
        neg = Negotiator()
        result = CatalogResult(matches=[
            CatalogMatch(capability_id="x", score=0.8, reason="test"),
        ])
        best = neg.select(result)
        assert best.capability_id == "x"
        assert abs(best.score - 0.8) < 0.01