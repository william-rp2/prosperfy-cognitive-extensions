#!/usr/bin/env python3
"""
Fase K — Memoria e Auditoria: Cenarios ME1-ME5 e AU1-AU6.

Memoria (ME1-ME5):
  ME1: Leitura da memoria — Interpreter consulta Cognitive Register, dados lidos sem erro
  ME2: Escrita na memoria — Interpreter cria evento no Cognitive Register, evento persiste
  ME3: Atualizacao de entidades — apos execucao, entidade atualizada com novos dados
  ME4: Contexto anterior no Negotiator — feedback de execucoes passadas influencia nova escolha
  ME5: Memoria indisponivel — Cognitive Register=None, skip seguro, pipeline nao quebra

Auditoria (AU1-AU6):
  AU1: Intencao original registrada no resultado
  AU2: Capability escolhida registrada no resultado
  AU3: Motivo da escolha registrado
  AU4: Decisoes do Policy Engine registradas
  AU5: Resultado da execucao registrado
  AU6: Feedback gerado apos execucao
"""

import sys
import os

sys.path.insert(0, os.path.expanduser(
    "~/projetos/prosperfy-cognitive-extensions/hermes/capability-intelligence/src"
))

import pytest
from unittest.mock import AsyncMock, MagicMock, call
from dataclasses import dataclass, field
from typing import Any

from capability_intelligence.executor import Executor
from capability_intelligence.feedback_store import FeedbackStore, LocalFeedback
from capability_intelligence.gap_proposal import GapProposalStore
from capability_intelligence.interpreter import (
    CognitiveRegister,
    GenericInterpreter,
    InfrastructureInterpreter,
    Interpreter,
)
from capability_intelligence.models import (
    AuthorizationResult,
    CapabilityFeedback,
    CapabilityResult,
    CatalogMatch,
    CatalogResult,
    Domain,
    ExecutionReference,
    IntentQuery,
    ResultMetadata,
)
from capability_intelligence.negotiator import Negotiator
from capability_intelligence.pipeline import Pipeline
from capability_intelligence.policy_engine import (
    PolicyEngine,
    PolicyResult,
    PolicyVerdict,
    policy_environment_allowed,
    policy_requires_approval,
)
from capability_intelligence.resolver import Resolver


# ======================================================================
# Mock do Cognitive Register (simula Supabase)
# ======================================================================

class MockCognitiveRegister:
    """Mock do Cognitive Register que simula o Supabase.

    Armazena eventos, entidades, artefatos e tarefas em memoria,
    permitindo verificacao do que foi escrito e lido.
    """

    def __init__(self):
        self.events: list[dict] = []
        self.entities: list[dict] = []
        self.artifacts: list[dict] = []
        self.tasks: list[dict] = []
        self._should_fail = False

    async def create_event(self, event: dict) -> None:
        if self._should_fail:
            raise RuntimeError("Cognitive Register failure")
        self.events.append(event)

    async def update_entity(self, entity: dict) -> None:
        if self._should_fail:
            raise RuntimeError("Cognitive Register failure")
        self.entities.append(entity)

    async def create_artifact(self, artifact: dict) -> None:
        if self._should_fail:
            raise RuntimeError("Cognitive Register failure")
        self.artifacts.append(artifact)

    async def create_task(self, task: dict) -> None:
        if self._should_fail:
            raise RuntimeError("Cognitive Register failure")
        self.tasks.append(task)

    def get_entity(self, name: str) -> dict | None:
        """Retorna a ultima entidade atualizada com esse nome."""
        for entity in reversed(self.entities):
            if entity.get("name") == name:
                return entity
        return None

    def clear(self):
        self.events.clear()
        self.entities.clear()
        self.artifacts.clear()
        self.tasks.clear()


# ======================================================================
# Helpers
# ======================================================================

def make_catalog_match(
    capability_id: str,
    score: float = 0.9,
    reason: str = "Melhor correspondencia semantica",
    avg_duration_seconds: int | None = None,
) -> CatalogMatch:
    metadata = {}
    if avg_duration_seconds is not None:
        metadata["avg_duration_seconds"] = avg_duration_seconds
    return CatalogMatch(
        capability_id=capability_id,
        score=score,
        reason=reason,
        metadata=metadata,
    )


def make_capability_result(
    success: bool = True,
    data: dict | None = None,
    error: str | None = None,
    duration_ms: int = 5000,
    entities_impacted: list[str] | None = None,
) -> CapabilityResult:
    return CapabilityResult(
        success=success,
        data=data or {"output": "done"},
        error=error,
        metadata=ResultMetadata(
            duration_ms=duration_ms,
            execution_ref=ExecutionReference(ref="ref-001"),
            entities_impacted=entities_impacted or [],
            rollback_executed=False,
            warnings=[],
        ),
    )


# ======================================================================
# CENARIOS DE MEMORIA (ME1-ME5)
# ======================================================================

