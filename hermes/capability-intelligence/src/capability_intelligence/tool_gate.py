"""
tool_gate.py — Tool Relevance Gate e Response Reviewer.

Garante que apenas tools relevantes ao contexto atual sejam executadas,
e que a resposta final seja coerente com a intenção e entidades ativas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from .context_envelope import (
    BLOCKED_TOOL_DOMAINS_FOR_CONTACT,
    ContextEnvelope,
)


class ToolDecision(str, Enum):
    ALLOW = "allow"
    DENY_IRRELEVANT_TOOL = "deny_irrelevant_tool"
    DENY_DOMAIN_MISMATCH = "deny_domain_mismatch"
    DENY_NO_ENTITY_OVERLAP = "deny_no_entity_overlap"
    REQUIRE_REPLAN = "require_replan"
    REQUIRE_CLARIFICATION = "require_clarification"


@dataclass
class ToolGateResult:
    decision: ToolDecision
    reason: str = ""
    entity_overlap: int = 0
    domain: str = ""
    confidence: float = 0.0


class ToolRelevanceGate:
    """Avalia se uma tool pode ser executada no contexto atual.

    Critérios:
    - Intenção atual vs domínio da tool
    - Entidades ativas vs entidades que a tool opera
    - Domínios bloqueados para a intenção atual
    """

    def evaluate(
        self,
        envelope: ContextEnvelope,
        tool_name: str,
        tool_domain: str,
        tool_arguments: dict = None,
    ) -> ToolGateResult:
        if tool_arguments is None:
            tool_arguments = {}

        # Se não há envelope, permitir (modo legado)
        if not envelope or not envelope.conversation_id:
            return ToolGateResult(decision=ToolDecision.ALLOW, reason="no_envelope")

        intent_domain = envelope.intent_domain or "general"
        active_entities = envelope.active_entities or []
        allowed_domains = envelope.allowed_tool_domains or []
        blocked_domains = envelope.blocked_tool_domains or []

        # 1. Verificar domínios bloqueados explícitos
        if blocked_domains and tool_domain in blocked_domains:
            metrics_summary = getattr(__import__('capability_intelligence.follow_up', fromlist=['metrics']), 'metrics', None)
            if metrics_summary:
                metrics_summary.irrelevant_tools_blocked += 1
            return ToolGateResult(
                decision=ToolDecision.DENY_DOMAIN_MISMATCH,
                reason=f"tool domain '{tool_domain}' is explicitly blocked for this intent",
                domain=tool_domain,
            )

        # 2. Para intenções de contato, bloquear domínios não-relacionados
        if intent_domain in ("contact_info", "follow_up"):
            if tool_domain in BLOCKED_TOOL_DOMAINS_FOR_CONTACT:
                metrics_summary = getattr(__import__('capability_intelligence.follow_up', fromlist=['metrics']), 'metrics', None)
                if metrics_summary:
                    metrics_summary.irrelevant_tools_blocked += 1
                return ToolGateResult(
                    decision=ToolDecision.DENY_IRRELEVANT_TOOL,
                    reason=f"contact intent blocked tool domain '{tool_domain}'",
                    domain=tool_domain,
                )

            # Verificar overlap de entidades
            entity_overlap = 0
            if active_entities:
                # Extrair entidades mencionadas nos argumentos
                arg_entities = self._extract_entities_from_args(tool_arguments)
                entity_overlap = len(set(active_entities) & set(arg_entities))

                if entity_overlap == 0 and allowed_domains:
                    return ToolGateResult(
                        decision=ToolDecision.DENY_NO_ENTITY_OVERLAP,
                        reason=f"no entity overlap between active entities and tool arguments",
                        entity_overlap=0,
                        domain=tool_domain,
                    )

        # 3. Se há allowlist de domínios, verificar
        if allowed_domains and tool_domain not in allowed_domains:
            return ToolGateResult(
                decision=ToolDecision.DENY_DOMAIN_MISMATCH,
                reason=f"tool domain '{tool_domain}' not in allowed: {allowed_domains}",
                domain=tool_domain,
            )

        return ToolGateResult(
            decision=ToolDecision.ALLOW,
            reason="tool allowed",
            confidence=1.0,
        )

    def _extract_entities_from_args(self, args: dict) -> list[str]:
        """Extrai possíveis entidades dos argumentos da tool."""
        entities = []
        for key, value in args.items():
            if isinstance(value, str):
                entities.append(value)
            elif isinstance(value, list):
                entities.extend(str(v) for v in value)
        return entities


# ─── Response Reviewer ───────────────────────────────────────────────────

@dataclass
class ReviewResult:
    passed: bool
    intent_alignment_score: float = 0.0
    entity_alignment_score: float = 0.0
    tool_alignment_score: float = 0.0
    conversation_continuity_score: float = 0.0
    internal_metadata_detected: bool = False
    final_decision: str = "block"
    reason: str = ""


class ResponseReviewer:
    """Revisa a resposta candidata antes do envio.

    Avalia:
    - alinhamento com a última mensagem
    - alinhamento com a intenção ativa
    - alinhamento com as entidades ativas
    - coerência das tools executadas
    - presença de metadados internos
    - mudança abrupta de domínio
    """

    INTERNAL_METADATA_PATTERNS = [
        "Cronjob Response",
        "job_id:",
        "(job_id:",
        "correlation_id:",
        "trace_id:",
        "[IMPORTANT:",
        "[SILENT]",
        "DELIVERY:",
        "```terminal",
        "```json",
        "tool_call",
        "tool_result",
    ]

    def review(
        self,
        candidate_response: str,
        envelope: ContextEnvelope,
        executed_tools: list[dict] = None,
        last_user_message: str = "",
    ) -> ReviewResult:
        if executed_tools is None:
            executed_tools = []

        scores = []
        reasons = []

        # 1. Verificar metadados internos
        internal_detected = self._check_internal_metadata(candidate_response)
        if internal_detected:
            return ReviewResult(
                passed=False,
                internal_metadata_detected=True,
                final_decision="block",
                reason="internal_metadata_detected",
            )

        # 2. Alinhamento com entidades ativas
        entity_score = self._score_entity_alignment(candidate_response, envelope)
        scores.append(("entity_alignment", entity_score))
        if entity_score == 0.0 and envelope.active_entities:
            return ReviewResult(
                passed=False,
                entity_alignment_score=0.0,
                final_decision="block",
                reason="no_entity_alignment",
            )

        # 3. Alinhamento com tools executadas
        tool_score = self._score_tool_alignment(candidate_response, executed_tools)
        scores.append(("tool_alignment", tool_score))

        # 4. Intenção
        intent_score = self._score_intent_alignment(
            candidate_response, envelope.active_intent, last_user_message
        )
        scores.append(("intent_alignment", intent_score))

        # 5. Score composto
        avg_score = sum(s for _, s in scores) / max(len(scores), 1)

        if avg_score < 0.3:
            return ReviewResult(
                passed=False,
                intent_alignment_score=intent_score,
                entity_alignment_score=entity_score,
                tool_alignment_score=tool_score,
                final_decision="block",
                reason=f"low_coherence_score_{avg_score:.2f}",
            )

        return ReviewResult(
            passed=True,
            intent_alignment_score=intent_score,
            entity_alignment_score=entity_score,
            tool_alignment_score=tool_score,
            conversation_continuity_score=avg_score,
            final_decision="allow",
            reason="passed",
        )

    def _check_internal_metadata(self, response: str) -> bool:
        """Verifica se a resposta contém metadados internos."""
        lower = response.lower()
        for pattern in self.INTERNAL_METADATA_PATTERNS:
            if pattern.lower() in lower:
                return True
        return False

    def _score_entity_alignment(self, response: str, envelope: ContextEnvelope) -> float:
        """Calcula score de alinhamento com entidades ativas."""
        if not envelope.active_entities:
            return 1.0  # sem entidades, sem penalidade

        lower_response = response.lower()
        matched = 0
        for entity in envelope.active_entities:
            # Tentar partes do nome da entidade
            parts = entity.split("_")
            names_to_check = [entity] + parts  # id completo + cada parte
            found = False
            for name in names_to_check:
                if name.lower() in lower_response:
                    found = True
                    break
            if found:
                matched += 1

        return matched / max(len(envelope.active_entities), 1)

    def _score_tool_alignment(self, response: str, executed_tools: list[dict]) -> float:
        """Verifica se os resultados das tools são refletidos na resposta."""
        if not executed_tools:
            return 0.5  # neutro

        # Pelo menos uma tool foi executada e seu domínio aparece na resposta
        for tool in executed_tools:
            tool_name = tool.get("name", "")
            tool_domain = tool.get("domain", "")
            # Se a resposta menciona o domínio da tool, está alinhada
            if tool_domain and tool_domain.lower() in response.lower():
                return 1.0

        return 0.5

    def _score_intent_alignment(
        self, response: str, intent: str, last_message: str
    ) -> float:
        """Avalia se a resposta corresponde à intenção."""
        if not intent and not last_message:
            return 0.5

        # Intenção deve estar refletida na resposta
        intent_keywords = intent.lower().split()
        response_lower = response.lower()
        matched = sum(1 for kw in intent_keywords if kw in response_lower)
        if intent_keywords:
            return matched / max(len(intent_keywords), 1)
        return 0.5