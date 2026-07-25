"""
Testes do Feedback Store (local, Hermes-side).
"""

import pytest
from datetime import datetime

from capability_intelligence.feedback_store import FeedbackStore, LocalFeedback
from capability_intelligence.models import Domain, IntentQuery


class TestFeedbackStore:
    """Testes do armazenamento local de feedback."""

    def test_record_and_retrieve(self):
        store = FeedbackStore()
        fb = LocalFeedback(
            capability_id="deploy_api",
            intent_query_hash="abc123",
            success=True,
            duration_ms=30000,
        )
        store.record(fb)
        history = store.get_history("deploy_api")
        assert len(history) == 1
        assert history[0].success

    def test_success_rate(self):
        store = FeedbackStore()
        for i in range(5):
            store.record(LocalFeedback(
                capability_id="x",
                intent_query_hash="h1",
                success=i < 4,  # 4 success, 1 fail
            ))
        rate = store.get_success_rate("x")
        assert rate == 0.8

    def test_success_rate_empty(self):
        store = FeedbackStore()
        assert store.get_success_rate("nonexistent") == 0.0

    def test_preferred_capability(self):
        store = FeedbackStore()
        for cap in ["a", "a", "b", "a", "b"]:
            store.record(LocalFeedback(
                capability_id=cap,
                intent_query_hash="intent_1",
                success=True,
            ))
        preferred = store.get_preferred_capability("intent_1")
        assert preferred == "a"  # 'a' aparece 3x, 'b' 2x

    def test_preferred_capability_empty(self):
        store = FeedbackStore()
        assert store.get_preferred_capability("unknown") is None

    def test_user_satisfaction(self):
        store = FeedbackStore()
        store.record(LocalFeedback(
            capability_id="deploy",
            intent_query_hash="h1",
            success=True,
            user_satisfaction=5,
        ))
        fb = store.get_history("deploy")[0]
        assert fb.user_satisfaction == 5

    def test_duration(self):
        store = FeedbackStore()
        store.record(LocalFeedback(
            capability_id="slow",
            intent_query_hash="h1",
            success=True,
            duration_ms=120000,
        ))
        assert store.get_history("slow")[0].duration_ms == 120000