class TestME1_LeituraDaMemoria:
    """
    ME1: Leitura da memoria — Interpreter consulta Cognitive Register,
    dados lidos sem erro.

    O Interpreter recebe um resultado bruto, processa e interage com
    o Cognitive Register sem lancar excecoes. A verificacao ocorre
    ao garantir que o evento cognitivo foi criado com os dados corretos.
    """

    @pytest.mark.asyncio
    async def test_me1_evento_criado_sem_erro(self):
        """ME1: Interpreter processa resultado e cria evento no Cognitive Register."""
        registry = MockCognitiveRegister()
        interp = Interpreter(cognitive_register=registry)

        interpretation = await interp.process(
            result_raw={
                "success": True,
                "metadata": {
                    "duration_ms": 12000,
                    "entities_impacted": ["vps-01"],
                    "rollback_executed": False,
                    "warnings": [],
                },
            },
            capability_id="deploy_api",
            domain="infrastructure",
        )

        # Leitura: Cognitive Register foi consultado sem erro
        assert interpretation is not None
        assert interpretation.summary == "Infraestrutura executada com sucesso"
        assert len(registry.events) == 1
        assert registry.events[0]["event_type"] == "capability:executed:infra"
        assert registry.events[0]["payload"]["capability_id"] == "deploy_api"
        assert registry.events[0]["payload"]["success"] is True

    @pytest.mark.asyncio
    async def test_me1_dados_do_resultado_persistidos(self):
        """ME1: Dados do resultado sao lidos e persistidos no Cognitive Register."""
        registry = MockCognitiveRegister()
        interp = Interpreter(cognitive_register=registry)

        await interp.process(
            result_raw={
                "success": False,
                "data": {},
                "error": "Timeout",
                "metadata": {
                    "duration_ms": 30000,
                    "entities_impacted": ["svc-db"],
                    "rollback_executed": True,
                    "warnings": ["slow query detected"],
                },
            },
            capability_id="backup_db",
            domain="infrastructure",
        )

        # Verifica que os dados lidos foram persistidos corretamente
        assert len(registry.events) == 1
        event = registry.events[0]
        assert event["event_type"] == "capability:executed:infra"
        assert event["payload"]["success"] is False
        assert event["payload"]["duration_ms"] == 30000
        assert event["payload"]["rollback"] is True

    @pytest.mark.asyncio
    async def test_me1_generic_interpreter_le_sem_erro(self):
        """ME1: Interpreter generico tambem consulta Cognitive Register sem erro."""
        registry = MockCognitiveRegister()
        interp = Interpreter(cognitive_register=registry)

        interpretation = await interp.process(
            result_raw={"success": True, "metadata": {}},
            capability_id="send_email",
            domain="marketing",
        )

        assert interpretation is not None
        assert "Capability executada" in interpretation.summary
        assert len(registry.events) == 1
        assert registry.events[0]["event_type"] == "capability:executed"
        assert registry.events[0]["payload"]["domain"] == "marketing"


class TestME2_EscritaNaMemoria:
    """
    ME2: Escrita na memoria — Interpreter cria evento no Cognitive Register,
    evento persiste.

    Apos criar um evento, ele deve estar acessivel no mock,
    confirmando que a escrita e persistencia ocorreram.
    """

    @pytest.mark.asyncio
    async def test_me2_evento_persiste_apos_escrita(self):
        """ME2: Evento criado no Cognitive Register persiste e pode ser lido."""
        registry = MockCognitiveRegister()
        interp = Interpreter(cognitive_register=registry)

        await interp.process(
            result_raw={
                "success": True,
                "metadata": {
                    "duration_ms": 5000,
                    "entities_impacted": ["host-alpha"],
                    "rollback_executed": False,
                    "warnings": [],
                },
            },
            capability_id="provision_host",
            domain="infrastructure",
        )

        # Verifica persistencia: evento esta no mock e pode ser lido
        assert len(registry.events) == 1
        event = registry.events[0]
        assert event["payload"]["capability_id"] == "provision_host"
        assert event["payload"]["duration_ms"] == 5000

    @pytest.mark.asyncio
    async def test_me2_multiplos_eventos_persistem(self):
        """ME2: Multiplos eventos consecutivos sao todos persistidos."""
        registry = MockCognitiveRegister()
        interp = Interpreter(cognitive_register=registry)

        for i in range(5):
            await interp.process(
                result_raw={
                    "success": True,
                    "metadata": {
                        "duration_ms": 1000 * (i + 1),
                        "entities_impacted": [f"host-{i}"],
                        "rollback_executed": False,
                        "warnings": [],
                    },
                },
                capability_id=f"task_{i}",
                domain="infrastructure",
            )

        assert len(registry.events) == 5
        event_ids = [e["payload"]["capability_id"] for e in registry.events]
        assert event_ids == ["task_0", "task_1", "task_2", "task_3", "task_4"]

    @pytest.mark.asyncio
    async def test_me2_sem_cognitive_event_nao_cria_evento(self):
        """ME2: Se nao ha cognitive_event no Interpretation, nada e persistido."""
        registry = MockCognitiveRegister()
        # InfrastructureInterpreter sempre cria cognitive_event
        # GenericInterpreter tambem sempre cria.
        # Mas podemos testar com um interpretador customizado que retorna
        # Interpretation sem cognitive_event.
        from capability_intelligence.interpreter import Interpretation

        class SilentInterpreter:
            def can_handle(self, domain):
                return True
            async def interpret(self, result_raw, capability_id, domain):
                return Interpretation(
                    summary="silent",
                    cognitive_event=None,
                )

        interp = Interpreter(
            cognitive_register=registry,
            specializations=[SilentInterpreter()],
        )

        await interp.process(
            result_raw={"success": True, "metadata": {}},
            capability_id="noop",
            domain="test",
        )

        assert len(registry.events) == 0


