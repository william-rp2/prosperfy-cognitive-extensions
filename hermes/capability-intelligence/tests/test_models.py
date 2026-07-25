"""
Testes do módulo Capability Intelligence v1.0

Prioridade: simplicidade, baixo acoplamento, cobertura de bordas.
"""

import pytest
from datetime import datetime

from capability_intelligence.models import (
    AuthorizationRequest,
    AuthorizationResult,
    CapabilityFeedback,
    CapabilityMetadata,
    CapabilityMaturity,
    CapabilityResult,
    CatalogMatch,
    CatalogResult,
    Domain,
    ExecutionReference,
    ExecutionRequest,
    IntentQuery,
    ResultMetadata,
    StatusResult,
)


class TestModels:
    """Testes dos modelos de contrato abstrato."""

    def test_intent_query_basics(self):
        q = IntentQuery(intent="deploy api", domain="infrastructure")
        assert q.intent == "deploy api"
        assert q.domain == "infrastructure"
        assert q.context == {}

    def test_intent_query_with_domain_enum(self):
        q = IntentQuery(intent="gerar banner", domain=Domain.MARKETING)
        assert q.domain == Domain.MARKETING

    def test_catalog_match_sorting(self):
        m1 = CatalogMatch(capability_id="a", score=0.9, reason="x")
        m2 = CatalogMatch(capability_id="b", score=0.5, reason="y")
        assert m1.score > m2.score

    def test_catalog_result_ordering(self):
        result = CatalogResult(matches=[
            CatalogMatch(capability_id="c", score=0.3, reason="z"),
            CatalogMatch(capability_id="a", score=0.9, reason="x"),
            CatalogMatch(capability_id="b", score=0.5, reason="y"),
        ])
        result.matches.sort(key=lambda m: m.score, reverse=True)
        assert result.matches[0].capability_id == "a"
        assert result.matches[2].capability_id == "c"

    def test_capability_result_success(self):
        r = CapabilityResult(
            success=True,
            data={"deploy_id": "dep_123"},
            metadata=ResultMetadata(duration_ms=45000),
        )
        assert r.success
        assert r.data["deploy_id"] == "dep_123"
        assert r.metadata.duration_ms == 45000

    def test_capability_result_failure(self):
        r = CapabilityResult(
            success=False,
            error="Connection timeout",
        )
        assert not r.success
        assert "Connection timeout" in r.error

    def result_metadata_with_entities(self):
        m = ResultMetadata(
            duration_ms=12000,
            execution_ref=ExecutionReference(ref="exec_abc"),
            entities_impacted=["vps-01", "app-evolution"],
            rollback_executed=False,
            warnings=["SSL expira em 15 dias"],
        )
        assert len(m.entities_impacted) == 2
        assert m.execution_ref.ref == "exec_abc"

    def test_execution_reference_opaque(self):
        ref = ExecutionReference(ref="qualquer-coisa-formato-interno")
        # Hermes nunca interpreta o formato, só armazena
        assert isinstance(ref.ref, str)

    def test_capability_feedback_local_only(self):
        fb = CapabilityFeedback(
            capability_id="deploy_api",
            intent_query=IntentQuery(intent="deploy", domain="infrastructure"),
            execution_ref=ExecutionReference(ref="exec_1"),
            success=True,
            duration_ms=30000,
        )
        assert not fb.user_intervention_required
        assert fb._success_rate == 0.0  # derivada, não persistida

    def test_domain_enum_values(self):
        assert Domain.INFRASTRUCTURE.value == "infrastructure"
        assert Domain.MARKETING.value == "marketing"
        assert Domain.OTHER.value == "other"

    def test_capability_metadata_defaults(self):
        m = CapabilityMetadata(capability_id="test")
        assert m.maturity == CapabilityMaturity.STABLE
        assert m.required_role == "observer"
        assert m.environments == []

    def test_authorization_result(self):
        r = AuthorizationResult(authorized=True, requires_approval=False)
        assert r.authorized
        assert not r.requires_approval

    def test_status_result(self):
        s = StatusResult(healthy=True, capabilities_total=50)
        assert s.healthy
        assert s.capabilities_total == 50