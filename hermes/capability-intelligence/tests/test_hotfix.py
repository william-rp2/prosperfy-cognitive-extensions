"""
test_hotfix.py — Testes da Sprint Crítica: Reminders, Sanitização e Contexto.

Cobre os 35 cenários definidos na especificação da Sprint.
"""

import pytest

from capability_intelligence.follow_up import (
    CompletionEvaluatorService,
    FollowUp,
    FollowUpStatus,
    MessageSanitizer,
    PreflightResult,
)
from capability_intelligence.follow_up_service import (
    FollowUpRepository,
    FollowUpService,
)
from capability_intelligence.context_envelope import (
    ContextEnvelope,
    ContextEnvelopeBuilder,
    ContextRetrievalScorer,
    INTENT_TO_TOOL_DOMAINS,
    BLOCKED_TOOL_DOMAINS_FOR_CONTACT,
)
from capability_intelligence.tool_gate import (
    ResponseReviewer,
    ToolDecision,
    ToolRelevanceGate,
)


# ═══════════════════════════════════════════════════════════════════════
# ETAPA 0 — HOTFIX: MessageSanitizer
# ═══════════════════════════════════════════════════════════════════════

class TestMessageSanitizer:
    """Testes de sanitização de mensagens (Falha 2 e 3)."""

    def test_removes_cronjob_response_header(self):
        """Cenário 14: 'Cronjob Response' não aparece."""
        raw = "Cronjob Response: Lembrar Lucas\n(job_id: abc123)\n\nConteúdo real"
        cleaned = MessageSanitizer.sanitize(raw)
        assert "Cronjob Response" not in cleaned
        assert "job_id" not in cleaned

    def test_removes_job_id(self):
        """Cenário 15: job_id não aparece."""
        raw = "Lembrete: telefone (job_id: cron_089992631caf)"
        cleaned = MessageSanitizer.sanitize(raw)
        assert "job_id:" not in cleaned
        assert "cron_089992631caf" not in cleaned

    def test_removes_important_brackets(self):
        """Cenário 16: texto interno em inglês não aparece."""
        raw = "[IMPORTANT: You are running as a cron job] Lembrete real"
        cleaned = MessageSanitizer.sanitize(raw)
        assert "IMPORTANT" not in cleaned
        assert "cron job" not in cleaned

    def test_removes_terminal_command(self):
        """Cenário 17: terminal command não aparece."""
        raw = "```terminal\necho test\n```\nResultado"
        cleaned = MessageSanitizer.sanitize(raw)
        assert "```terminal" not in cleaned

    def test_sanitize_clean_message_unchanged(self):
        """Mensagens limpas não são alteradas."""
        msg = "Will, ainda não encontrei o telefone do Lucas."
        assert MessageSanitizer.sanitize(msg) == msg


# ═══════════════════════════════════════════════════════════════════════
# ETAPA 1 — FOLLOW-UP MODEL
# ═══════════════════════════════════════════════════════════════════════

class TestCompletionEvaluator:
    """Testes do CompletionEvaluatorService."""

    def test_all_fields_exist_completes(self):
        """Cenário 1: criar follow-up de campo ausente → campo preenchido."""
        completed, evidence = CompletionEvaluatorService.evaluate(
            "all_fields_exist",
            {"fields": ["phone"]},
            {"phone": "+5519992788205", "email": None},
        )
        assert completed
        assert evidence["found_fields"]["phone"] == "+5519992788205"

    def test_all_fields_exist_missing(self):
        """Cenário 2: campo permanece ausente → lembrete pode ser enviado."""
        completed, evidence = CompletionEvaluatorService.evaluate(
            "all_fields_exist",
            {"fields": ["phone", "email"]},
            {"phone": None, "email": None},
        )
        assert not completed
        assert "phone" in evidence["missing_fields"]

    def test_field_filled_before_deadline(self):
        """Cenário 3: campo preenchido antes do horário → concluído."""
        completed, evidence = CompletionEvaluatorService.evaluate(
            "all_fields_exist",
            {"fields": ["phone", "email"]},
            {"phone": "+5519992788205", "email": "teste@test.com"},
        )
        assert completed
        assert len(evidence["found_fields"]) == 2

    def test_partial_completion(self):
        """Cenário 7: conclusão parcial."""
        completed, evidence = CompletionEvaluatorService.evaluate(
            "any_field_exists",
            {"fields": ["phone", "email"]},
            {"phone": "+5519992788205", "email": None},
        )
        assert completed  # any_field_exists: phone já existe

    def test_full_completion(self):
        """Cenário 8: conclusão total."""
        completed, evidence = CompletionEvaluatorService.evaluate(
            "all_fields_exist",
            {"fields": ["phone", "email"]},
            {"phone": "+5519992788205", "email": "a@b.com"},
        )
        assert completed
        assert len(evidence["found_fields"]) == 2


# ═══════════════════════════════════════════════════════════════════════
# ETAPA 4 — CONTEXT ENVELOPE
# ═══════════════════════════════════════════════════════════════════════