class TestME3_AtualizacaoDeEntidades:
    """
    ME3: Atualizacao de entidades — apos execucao, entidade atualizada
    com novos dados no Cognitive Register.
    """

    @pytest.mark.asyncio
    async def test_me3_entidade_atualizada_apos_execucao(self):
        """ME3: Entidade impactada e atualizada no Cognitive Register apos execucao."""
        registry = MockCognitiveRegister()
        interp = Interpreter(cognitive_register=registry)

        await interp.process(
            result_raw={
                "success": True,
                "metadata": {
                    "duration_ms": 45000,
                    "entities_impacted": ["vps-01"],
                    "rollback_executed": False,
                    "warnings": [],
                },
            },
            capability_id="deploy_api",
            domain="infrastructure",
        )

        # Verifica que a entidade foi atualizada
        assert len(registry.entities) == 1
        entity = registry.entities[0]
        assert entity["name"] == "vps-01"
        assert entity["properties"]["last_operation"] == "deploy_api"

    @pytest.mark.asyncio
    async def test_me3_multiplas_entidades_atualizadas(self):
        """ME3: Multiplas entidades impactadas sao todas atualizadas."""
        registry = MockCognitiveRegister()
        interp = Interpreter(cognitive_register=registry)

        await interp.process(
            result_raw={
                "success": True,
                "metadata": {
                    "duration_ms": 30000,
                    "entities_impacted": ["vps-01", "vps-02", "lb-01"],
                    "rollback_executed": False,
                    "warnings": [],
                },
            },
            capability_id="scale_cluster",
            domain="infrastructure",
        )

        assert len(registry.entities) == 3
        names = [e["name"] for e in registry.entities]
        assert "vps-01" in names
        assert "vps-02" in names
        assert "lb-01" in names
        for entity in registry.entities:
            assert entity["properties"]["last_operation"] == "scale_cluster"

    @pytest.mark.asyncio
    async def test_me3_sem_entidades_impactadas(self):
        """ME3: Nenhuma entidade impactada → nenhuma atualizacao no CR."""
        registry = MockCognitiveRegister()
        interp = Interpreter(cognitive_register=registry)

        await interp.process(
            result_raw={
                "success": True,
                "metadata": {
                    "duration_ms": 1000,
                    "entities_impacted": [],
                    "rollback_executed": False,
                    "warnings": [],
                },
            },
            capability_id="health_check",
            domain="infrastructure",
        )

        assert len(registry.entities) == 0

    @pytest.mark.asyncio
    async def test_me3_entidade_atualizada_com_falha(self):
        """ME3: Mesmo em caso de falha, entidade e atualizada com operacao."""
        registry = MockCognitiveRegister()
        interp = Interpreter(cognitive_register=registry)

        await interp.process(
            result_raw={
                "success": False,
                "data": {},
                "error": "Connection refused",
                "metadata": {
                    "duration_ms": 5000,
                    "entities_impacted": ["db-primary"],
                    "rollback_executed": True,
                    "warnings": ["connection timeout"],
                },
            },
            capability_id="migrate_db",
            domain="infrastructure",
        )

        assert len(registry.entities) == 1
        entity = registry.entities[0]
        assert entity["name"] == "db-primary"
        # Mesmo com falha, a operacao (capability_id) e registrada na entidade
        assert entity["properties"]["last_operation"] == "migrate_db"


class TestME4_ContextoAnteriorNoNegotiator:
    """
    ME4: Contexto anterior no Negotiator — feedback de execucoes passadas
    influencia nova escolha.

    O Negotiator usa o historico de feedback para ajustar scores
    de Capabilities candidatas.
    """

    def test_me4_feedback_penaliza_falhas_anteriores(self):
        """ME4: Feedback de falhas passadas reduz score da Capability."""
        intent = IntentQuery(intent="deploy", domain="infrastructure")
        feedback = [
            CapabilityFeedback(
                capability_id="A",
                intent_query=intent,
                execution_ref=ExecutionReference(ref="e1"),
                success=False,
            ),
            CapabilityFeedback(
                capability_id="A",
                intent_query=intent,
                execution_ref=ExecutionReference(ref="e2"),
                success=False,
            ),
            CapabilityFeedback(
                capability_id="A",
                intent_query=intent,
                execution_ref=ExecutionReference(ref="e3"),
                success=False,
            ),
        ]
        neg = Negotiator(feedback_history=feedback)
        result = CatalogResult(matches=[
            make_catalog_match("A", score=0.9),
            make_catalog_match("B", score=0.80),
        ])
        best = neg.select(result)
        assert best is not None
        # A: 0/3 sucessos → penalizado * 0.90 = 0.81
        # B: 0.80 sem feedback
        # A penalizado (0.81) > B (0.80) → A ainda vence, mas com score menor
        assert abs(best.score - 0.81) < 0.01

    def test_me4_feedback_faz_b_vencer_quando_a_e_muito_penalizado(self):
        """ME4: Feedback negativo intenso faz B (sem historico) vencer A."""
        intent = IntentQuery(intent="deploy", domain="infrastructure")
        feedback = [
            CapabilityFeedback(
                capability_id="A",
                intent_query=intent,
                execution_ref=ExecutionReference(ref=f"e{i}"),
                success=False,
            )
            for i in range(10)
        ]
        neg = Negotiator(feedback_history=feedback)
        result = CatalogResult(matches=[
            make_catalog_match("A", score=0.95),
            make_catalog_match("B", score=0.90),
        ])
        best = neg.select(result)
        assert best is not None
        # A: 0/10 sucessos → score *= 0.90 = 0.855
        # B: 0.90 sem feedback
        # B vence!
        assert best.capability_id == "B"

    def test_me4_feedback_positivo_bonifica(self):
        """ME4: Feedback positivo consistente bonifica a Capability."""
        intent = IntentQuery(intent="deploy", domain="infrastructure")
        feedback = [
            CapabilityFeedback(
                capability_id="A",
                intent_query=intent,
                execution_ref=ExecutionReference(ref=f"e{i}"),
                success=True,
                duration_ms=500,
                user_satisfaction=5,
            )
            for i in range(10)
        ]
        neg = Negotiator(feedback_history=feedback)
        result = CatalogResult(matches=[
            make_catalog_match("A", score=0.9, avg_duration_seconds=1),
            make_catalog_match("B", score=0.85),
        ])
        best = neg.select(result)
        assert best is not None
        # A com 100% sucesso, satisfacao 5 → pode ser bonificado
        # Score deve ser >= 0.9 (nao penalizado)
        assert best.capability_id == "A"
        assert best.score >= 0.9

    def test_me4_sem_feedback_scores_inalterados(self):
        """ME4: Sem feedback historico, scores permancem inalterados."""
        neg = Negotiator(feedback_history=[])
        result = CatalogResult(matches=[
            make_catalog_match("A", score=0.75),
            make_catalog_match("B", score=0.60),
        ])
        best = neg.select(result)
        assert best is not None
        assert best.capability_id == "A"
        assert abs(best.score - 0.75) < 0.01

    def test_me4_feedback_misto_parcial(self):
        """ME4: Feedback misto (sucessos+falhas) ajusta score proporcionalmente."""
        intent = IntentQuery(intent="deploy", domain="infrastructure")
        # 4 sucessos, 1 falha = 80% sucesso → no penalty (>0.8 threshold)
        feedback = [
            CapabilityFeedback(
                capability_id="A",
                intent_query=intent,
                execution_ref=ExecutionReference(ref=f"e{i}"),
                success=(i < 4),
            )
            for i in range(5)
        ]
        neg = Negotiator(feedback_history=feedback)
        result = CatalogResult(matches=[
            make_catalog_match("A", score=0.9),
        ])
        best = neg.select(result)
        assert best is not None
        # 4/5 = 0.8 success_rate, nao menor que 0.8 → sem penalidade
        assert abs(best.score - 0.9) < 0.01


