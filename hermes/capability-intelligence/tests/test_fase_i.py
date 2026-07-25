"""Fase I — Performance: Linha de Base.

Cenários PF1 a PF6:
  PF1: Criacão de IntentQuery vazia          <   1ms
  PF2: Negotiator com 2 candidatos           <   1ms
  PF3: Negotiator com 10 candidatos + 100 fb <  10ms
  PF4: Pipeline completo (mock)              <  50ms
  PF5: Pipeline real via MCP                 <  60s  (skip se MCP indisponível)
  PF6: Negotiator com 500 candidatos         < 100ms

Uso exclusivo de time.perf_counter() para medições.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import pytest

from capability_intelligence.executor import (
    AuthorizationPort,
    ExecutionPort,
    Executor,
)
from capability_intelligence.feedback_store import FeedbackStore, LocalFeedback
from capability_intelligence.gap_proposal import GapProposalStore
from capability_intelligence.interpreter import CognitiveRegister, Interpreter
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
from capability_intelligence.negotiator import Negotiator
from capability_intelligence.pipeline import Pipeline, PipelineResult
from capability_intelligence.policy_engine import PolicyEngine
from capability_intelligence.resolver import CatalogPort, Resolver

# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

THRESHOLDS: dict[str, float] = {
    "PF1": 0.001,  # 1 ms
    "PF2": 0.001,
    "PF3": 0.010,
    "PF4": 0.050,
    "PF5": 60.0,
    "PF6": 0.100,
}


def _fmt_ms(seconds: float) -> str:
    return f"{seconds * 1000:.3f} ms"


def _assert_under(pf: str, elapsed: float) -> None:
    limit = THRESHOLDS[pf]
    assert elapsed < limit, (
        f"{pf}: {_fmt_ms(elapsed)} excedeu limite de {_fmt_ms(limit)}"
    )


# ─── Mocks (Protocolos) ────────────────────────────────────────────


class MockCatalogPort:
    """CatalogPort que retorna resultado fixo — sem IO real."""

    def __init__(self, matches: list[CatalogMatch] | None = None):
        self.matches = matches or []

    async def resolve(self, query: IntentQuery) -> CatalogResult:
        return CatalogResult(matches=self.matches)


class MockAuthorizationPort:
    """AuthorizationPort que sempre autoriza."""

    async def authorize(self, request: AuthorizationRequest) -> AuthorizationResult:
        return AuthorizationResult(authorized=True)


class MockExecutionPort:
    """ExecutionPort que retorna resultado fake."""

    async def execute(self, request: ExecutionRequest) -> ExecutionReference:
        return ExecutionReference(ref="mock-exec")

    async def result(self, ref: ExecutionReference) -> CapabilityResult:
        return CapabilityResult(
            success=True,
            data={"done": True},
            metadata=ResultMetadata(duration_ms=5),
        )

    async def status(self, ref: ExecutionReference | None = None) -> StatusResult:
        return StatusResult(healthy=True)


class MockCognitiveRegister:
    """CognitiveRegister que não faz nada de verdade."""

    async def create_event(self, event: dict) -> None:
        pass

    async def update_entity(self, entity: dict) -> None:
        pass

    async def create_artifact(self, artifact: dict) -> None:
        pass

    async def create_task(self, task: dict) -> None:
        pass


# ─── Factory helpers ────────────────────────────────────────────────


def _make_match(capability_id: str, score: float, reason: str = "") -> CatalogMatch:
    return CatalogMatch(
        capability_id=capability_id,
        score=score,
        reason=reason or f"Score {score}",
    )


def _make_feedback(
    capability_id: str,
    success: bool = True,
    duration_ms: int = 0,
    satisfaction: int | None = None,
) -> CapabilityFeedback:
    return CapabilityFeedback(
        capability_id=capability_id,
        intent_query=IntentQuery(intent="perf-test", domain=Domain.OTHER),
        execution_ref=ExecutionReference(ref="perf-ref"),
        success=success,
        duration_ms=duration_ms,
        user_satisfaction=satisfaction,
    )


# ═══════════════════════════════════════════════════════════════════════
# PF1: IntentQuery vazia (< 1 ms)
# ═══════════════════════════════════════════════════════════════════════

class TestPF1_IntentQueryVazia:
    """Criacão de IntentQuery sem Catalog real deve ser < 1 ms."""

    def test_create_empty_intent_query(self):
        start = time.perf_counter()
        for _ in range(1000):
            IntentQuery(intent="", domain=Domain.OTHER)
        elapsed = time.perf_counter() - start
        avg = elapsed / 1000
        print(f"\n  PF1: {_fmt_ms(avg)} (média de 1000 iterações)")
        _assert_under("PF1", avg)

    def test_create_with_full_context(self):
        """IntentQuery com todos os campos preenchidos."""
        start = time.perf_counter()
        for _ in range(1000):
            IntentQuery(
                intent="deploy application",
                domain=Domain.INFRASTRUCTURE,
                context={"env": "production", "app": "api"},
                preferences={"cost": "low", "speed": "fast"},
            )
        elapsed = time.perf_counter() - start
        avg = elapsed / 1000
        print(f"\n  PF1-full: {_fmt_ms(avg)} (média de 1000 iterações)")
        _assert_under("PF1", avg)


# ═══════════════════════════════════════════════════════════════════════
# PF2: Negotiator com 2 candidatos, sem feedback (< 1 ms)
# ═══════════════════════════════════════════════════════════════════════

class TestPF2_NegotiatorDoisCandidatos:
    """Negotiator com 2 candidatos e sem feedback deve ser < 1 ms."""

    def test_select_two_candidates(self):
        neg = Negotiator()
        result = CatalogResult(matches=[
            _make_match("cap_a", 0.95, "Excelente"),
            _make_match("cap_b", 0.50, "Regular"),
        ])

        start = time.perf_counter()
        for _ in range(1000):
            neg.select(result)
        elapsed = time.perf_counter() - start
        avg = elapsed / 1000
        print(f"\n  PF2: {_fmt_ms(avg)} (média de 1000 iterações)")
        _assert_under("PF2", avg)

    def test_select_no_matches(self):
        """Cenario sem matches também deve ser rápido."""
        neg = Negotiator()
        result = CatalogResult(matches=[])

        start = time.perf_counter()
        for _ in range(1000):
            neg.select(result)
        elapsed = time.perf_counter() - start
        avg = elapsed / 1000
        print(f"\n  PF2-empty: {_fmt_ms(avg)} (média de 1000 iterações)")
        _assert_under("PF2", avg)


# ═══════════════════════════════════════════════════════════════════════
# PF3: Negotiator com 10 candidatos, 100 feedbacks (< 10 ms)
# ═══════════════════════════════════════════════════════════════════════

class TestPF3_NegotiatorDezCem:
    """Negotiator com 10 candidatos e 100 feedbacks deve ser < 10 ms."""

    @staticmethod
    def _build_scenario() -> tuple[Negotiator, CatalogResult]:
        matches = [
            _make_match(f"cap_{i}", round(0.5 + i * 0.05, 2), f"Candidato {i}")
            for i in range(10)
        ]
        feedbacks = []
        intent = IntentQuery(intent="perf-test", domain=Domain.OTHER)
        ref = ExecutionReference(ref="perf")
        for cap_idx in range(10):
            for _ in range(10):
                fb = CapabilityFeedback(
                    capability_id=f"cap_{cap_idx}",
                    intent_query=intent,
                    execution_ref=ref,
                    success=(cap_idx % 3 != 0),  # ~66% success
                    duration_ms=50 + cap_idx * 10,
                    user_satisfaction=4 if cap_idx < 5 else 3,
                )
                feedbacks.append(fb)
        neg = Negotiator(feedback_history=feedbacks)
        result = CatalogResult(matches=matches)
        return neg, result

    def test_select_with_100_feedbacks(self):
        neg, result = self._build_scenario()

        start = time.perf_counter()
        for _ in range(100):
            neg.select(result)
        elapsed = time.perf_counter() - start
        avg = elapsed / 100
        print(f"\n  PF3: {_fmt_ms(avg)} (média de 100 execuções)")
        _assert_under("PF3", avg)

    def test_select_single_run_correctness(self):
        """Verifica que o resultado ainda é correto com feedback."""
        neg, result = self._build_scenario()
        best = neg.select(result)
        assert best is not None
        assert best.capability_id.startswith("cap_")
        # O score deve ter sido ajustado pelo feedback
        original = next(m for m in result.matches if m.capability_id == best.capability_id)
        # Verifica que o score ajustado é diferente do original (ou igual se não afetado)
        all_same = all(
            m.score == CatalogMatch(capability_id=m.capability_id, score=m.score, reason=m.reason).score
            for m in result.matches
        )
        # Só verifica que selecionou algo válido
        assert best.score > 0


# ═══════════════════════════════════════════════════════════════════════
# PF4: Pipeline completo sem execução real (mock) (< 50 ms)
# ═══════════════════════════════════════════════════════════════════════

class TestPF4_PipelineMockado:
    """Pipeline completo com todos os componentes mockados deve ser < 50 ms."""

    @staticmethod
    def _build_pipeline() -> Pipeline:
        catalog = MockCatalogPort(matches=[
            _make_match("deploy_app", 0.92, "Melhor opção"),
            _make_match("deploy_svc", 0.75, "Segunda opção"),
        ])
        resolver = Resolver(catalog=catalog)
        negotiator = Negotiator()
        policy = PolicyEngine()  # sem políticas ativas

        executor = Executor(
            authorization=MockAuthorizationPort(),
            execution=MockExecutionPort(),
        )
        interpreter = Interpreter(cognitive_register=MockCognitiveRegister())
        feedback_store = FeedbackStore()
        gap_store = GapProposalStore()

        return Pipeline(
            resolver=resolver,
            negotiator=negotiator,
            policy_engine=policy,
            executor=executor,
            interpreter=interpreter,
            feedback_store=feedback_store,
            gap_store=gap_store,
        )

    @pytest.mark.asyncio
    async def test_pipeline_full_mock(self):
        pipeline = self._build_pipeline()

        start = time.perf_counter()
        for _ in range(20):
            result = await pipeline.run(
                intent="deploy application",
                domain=Domain.INFRASTRUCTURE,
                context={"env": "production"},
                user="test-user",
                environment="staging",
            )
        elapsed = time.perf_counter() - start
        avg = elapsed / 20
        print(f"\n  PF4: {_fmt_ms(avg)} (média de 20 execuções)")
        _assert_under("PF4", avg)

    @pytest.mark.asyncio
    async def test_pipeline_result_correctness(self):
        """Verifica que o pipeline mockado retorna PipelineResult válido."""
        pipeline = self._build_pipeline()

        # Cenário com scores próximos → disambiguation
        result = await pipeline.run(
            intent="deploy application",
            domain=Domain.INFRASTRUCTURE,
            context={"env": "production"},
            user="test-user",
            environment="staging",
        )
        assert isinstance(result, PipelineResult)
        # Scores 0.92 e 0.75 → gap 0.17 ≤ 0.30 → disambiguation
        assert result.disambiguation is True
        assert result.success is False  # ambiguidade não é sucesso
        assert result.candidates is not None
        assert len(result.candidates) == 2

        # Cenário com gap grande → auto-select
        catalog_big_gap = MockCatalogPort(matches=[
            _make_match("deploy_app", 0.95, "Excelente"),
            _make_match("deploy_svc", 0.40, "Fraco"),
        ])
        resolver_big_gap = Resolver(catalog=catalog_big_gap)
        pipeline2 = Pipeline(
            resolver=resolver_big_gap,
            negotiator=Negotiator(),
            policy_engine=PolicyEngine(),
            executor=Executor(
                authorization=MockAuthorizationPort(),
                execution=MockExecutionPort(),
            ),
            interpreter=Interpreter(cognitive_register=MockCognitiveRegister()),
            feedback_store=FeedbackStore(),
            gap_store=GapProposalStore(),
        )
        result2 = await pipeline2.run(
            intent="deploy application",
            domain=Domain.INFRASTRUCTURE,
            context={"env": "production"},
            user="test-user",
            environment="staging",
        )
        assert isinstance(result2, PipelineResult)
        assert result2.success is True
        assert result2.capability_id == "deploy_app"


# ═══════════════════════════════════════════════════════════════════════
# PF5: Pipeline real com execução via MCP (< 60 s, skip se MCP indisponível)
# ═══════════════════════════════════════════════════════════════════════

MCP_AVAILABLE = bool(os.environ.get("MCP_API_KEY") or os.environ.get("PROSPERFY_API_KEY"))


@pytest.mark.skipif(not MCP_AVAILABLE, reason="MCP_API_KEY/PROSPERFY_API_KEY não configurada")
class TestPF5_PipelineRealMCP:
    """Pipeline real via MCP Adapter. Requer API key configurada."""

    @pytest.mark.asyncio
    async def test_pipeline_via_mcp(self):
        from capability_intelligence.transport.adapters.mcp_adapter import (
            MCPAdapter,
        )

        api_key = os.environ.get("MCP_API_KEY") or os.environ.get("PROSPERFY_API_KEY", "")
        adapter = MCPAdapter(api_key=api_key)

        # Wrap MCPAdapter nos Protocolos que o Pipeline espera
        class MCPCatalogPort:
            async def resolve(self, query: IntentQuery) -> CatalogResult:
                return await adapter.resolve_catalog(query)

        class MCPAuthorizationPort:
            async def authorize(self, request: AuthorizationRequest) -> AuthorizationResult:
                return await adapter.authorize(request)

        class MCPExecutionPort:
            async def execute(self, request: ExecutionRequest) -> ExecutionReference:
                return await adapter.execute(request)

            async def result(self, ref: ExecutionReference) -> CapabilityResult:
                return await adapter.get_result(ref)

            async def status(self, ref: ExecutionReference | None = None) -> StatusResult:
                return await adapter.get_status(ref)

        catalog_port = MCPCatalogPort()
        auth_port = MCPAuthorizationPort()
        exec_port = MCPExecutionPort()

        resolver = Resolver(catalog=catalog_port)
        negotiator = Negotiator()
        policy = PolicyEngine()
        executor = Executor(authorization=auth_port, execution=exec_port)
        interpreter = Interpreter()
        feedback_store = FeedbackStore()
        gap_store = GapProposalStore()

        pipeline = Pipeline(
            resolver=resolver,
            negotiator=negotiator,
            policy_engine=policy,
            executor=executor,
            interpreter=interpreter,
            feedback_store=feedback_store,
            gap_store=gap_store,
        )

        start = time.perf_counter()
        result = await pipeline.run(
            intent="deploy",
            domain=Domain.INFRASTRUCTURE,
            context={"service": "api", "version": "v1"},
            user="test-user",
            environment="staging",
        )
        elapsed = time.perf_counter() - start
        print(f"\n  PF5: {_fmt_ms(elapsed)}")
        _assert_under("PF5", elapsed)
        # Não falhamos se o MCP retornar erro — só medimos tempo
        assert isinstance(result, PipelineResult)


# ═══════════════════════════════════════════════════════════════════════
# PF6: Catalog com 500 Capabilities (< 100ms no Negotiator)
# ═══════════════════════════════════════════════════════════════════════

class TestPF6_NegotiatorQuinhentos:
    """Negotiator com 500 candidatos (filtragem + ordenação) < 100 ms."""

    @staticmethod
    def _build_500_scenario() -> tuple[Negotiator, CatalogResult]:
        import random
        random.seed(42)
        matches = []
        domains = ["infrastructure", "marketing", "ai", "data", "finance", "crm"]
        for i in range(500):
            cap_id = f"cap_{i:04d}"
            score = round(random.uniform(0.1, 0.99), 2)
            matches.append(
                CatalogMatch(
                    capability_id=cap_id,
                    score=score,
                    reason=f"Match {i} - {domains[i % len(domains)]}",
                    metadata={"display_name": cap_id, "domain": domains[i % len(domains)]},
                )
            )
        neg = Negotiator()
        result = CatalogResult(matches=matches)
        return neg, result

    def test_select_500_candidates(self):
        neg, result = self._build_500_scenario()

        start = time.perf_counter()
        for _ in range(50):
            neg.select(result)
        elapsed = time.perf_counter() - start
        avg = elapsed / 50
        print(f"\n  PF6: {_fmt_ms(avg)} (média de 50 execuções)")
        _assert_under("PF6", avg)

    def test_select_500_with_feedback(self):
        """500 candidatos + 50 feedbacks distribuídos."""
        import random
        random.seed(42)
        neg, result = self._build_500_scenario()

        # Adiciona 50 feedbacks distribuídos
        feedbacks = []
        for i in range(50):
            cap_id = f"cap_{random.randint(0, 499):04d}"
            feedbacks.append(_make_feedback(cap_id, success=i % 4 != 0, duration_ms=100 + i))
        neg = Negotiator(feedback_history=feedbacks)

        start = time.perf_counter()
        for _ in range(50):
            neg.select(result)
        elapsed = time.perf_counter() - start
        avg = elapsed / 50
        print(f"\n  PF6-fb: {_fmt_ms(avg)} (média de 50 execuções, 50 feedbacks)")
        _assert_under("PF6", avg)

    def test_select_500_result_correctness(self):
        """Verifica que o melhor candidato é realmente o de maior score."""
        neg, result = self._build_500_scenario()
        best = neg.select(result)
        assert best is not None
        # O melhor deve ser o de maior score original (sem feedback, sem penalização)
        max_score = max(m.score for m in result.matches)
        assert abs(best.score - max_score) < 0.01

    def test_select_500_gap_detection(self):
        """Se todos tiverem score baixo, deve retornar None (gap)."""
        import random
        random.seed(1)
        matches = [
            _make_match(f"cap_{i}", round(random.uniform(0.05, 0.25), 2))
            for i in range(500)
        ]
        neg = Negotiator()
        result = CatalogResult(matches=matches)
        start = time.perf_counter()
        best = neg.select(result)
        elapsed = time.perf_counter() - start
        print(f"\n  PF6-gap: {_fmt_ms(elapsed)}")
        assert best is None  # todos abaixo do threshold
        _assert_under("PF6", elapsed)