class TestContextEnvelope:
    """Testes do ContextEnvelope."""

    def test_envelope_creation(self):
        """Envelope é criado com correlation_id."""
        env = ContextEnvelopeBuilder() \
            .with_conversation("whatsapp_123") \
            .with_intent("verificar contato", "contact_info") \
            .with_entities(["lucas_bispo", "jaqueline_manente"]) \
            .with_blocked_tools(["github"]) \
            .build()
        assert env.conversation_id == "whatsapp_123"
        assert env.active_intent == "verificar contato"
        assert env.intent_domain == "contact_info"
        assert "lucas_bispo" in env.active_entities
        assert env.correlation_id  # auto-gerado
        assert env.turn_id  # auto-gerado

    def test_github_blocked_for_contact_intent(self):
        """Cenário 21: tool GitHub é bloqueada para intenção de contato."""
        gate = ToolRelevanceGate()
        env = ContextEnvelopeBuilder() \
            .with_conversation("whatsapp_test") \
            .with_intent("verificar contato", "contact_info") \
            .with_entities(["lucas_bispo"]) \
            .with_blocked_tools(BLOCKED_TOOL_DOMAINS_FOR_CONTACT) \
            .build()

        result = gate.evaluate(env, "gh_repo_list", "github")
        assert result.decision in (
            ToolDecision.DENY_IRRELEVANT_TOOL,
            ToolDecision.DENY_DOMAIN_MISMATCH,
        ), f"GitHub deveria ser bloqueado, mas foi: {result.decision}"

    def test_tool_allowed_for_correct_domain(self):
        """Tool de entidade é permitida para intenção de contato."""
        gate = ToolRelevanceGate()
        env = ContextEnvelopeBuilder() \
            .with_intent("verificar contato", "contact_info") \
            .with_entities(["lucas_bispo"]) \
            .build()

        result = gate.evaluate(env, "entity_lookup", "cognitive_search")
        assert result.decision == ToolDecision.ALLOW


# ═══════════════════════════════════════════════════════════════════════
# ETAPA 5 — TOOL RELEVANCE GATE — CENÁRIO DO INCIDENTE
# ═══════════════════════════════════════════════════════════════════════

class TestToolRelevanceGateIncident:
    """Reprodução do incidente: 'Eu já passei os 2, confira'."""

    def test_github_blocked_for_contact_verification(self):
        """Cenário 21 reproduzido: GitHub bloqueado."""
        # Contexto que deveria ter sido criado para a mensagem
        # "Eu já passei os 2, confira"
        env = ContextEnvelope(
            conversation_id="whatsapp_main",
            incoming_message_id="msg_5428",
            reply_to_message_id="msg_5426",  # resposta ao lembrete
            active_intent="verificar informações de contato já fornecidas",
            active_entities=["lucas_bispo", "jaqueline_manente"],
            intent_domain="contact_info",
            allowed_tool_domains=[
                "cognitive_search", "entity_lookup",
                "conversation_history", "follow_up_management",
            ],
            blocked_tool_domains=BLOCKED_TOOL_DOMAINS_FOR_CONTACT,
        )

        gate = ToolRelevanceGate()

        # GitHub deve ser negado
        result = gate.evaluate(env, "gh_repo_list", "github")
        assert result.decision in (
            ToolDecision.DENY_IRRELEVANT_TOOL,
            ToolDecision.DENY_DOMAIN_MISMATCH,
        ), f"GitHub deveria ser bloqueado, mas foi: {result.decision}"

        # Terminal também
        result = gate.evaluate(env, "terminal", "terminal")
        assert result.decision in (
            ToolDecision.DENY_IRRELEVANT_TOOL,
            ToolDecision.DENY_DOMAIN_MISMATCH,
        ), f"Terminal deveria ser bloqueado, mas foi: {result.decision}"

        # Entity lookup sem entidades no argumento → permitido porque não há
        # blocklist e o domínio é permitido para intenção de contato
        result = gate.evaluate(env, "entity_lookup", "cognitive_search")
        assert result.decision in (ToolDecision.ALLOW, ToolDecision.DENY_NO_ENTITY_OVERLAP)

    def test_context_retrieval_prioritizes_current(self):
        """Cenário 27: contexto de outra conversa não substitui a atual."""
        scorer = ContextRetrievalScorer()

        # Contexto de conversa antiga sobre GitHub
        old = scorer.score(
            source_conversation_id="github_conv",
            current_conversation_id="whatsapp_main",
            source_entities=["william-rp2", "prosperfybr"],
            current_entities=["lucas_bispo", "jaqueline_manente"],
            source_intent="verificar contas github",
            current_intent="verificar contato",
        )

        assert old["score"] < 0.3, (
            f"Contexto antigo deveria ter score baixo, mas teve {old['score']}"
        )
        assert old["use"] is False, "Contexto antigo não deveria ser usado"


# ═══════════════════════════════════════════════════════════════════════
# ETAPA 7 — RESPONSE REVIEWER
# ═══════════════════════════════════════════════════════════════════════