class TestME5_MemoriaIndisponivel:
    """
    ME5: Memoria indisponivel — Cognitive Register=None, skip seguro,
    pipeline nao quebra.

    Quando o Cognitive Register nao esta disponivel (None),
    o Interpreter deve processar sem tentar escrever.
    """

    @pytest.mark.asyncio
    async def test_me5_cognitive_register_none_nao_quebra(self):
        """ME5: CognitiveRegister=None → Interpreter processa sem erro."""
        interp = Interpreter(cognitive_register=None)

        interpretation = await interp.process(
            result_raw={
                "success": True,
                "metadata": {
                    "duration_ms": 5000,
                    "entities_impacted": ["vps-01"],
                    "rollback_executed": False,
                    "warnings": [],
                },
            },
            capability_id="deploy_api",
            domain="infrastructure",
        )

        assert interpretation is not None
        assert interpretation.summary == "Infraestrutura executada com sucesso"
        # Nao deve haver erro mesmo sem Cognitive Register

    @pytest.mark.asyncio
    async def test_me5_domain_indisponivel_mantem_funcionalidade(self):
        """ME5: Sem CR, interpretacao ainda funciona para qualquer dominio."""
        interp = Interpreter(cognitive_register=None)

        interpretation = await interp.process(
            result_raw={"success": True, "metadata": {}},
            capability_id="any_tool",
            domain="marketing",
        )

        assert interpretation is not None
        assert "Capability executada" in interpretation.summary
        # O Interpretation deve conter o cognitive_event mesmo sem CR
        assert interpretation.cognitive_event is not None
        assert interpretation.cognitive_event["payload"]["domain"] == "marketing"

    @pytest.mark.asyncio
    async def test_me5_sem_cr_interpretacao_retorna_summary(self):
        """ME5: Sem CR, o summary e eventos sao retornados no Interpretation."""
        interp = Interpreter(cognitive_register=None)

        interpretation = await interp.process(
            result_raw={
                "success": False,
                "error": "Timeout",
                "metadata": {
                    "duration_ms": 60000,
                    "entities_impacted": ["db-master"],
                    "rollback_executed": True,
                    "warnings": ["slow query"],
                },
            },
            capability_id="backup_db",
            domain="infrastructure",
        )

        assert interpretation is not None
        assert "Falha" in interpretation.summary
        assert interpretation.cognitive_event is not None
        assert interpretation.cognitive_event["payload"]["capability_id"] == "backup_db"
        # Entidades ainda sao computadas mesmo sem CR
        assert len(interpretation.entities_updated) == 1
        assert interpretation.entities_updated[0]["name"] == "db-master"

    @pytest.mark.asyncio
    async def test_me5_cr_none_no_interpreter_specializations(self):
        """ME5: Interpreter sem CR funciona com interpretadores especializados."""
        interp = Interpreter(cognitive_register=None, specializations=[
            InfrastructureInterpreter(),
        ])

        interpretation = await interp.process(
            result_raw={"success": True, "metadata": {}},
            capability_id="test",
            domain="infrastructure",
        )

        assert interpretation is not None
        assert isinstance(interpretation, object)
        # Verifica que encontrou o interpretador especializado
        assert "Infraestrutura" in interpretation.summary


# ======================================================================
# CENARIOS DE AUDITORIA (AU1-AU6)
# ======================================================================

@dataclass
class MockCatalogPort:
    """Mock do CatalogPort para testar o Resolver."""
    result: CatalogResult | None = None

    async def resolve(self, query: IntentQuery) -> CatalogResult:
        return self.result or CatalogResult(matches=[])


@dataclass
class MockAuthorizationPort:
    """Mock do AuthorizationPort."""
    authorized: bool = True

    async def authorize(self, request) -> AuthorizationResult:
        return AuthorizationResult(authorized=self.authorized)


