"""
pipeline.py — Orquestrador do pipeline Capability Intelligence.

Fluxo completo:

Resolver → Negotiator → Policy Engine → Executor → Interpreter → Feedback Store

Cada etapa é independente e tem uma única responsabilidade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .executor import Executor
from .feedback_store import FeedbackStore, LocalFeedback
from .gap_proposal import GapProposalStore
from .interpreter import Interpreter
from .models import (
    AuthorizationResult,
    CapabilityResult,
    CatalogResult,
    Domain,
    ExecutionReference,
    GapProposal,
    IntentQuery,
)
from .negotiator import Negotiator
from .policy_engine import PolicyEngine, PolicyResult
from .resolver import Resolver
from .transport.protocol_adapter import ProtocolAdapter


@dataclass
class PipelineResult:
    """Resultado completo do pipeline."""
    success: bool
    capability_id: str | None = None
    execution_ref: ExecutionReference | None = None
    result: CapabilityResult | None = None
    summary: str = ""
    error: str | None = None
    requires_approval: bool = False
    disambiguation: bool = False
    candidates: list[dict] | None = None
    gap_proposal: GapProposal | None = None


@dataclass
class Pipeline:
    """
    Orquestrador completo do pipeline.

    Cada componente pode ser substituído independentemente
    (injeção de dependência).
    """

    resolver: Resolver
    negotiator: Negotiator
    policy_engine: PolicyEngine
    executor: Executor
    interpreter: Interpreter
    feedback_store: FeedbackStore
    gap_store: GapProposalStore = field(default_factory=GapProposalStore)

    async def run(self, intent: str, domain: Domain | str,
                  context: dict | None = None,
                  preferences: dict | None = None,
                  user: str = "",
                  environment: str = "") -> PipelineResult:
        """Executa o pipeline completo."""

        # 1. RESOLVER — consulta Catálogo
        catalog_result = await self.resolver.resolve(
            intent=intent,
            domain=domain,
            context=context,
            preferences=preferences,
        )

        # 2. NEGOTIATOR — seleciona melhor Capability
        best = self.negotiator.select(catalog_result)

        if best is None:
            # Gap detection: nenhuma Capability adequada
            gap = self.gap_store.register(
                intent=intent,
                domain=str(domain),
                context=context,
            )
            return PipelineResult(
                success=False,
                error=f"Nenhuma Capability encontrada para '{intent}' no domínio '{domain}'",
                gap_proposal=gap,
                candidates=[
                    {"capability_id": m.capability_id, "score": m.score}
                    for m in catalog_result.matches
                ] if catalog_result.matches else None,
            )

        if catalog_result.disambiguation:
            # Múltiplas opções viáveis — precisa de decisão
            return PipelineResult(
                success=False,
                disambiguation=True,
                candidates=[
                    {"capability_id": m.capability_id, "score": m.score,
                     "reason": m.reason}
                    for m in catalog_result.matches[:3]
                ],
                summary=f"Múltiplas Capabilities disponíveis para '{intent}'",
            )

        # 3. POLICY ENGINE — valida políticas
        verdicts = await self.policy_engine.evaluate(
            capability_id=best.capability_id,
            user=user,
            environment=environment,
            domain=str(domain),
        )

        if self.policy_engine.is_denied(verdicts):
            denied = [v for v in verdicts if v.result == PolicyResult.DENY]
            return PipelineResult(
                success=False,
                error=f"Políticas negaram execucão: {[v.reason for v in denied]}",
            )

        if self.policy_engine.requires_approval(verdicts):
            return PipelineResult(
                success=False,
                requires_approval=True,
                capability_id=best.capability_id,
                summary=f"Capability '{best.capability_id}' requer aprovacão",
            )

        # 4. EXECUTOR — executa (agnóstico cognitivo)
        result = await self.executor.run(
            capability_id=best.capability_id,
            params=context or {},
            user=user,
            environment=environment,
        )

        # 5. INTERPRETER — interpreta e atualiza Cognitive Register
        interpretation = await self.interpreter.process(
            result_raw={
                "success": result.success,
                "data": result.data,
                "error": result.error,
                "metadata": {
                    "duration_ms": result.metadata.duration_ms if result.metadata else 0,
                    "entities_impacted": result.metadata.entities_impacted if result.metadata else [],
                    "rollback_executed": result.metadata.rollback_executed if result.metadata else False,
                    "warnings": result.metadata.warnings if result.metadata else [],
                },
            },
            capability_id=best.capability_id,
            domain=str(domain),
        )

        # 6. FEEDBACK STORE — registra feedback local
        self.feedback_store.record(LocalFeedback(
            capability_id=best.capability_id,
            intent_query_hash=str(hash(intent)),
            success=result.success,
            duration_ms=result.metadata.duration_ms if result.metadata else 0,
            user_intervention_required=False,
            user_satisfaction=None,
        ))

        return PipelineResult(
            success=result.success,
            capability_id=best.capability_id,
            execution_ref=result.metadata.execution_ref if result.metadata else None,
            result=result,
            summary=interpretation.summary,
            error=result.error,
        )