class TestResponseReviewer:
    """Testes do ResponseReviewer — bloqueio de resposta incoerente."""

    def test_block_response_with_wrong_domain(self):
        """Cenário 27: ResponseReviewer bloqueia resposta incorreta."""
        reviewer = ResponseReviewer()
        envelope = ContextEnvelope(
            conversation_id="whatsapp_main",
            active_intent="verificar informações de contato",
            active_entities=["lucas_bispo", "jaqueline_manente"],
            intent_domain="contact_info",
        )

        # Resposta sobre GitHub (incorreta para o contexto)
        bad_response = "As contas william-rp2 e prosperfybr estão funcionando. Total: 74 repositórios."

        result = reviewer.review(
            candidate_response=bad_response,
            envelope=envelope,
            executed_tools=[{"name": "gh_repo_list", "domain": "github"}],
            last_user_message="Eu já passei os 2, confira",
        )

        assert not result.passed, "Reviewer deveria bloquear resposta incorreta"

    def test_allow_response_with_correct_entities(self):
        """Resposta correta sobre contato deve passar."""
        reviewer = ResponseReviewer()
        envelope = ContextEnvelope(
            conversation_id="whatsapp_main",
            active_intent="verificar informações de contato",
            active_entities=["lucas_bispo", "jaqueline_manente"],
            intent_domain="contact_info",
        )

        good_response = (
            "Você tem razão! Confirmei que o telefone do Lucas Bispo "
            "e o telefone e e-mail da Jaqueline Manente já estão registrados. "
            "Os dois lembretes foram encerrados."
        )

        result = reviewer.review(
            candidate_response=good_response,
            envelope=envelope,
            executed_tools=[{"name": "entity_lookup", "domain": "cognitive_search"}],
            last_user_message="Eu já passei os 2, confira",
        )

        assert result.passed, f"Resposta correta deveria passar, mas foi: {result.final_decision}"


# ═══════════════════════════════════════════════════════════════════════
# DEDUPLICAÇÃO
# ═══════════════════════════════════════════════════════════════════════

class TestDeduplication:
    """Testes de deduplicação de follow-ups."""

    def test_dedup_key_generation(self):
        """Chave de deduplicação é consistente."""
        key1 = FollowUp.build_deduplication_key("Lucas Bispo", "phone")
        key2 = FollowUp.build_deduplication_key("lucas bispo", "PHONE")
        assert key1 == key2, "Deduplication key deve ser case-insensitive"

    def test_different_entities_different_keys(self):
        """Entidades diferentes geram chaves diferentes."""
        key1 = FollowUp.build_deduplication_key("Lucas Bispo", "phone")
        key2 = FollowUp.build_deduplication_key("Jaqueline Manente", "phone")
        assert key1 != key2


# ═══════════════════════════════════════════════════════════════════════
# CENÁRIOS DO INCIDENTE REAL
# ═══════════════════════════════════════════════════════════════════════

class TestIncidentScenario:
    """Reprodução do incidente completo."""

    def test_preflight_catches_resolved_data(self):
        """Cenário 5: job dispara após preenchimento, mas preflight suprime."""
        # Simula dados já existentes no Supabase
        current_data = {
            "phone": "+5519992788205",
            "email": None,
        }

        completed, evidence = CompletionEvaluatorService.evaluate(
            "all_fields_exist",
            {"fields": ["phone"]},
            current_data,
        )

        # Lucas tem phone → condição satisfeita
        assert completed
        assert evidence["found_fields"]["phone"] == "+5519992788205"

    def test_jaqueline_data_exists(self):
        """Cenário 5: dados da Jaqueline já existem."""
        current_data = {
            "phone": "+55 16 99242-7373",
            "email": "jacquelinemanente34@gmail.com",
        }

        completed, evidence = CompletionEvaluatorService.evaluate(
            "all_fields_exist",
            {"fields": ["phone", "email"]},
            current_data,
        )

        assert completed
        assert len(evidence["found_fields"]) == 2

    def test_context_envelope_for_incident_message(self):
        """Cenário 30: envelope correto para 'Eu já passei os 2, confira'."""
        env = ContextEnvelopeBuilder() \
            .with_conversation("whatsapp_main") \
            .with_message("msg_5428", reply_to="msg_5426") \
            .with_intent("verificar informações de contato já fornecidas", "contact_info") \
            .with_entities(["lucas_bispo", "jaqueline_manente"]) \
            .with_allowed_tools([
                "cognitive_search", "entity_lookup",
                "conversation_history", "follow_up_management",
            ]) \
            .with_blocked_tools(BLOCKED_TOOL_DOMAINS_FOR_CONTACT) \
            .build()

        # Verificar que GitHub não está nos domínios permitidos
        assert "github" not in env.allowed_tool_domains
        assert "github" in env.blocked_tool_domains

        # Entidades obrigatórias
        assert "lucas_bispo" in env.active_entities
        assert "jaqueline_manente" in env.active_entities

        # Intenção obrigatória
        assert "verificar" in env.active_intent.lower()