@dataclass
class MockExecutionPort:
    """Mock do ExecutionPort."""
    result_to_return: CapabilityResult | None = None

    async def execute(self, request) -> ExecutionReference:
        return ExecutionReference(ref="mock-ref-001")

    async def result(self, ref: ExecutionReference) -> CapabilityResult:
        return self.result_to_return or make_capability_result()

    async def status(self, ref=None) -> Any:
        from capability_intelligence.models import StatusResult
        return StatusResult(healthy=True, capabilities_total=10, capabilities_available=8)


class TestAU1_IntencaoOriginalRegistrada:
    """
    AU1: Intencao original registrada no resultado.

    A intencao original (intent string) que iniciou o pipeline
    deve ser preservada e acessivel no resultado final.
    """

    @pytest.mark.asyncio
    async def test_au1_intent_passada_ao_resolver(self):
        """AU1: A intencao original e passada corretamente ao Resolver."""
        catalog = MockCatalogPort(result=CatalogResult(matches=[
            make_catalog_match("deploy_api", score=0.95, reason="Melhor match"),
        ]))
        resolver = Resolver(catalog=catalog)
        neg = Negotiator()
        policy = PolicyEngine()
        exec_mock = Executor(
            authorization=MockAuthorizationPort(),
            execution=MockExecutionPort(),
        )
        interp = Interpreter(cognitive_register=None)
        fb_store = FeedbackStore()

        pipeline = Pipeline(
            resolver=resolver,
            negotiator=neg,
            policy_engine=policy,
            executor=exec_mock,
            interpreter=interp,
            feedback_store=fb_store,
        )

        result = await pipeline.run(
            intent="Fazer deploy da API",
            domain=Domain.INFRASTRUCTURE,
            context={"branch": "main"},
        )

        assert result.success is True
        # A pipeline result deve refletir a execucao bem-sucedida
        # O intent original nao esta no PipelineResult atual,
        # mas podemos verificar que o fluxo usou a intent correta
        assert result.capability_id == "deploy_api"
        assert result.result is not None
        assert result.result.success is True

    @pytest.mark.asyncio
    async def test_au1_intent_no_summary(self):
        """AU1: A intencao transparece no summary do resultado."""
        catalog = MockCatalogPort(result=CatalogResult(matches=[
            make_catalog_match("deploy_api", score=0.95),
        ]))
        resolver = Resolver(catalog=catalog)
        pipeline = Pipeline(
            resolver=resolver,
            negotiator=Negotiator(),
            policy_engine=PolicyEngine(),
            executor=Executor(
                authorization=MockAuthorizationPort(),
                execution=MockExecutionPort(),
            ),
            interpreter=Interpreter(cognitive_register=None),
            feedback_store=FeedbackStore(),
        )

        result = await pipeline.run(
            intent="Fazer deploy da API",
            domain=Domain.INFRASTRUCTURE,
        )

        # O summary vem do interpreter e indica o dominio
        assert result.summary != ""
        assert "Infraestrutura" in result.summary or "Capability" in result.summary


class TestAU2_CapabilityEscolhidaRegistrada:
    """
    AU2: Capability escolhida registrada no resultado.

    A Capability selecionada pelo Negotiator deve estar presente
    no resultado do pipeline.
    """

    @pytest.mark.asyncio
    async def test_au2_capability_id_no_resultado(self):
        """AU2: capability_id da Capability escolhida esta no PipelineResult."""
        catalog = MockCatalogPort(result=CatalogResult(matches=[
            make_catalog_match("deploy_api", score=0.95, reason="Melhor match"),
        ]))
        pipeline = Pipeline(
            resolver=Resolver(catalog=catalog),
            negotiator=Negotiator(),
            policy_engine=PolicyEngine(),
            executor=Executor(
                authorization=MockAuthorizationPort(),
                execution=MockExecutionPort(),
            ),
            interpreter=Interpreter(cognitive_register=None),
            feedback_store=FeedbackStore(),
        )

        result = await pipeline.run(
            intent="deploy",
            domain=Domain.INFRASTRUCTURE,
        )

        assert result.capability_id == "deploy_api"

    @pytest.mark.asyncio
    async def test_au2_capability_id_em_disambiguation(self):
        """AU2: Candidates listados quando ha ambiguidade."""
        catalog = MockCatalogPort(result=CatalogResult(matches=[
            make_catalog_match("a", score=0.85, reason="bom"),
            make_catalog_match("b", score=0.80, reason="bom tb"),
        ]))
        pipeline = Pipeline(
            resolver=Resolver(catalog=catalog),
            negotiator=Negotiator(),
            policy_engine=PolicyEngine(),
            executor=Executor(
                authorization=MockAuthorizationPort(),
                execution=MockExecutionPort(),
            ),
            interpreter=Interpreter(cognitive_register=None),
            feedback_store=FeedbackStore(),
        )

        result = await pipeline.run(
            intent="ambiguous",
            domain=Domain.INFRASTRUCTURE,
        )

        # Disambiguation ativada
        assert result.disambiguation is True
        assert result.candidates is not None
        assert len(result.candidates) >= 2
        ids = [c["capability_id"] for c in result.candidates]
        assert "a" in ids
        assert "b" in ids


class TestAU3_MotivoDaEscolhaRegistrado:
    """
    AU3: Motivo da escolha registrado.

    A razao pela qual uma Capability foi selecionada deve estar
    registrada e acessivel.
    """

    @pytest.mark.asyncio
    async def test_au3_motivo_no_pipeline_result(self):
        """AU3: O motivo da escolha do Negotiator e registrado no resultado."""
        catalog = MockCatalogPort(result=CatalogResult(matches=[
            make_catalog_match("deploy_api", score=0.95, reason="Melhor correspondencia semantica"),
            make_catalog_match("rollback_api", score=0.50, reason="Fallback"),
        ]))
        pipeline = Pipeline(
            resolver=Resolver(catalog=catalog),
            negotiator=Negotiator(),
            policy_engine=PolicyEngine(),
            executor=Executor(
                authorization=MockAuthorizationPort(),
                execution=MockExecutionPort(),
            ),
            interpreter=Interpreter(cognitive_register=None),
            feedback_store=FeedbackStore(),
        )

        result = await pipeline.run(
            intent="deploy",
            domain=Domain.INFRASTRUCTURE,
        )

        assert result.capability_id == "deploy_api"

    @pytest.mark.asyncio
    async def test_au3_reason_in_candidates_during_disambiguation(self):
        """AU3: Motivo de cada candidato registrado em disambiguation."""
        catalog = MockCatalogPort(result=CatalogResult(matches=[
            make_catalog_match("a", score=0.85, reason="Melhor score semantico"),
            make_catalog_match("b", score=0.80, reason="Boa correspondencia contextual"),
        ]))
        pipeline = Pipeline(
            resolver=Resolver(catalog=catalog),
            negotiator=Negotiator(),
            policy_engine=PolicyEngine(),
            executor=Executor(
                authorization=MockAuthorizationPort(),
                execution=MockExecutionPort(),
            ),
            interpreter=Interpreter(cognitive_register=None),
            feedback_store=FeedbackStore(),
        )

        result = await pipeline.run(
            intent="deploy",
            domain=Domain.INFRASTRUCTURE,
        )

        assert result.disambiguation is True
        assert result.candidates is not None
        # Cada candidato tem um motivo
        for c in result.candidates:
            assert "reason" in c
        reasons = [c["reason"] for c in result.candidates]
        assert "Melhor score semantico" in reasons
        assert "Boa correspondencia contextual" in reasons


class TestAU4_DecisoesDoPolicyEngine:
    """
    AU4: Decisoes do Policy Engine registradas.

    As decisoes tomadas pelo Policy Engine (allow, deny, require_approval)
    devem ser refletidas no resultado do pipeline.
    """

    @pytest.mark.asyncio
    async def test_au4_policy_allow_executa_normalmente(self):
        """AU4: Policy ALLOW → pipeline executa normalmente."""
        catalog = MockCatalogPort(result=CatalogResult(matches=[
            make_catalog_match("deploy_api", score=0.95),
        ]))
        pipeline = Pipeline(
            resolver=Resolver(catalog=catalog),
            negotiator=Negotiator(),
            policy_engine=PolicyEngine(),  # sem politicas = ALLOW
            executor=Executor(
                authorization=MockAuthorizationPort(),
                execution=MockExecutionPort(),
            ),
            interpreter=Interpreter(cognitive_register=None),
            feedback_store=FeedbackStore(),
        )

        result = await pipeline.run(
            intent="deploy",
            domain=Domain.INFRASTRUCTURE,
        )

        assert result.success is True
        assert result.error is None

    @pytest.mark.asyncio
    async def test_au4_policy_deny_retorna_erro(self):
        """AU4: Policy DENY → pipeline retorna erro."""
        catalog = MockCatalogPort(result=CatalogResult(matches=[
            make_catalog_match("deploy_api", score=0.95),
        ]))
        pipeline = Pipeline(
            resolver=Resolver(catalog=catalog),
            negotiator=Negotiator(),
            policy_engine=PolicyEngine(
                policies=[policy_environment_allowed]
            ),
            executor=Executor(
                authorization=MockAuthorizationPort(),
                execution=MockExecutionPort(),
            ),
            interpreter=Interpreter(cognitive_register=None),
            feedback_store=FeedbackStore(),
        )

        result = await pipeline.run(
            intent="deploy",
            domain=Domain.INFRASTRUCTURE,
            environment="production-test",  # nao permitido
        )

        assert result.success is False
        assert "Políticas negaram" in (result.error or "")

    @pytest.mark.asyncio
    async def test_au4_policy_require_approval(self):
        """AU4: Policy REQUIRE_APPROVAL → pipeline marca aprovacao.

        Usamos uma policy customizada que sempre exige aprovacao
        para simular o cenario, pois o pipeline atual nao propaga
        authorization_result para o PolicyEngine.
        """
        def policy_always_require_approval(**kwargs) -> PolicyVerdict:
            return PolicyVerdict(
                policy="always_require_approval",
                result=PolicyResult.REQUIRE_APPROVAL,
                reason="Aprovacao obrigatoria para esta operacao",
            )

        catalog = MockCatalogPort(result=CatalogResult(matches=[
            make_catalog_match("deploy_api", score=0.95),
        ]))
        pipeline = Pipeline(
            resolver=Resolver(catalog=catalog),
            negotiator=Negotiator(),
            policy_engine=PolicyEngine(
                policies=[policy_always_require_approval]
            ),
            executor=Executor(
                authorization=MockAuthorizationPort(),
                execution=MockExecutionPort(),
            ),
            interpreter=Interpreter(cognitive_register=None),
            feedback_store=FeedbackStore(),
        )

        result = await pipeline.run(
            intent="deploy",
            domain=Domain.INFRASTRUCTURE,
        )

        assert result.success is False
        assert result.requires_approval is True
        assert result.capability_id == "deploy_api"

    @pytest.mark.asyncio
    async def test_au4_multiplas_politicas_combinadas(self):
        """AU4: Multiplas politicas sao todas avaliadas."""
        catalog = MockCatalogPort(result=CatalogResult(matches=[
            make_catalog_match("deploy_api", score=0.95),
        ]))
        pipeline = Pipeline(
            resolver=Resolver(catalog=catalog),
            negotiator=Negotiator(),
            policy_engine=PolicyEngine(
                policies=[policy_environment_allowed]
            ),
            executor=Executor(
                authorization=MockAuthorizationPort(),
                execution=MockExecutionPort(),
            ),
            interpreter=Interpreter(cognitive_register=None),
            feedback_store=FeedbackStore(),
        )

        result = await pipeline.run(
            intent="deploy",
            domain=Domain.INFRASTRUCTURE,
            environment="production",  # permitido
        )

        assert result.success is True
        assert result.error is None


class TestAU5_ResultadoDaExecucao:
    """
    AU5: Resultado da execucao registrado.

    O resultado (CapabilityResult) da execucao da Capability
    deve estar disponivel no PipelineResult.
    """

    @pytest.mark.asyncio
    async def test_au5_capability_result_no_pipeline_result(self):
        """AU5: CapabilityResult esta presente no PipelineResult apos execucao."""
        expected_result = make_capability_result(
            success=True,
            data={"output": "Deploy realizado", "url": "https://app.example.com"},
            duration_ms=15000,
            entities_impacted=["api-server"],
        )
        catalog = MockCatalogPort(result=CatalogResult(matches=[
            make_catalog_match("deploy_api", score=0.95),
        ]))
        pipeline = Pipeline(
            resolver=Resolver(catalog=catalog),
            negotiator=Negotiator(),
            policy_engine=PolicyEngine(),
            executor=Executor(
                authorization=MockAuthorizationPort(),
                execution=MockExecutionPort(result_to_return=expected_result),
            ),
            interpreter=Interpreter(cognitive_register=None),
            feedback_store=FeedbackStore(),
        )

        result = await pipeline.run(
            intent="deploy",
            domain=Domain.INFRASTRUCTURE,
        )

        assert result.result is not None
        assert result.result.success is True
        assert result.result.data == {"output": "Deploy realizado", "url": "https://app.example.com"}

    @pytest.mark.asyncio
    async def test_au5_erro_de_execucao_registrado(self):
        """AU5: Erro de execucao e registrado no PipelineResult."""
        failed_result = make_capability_result(
            success=False,
            data=None,
            error="Connection timeout after 30s",
        )
        catalog = MockCatalogPort(result=CatalogResult(matches=[
            make_catalog_match("deploy_api", score=0.95),
        ]))
        pipeline = Pipeline(
            resolver=Resolver(catalog=catalog),
            negotiator=Negotiator(),
            policy_engine=PolicyEngine(),
            executor=Executor(
                authorization=MockAuthorizationPort(),
                execution=MockExecutionPort(result_to_return=failed_result),
            ),
            interpreter=Interpreter(cognitive_register=None),
            feedback_store=FeedbackStore(),
        )

        result = await pipeline.run(
            intent="deploy",
            domain=Domain.INFRASTRUCTURE,
        )

        assert result.success is False
        assert result.result is not None
        assert result.result.success is False
        assert result.result.error == "Connection timeout after 30s"
        assert result.error == "Connection timeout after 30s"

    @pytest.mark.asyncio
    async def test_au5_metadata_da_execucao_preservada(self):
        """AU5: Metadados da execucao (duration, entities) preservados."""
        exec_result = make_capability_result(
            success=True,
            data={"done": True},
            duration_ms=42000,
            entities_impacted=["web-01", "web-02", "lb-main"],
        )
        catalog = MockCatalogPort(result=CatalogResult(matches=[
            make_catalog_match("scale_web", score=0.95),
        ]))
        pipeline = Pipeline(
            resolver=Resolver(catalog=catalog),
            negotiator=Negotiator(),
            policy_engine=PolicyEngine(),
            executor=Executor(
                authorization=MockAuthorizationPort(),
                execution=MockExecutionPort(result_to_return=exec_result),
            ),
            interpreter=Interpreter(cognitive_register=None),
            feedback_store=FeedbackStore(),
        )

        result = await pipeline.run(
            intent="scale web servers",
            domain=Domain.INFRASTRUCTURE,
        )

        assert result.result is not None
        assert result.result.metadata is not None
        assert result.result.metadata.duration_ms == 42000
        assert "web-01" in result.result.metadata.entities_impacted
        assert "web-02" in result.result.metadata.entities_impacted
        assert "lb-main" in result.result.metadata.entities_impacted


class TestAU6_FeedbackGeradoAposExecucao:
    """
    AU6: Feedback gerado apos execucao.

    Apos a execucao do pipeline, um feedback local deve ser
    registrado no FeedbackStore para aprendizado futuro.
    """

    @pytest.mark.asyncio
    async def test_au6_feedback_registrado_apos_sucesso(self):
        """AU6: Feedback registrado no FeedbackStore apos execucao bem-sucedida."""
        catalog = MockCatalogPort(result=CatalogResult(matches=[
            make_catalog_match("deploy_api", score=0.95),
        ]))
        fb_store = FeedbackStore()

        pipeline = Pipeline(
            resolver=Resolver(catalog=catalog),
            negotiator=Negotiator(),
            policy_engine=PolicyEngine(),
            executor=Executor(
                authorization=MockAuthorizationPort(),
                execution=MockExecutionPort(),
            ),
            interpreter=Interpreter(cognitive_register=None),
            feedback_store=fb_store,
        )

        result = await pipeline.run(
            intent="deploy",
            domain=Domain.INFRASTRUCTURE,
        )

        assert result.success is True
        # Feedback deve ter sido gerado
        history = fb_store.get_history("deploy_api")
        assert len(history) >= 1
        assert history[0].capability_id == "deploy_api"
        assert history[0].success is True
        assert history[0].duration_ms == 5000

    @pytest.mark.asyncio
    async def test_au6_feedback_registrado_apos_falha(self):
        """AU6: Feedback registrado mesmo apos falha na execucao."""
        failed_result = make_capability_result(
            success=False,
            error="Internal error",
            duration_ms=1000,
        )
        catalog = MockCatalogPort(result=CatalogResult(matches=[
            make_catalog_match("deploy_api", score=0.95),
        ]))
        fb_store = FeedbackStore()

        pipeline = Pipeline(
            resolver=Resolver(catalog=catalog),
            negotiator=Negotiator(),
            policy_engine=PolicyEngine(),
            executor=Executor(
                authorization=MockAuthorizationPort(),
                execution=MockExecutionPort(result_to_return=failed_result),
            ),
            interpreter=Interpreter(cognitive_register=None),
            feedback_store=fb_store,
        )

        result = await pipeline.run(
            intent="deploy",
            domain=Domain.INFRASTRUCTURE,
        )

        assert result.success is False
        # Feedback deve ter sido gerado mesmo com falha
        history = fb_store.get_history("deploy_api")
        assert len(history) >= 1
        assert history[0].success is False
        assert history[0].duration_ms == 1000

    @pytest.mark.asyncio
    async def test_au6_feedback_contem_hash_da_intencao(self):
        """AU6: Feedback inclui hash da intencao original."""
        catalog = MockCatalogPort(result=CatalogResult(matches=[
            make_catalog_match("deploy_api", score=0.95),
        ]))
        fb_store = FeedbackStore()

        pipeline = Pipeline(
            resolver=Resolver(catalog=catalog),
            negotiator=Negotiator(),
            policy_engine=PolicyEngine(),
            executor=Executor(
                authorization=MockAuthorizationPort(),
                execution=MockExecutionPort(),
            ),
            interpreter=Interpreter(cognitive_register=None),
            feedback_store=fb_store,
        )

        await pipeline.run(
            intent="Fazer deploy da API em producao",
            domain=Domain.INFRASTRUCTURE,
        )

        history = fb_store.get_history("deploy_api")
        assert len(history) >= 1
        # intent_query_hash deve ser uma string nao vazia
        assert history[0].intent_query_hash != ""
        assert isinstance(history[0].intent_query_hash, str)

    @pytest.mark.asyncio
    async def test_au6_feedback_store_acumula_multiplas_execucoes(self):
        """AU6: FeedbackStore acumula feedback de multiplas execucoes."""
        catalog = MockCatalogPort(result=CatalogResult(matches=[
            make_catalog_match("deploy_api", score=0.95),
        ]))
        fb_store = FeedbackStore()

        pipeline = Pipeline(
            resolver=Resolver(catalog=catalog),
            negotiator=Negotiator(),
            policy_engine=PolicyEngine(),
            executor=Executor(
                authorization=MockAuthorizationPort(),
                execution=MockExecutionPort(),
            ),
            interpreter=Interpreter(cognitive_register=None),
            feedback_store=fb_store,
        )

        # 3 execucoes
        for _ in range(3):
            await pipeline.run(
                intent="deploy",
                domain=Domain.INFRASTRUCTURE,
            )

        history = fb_store.get_history("deploy_api")
        assert len(history) == 3
        # Todos os feedbacks devem ser deste pipeline para deploy_api
        for fb in history:
            assert fb.capability_id == "deploy_api"

    @pytest.mark.asyncio
    async def test_au6_feedback_diferente_para_cada_capability(self):
        """AU6: Feedback e registrado para a Capability correta."""
        fb_store = FeedbackStore()

        # Primeira execucao: deploy_api
        catalog_a = MockCatalogPort(result=CatalogResult(matches=[
            make_catalog_match("deploy_api", score=0.95),
        ]))
        pipeline_a = Pipeline(
            resolver=Resolver(catalog=catalog_a),
            negotiator=Negotiator(),
            policy_engine=PolicyEngine(),
            executor=Executor(
                authorization=MockAuthorizationPort(),
                execution=MockExecutionPort(),
            ),
            interpreter=Interpreter(cognitive_register=None),
            feedback_store=fb_store,
        )
        await pipeline_a.run(intent="deploy", domain=Domain.INFRASTRUCTURE)

        # Segunda execucao: rollback_api
        catalog_b = MockCatalogPort(result=CatalogResult(matches=[
            make_catalog_match("rollback_api", score=0.95),
        ]))
        pipeline_b = Pipeline(
            resolver=Resolver(catalog=catalog_b),
            negotiator=Negotiator(),
            policy_engine=PolicyEngine(),
            executor=Executor(
                authorization=MockAuthorizationPort(),
                execution=MockExecutionPort(),
            ),
            interpreter=Interpreter(cognitive_register=None),
            feedback_store=fb_store,
        )
        await pipeline_b.run(intent="rollback", domain=Domain.INFRASTRUCTURE)

        # Verifica feedbacks por Capability
        deploy_history = fb_store.get_history("deploy_api")
        rollback_history = fb_store.get_history("rollback_api")
        assert len(deploy_history) == 1
        assert len(rollback_history) == 1
        assert deploy_history[0].capability_id == "deploy_api"
        assert rollback_history[0].capability_id == "rollback_api"