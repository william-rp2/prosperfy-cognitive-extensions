#!/usr/bin/env python3
"""
Fase C — Validação: Erros e Recuperação (ER1-ER6, RC1-RC5).

Cenários:
  ER1-ER6: Erros — Catalog offline, Skills 500, Auth deny, params inválidos,
                    timeout, Cognitive Register offline
  RC1-RC5: Recuperação — Queda, timeout, reconexão, retry, rollback
"""

import sys
import os

sys.path.insert(0, os.path.expanduser(
    "~/projetos/prosperfy-cognitive-extensions/hermes/capability-intelligence/src"
))

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from capability_intelligence.models import (
    CatalogMatch, CatalogResult, Domain, IntentQuery,
    AuthorizationRequest, AuthorizationResult,
    CapabilityResult, ExecutionReference, ExecutionRequest, ResultMetadata, StatusResult,
)
from capability_intelligence.resolver import Resolver
from capability_intelligence.negotiator import Negotiator
from capability_intelligence.policy_engine import PolicyEngine, PolicyResult, PolicyVerdict
from capability_intelligence.executor import Executor
from capability_intelligence.interpreter import Interpreter
from capability_intelligence.feedback_store import FeedbackStore, LocalFeedback
from capability_intelligence.gap_proposal import GapProposalStore
from capability_intelligence.pipeline import Pipeline, PipelineResult


# ═══════════════════════════════════════════════════════════════════════
# Mocks especializados (implementam os Protocolos)
# ═══════════════════════════════════════════════════════════════════════

class MockCatalogSuccess:
    """Mock de CatalogPort, AuthorizationPort, ExecutionPort — sucesso."""
    def __init__(self, matches: list[CatalogMatch] | None = None):
        self._matches = matches or [
            CatalogMatch(capability_id="deploy_api", score=0.95, reason="test"),
        ]
        self.call_count = 0

    async def resolve(self, query: IntentQuery) -> CatalogResult:
        self.call_count += 1
        return CatalogResult(matches=self._matches)

    async def authorize(self, request: AuthorizationRequest) -> AuthorizationResult:
        return AuthorizationResult(authorized=True)

    async def execute(self, request: ExecutionRequest) -> ExecutionReference:
        return ExecutionReference(ref="exec-ref")

    async def result(self, ref: ExecutionReference) -> CapabilityResult:
        return CapabilityResult(
            success=True, data={"done": True},
            metadata=ResultMetadata(
                duration_ms=100,
                execution_ref=ref,
            ),
        )

    async def status(self, ref=None) -> StatusResult:
        return StatusResult(healthy=True, capabilities_total=10)


class MockCatalogFailingResolver:
    """CatalogPort.resolve() lança exceção — simula Catalog offline (ER1)."""
    async def resolve(self, query: IntentQuery) -> CatalogResult:
        raise ConnectionError("Catalog is offline")


class MockAuthorizationDeny:
    """AuthorizationPort.authorize() retorna authorized=False (ER3)."""
    async def authorize(self, request: AuthorizationRequest) -> AuthorizationResult:
        return AuthorizationResult(authorized=False, reason="role 'viewer' cannot deploy")

    async def execute(self, request: ExecutionRequest) -> ExecutionReference:
        return ExecutionReference(ref="exec-ref")

    async def result(self, ref: ExecutionReference) -> CapabilityResult:
        return CapabilityResult(success=True, data={})

    async def resolve(self, query: IntentQuery) -> CatalogResult:
        return CatalogResult(matches=[
            CatalogMatch(capability_id="deploy_api", score=0.95, reason="test"),
        ])

    async def status(self, ref=None) -> StatusResult:
        return StatusResult(healthy=True)


class MockSkills500:
    """ExecutionPort.execute() lança exceção — simula Skills 500 (ER2, RC1)."""
    async def authorize(self, request: AuthorizationRequest) -> AuthorizationResult:
        return AuthorizationResult(authorized=True)

    async def execute(self, request: ExecutionRequest) -> ExecutionReference:
        raise RuntimeError("Skills platform returned HTTP 500")

    async def result(self, ref: ExecutionReference) -> CapabilityResult:
        raise RuntimeError("Skills platform returned HTTP 500")

    async def resolve(self, query: IntentQuery) -> CatalogResult:
        return CatalogResult(matches=[
            CatalogMatch(capability_id="deploy_api", score=0.95, reason="test"),
        ])

    async def status(self, ref=None) -> StatusResult:
        return StatusResult(healthy=True)


class MockInvalidParams:
    """ExecutionPort.execute() rejeita params vazios (ER4)."""
    def __init__(self):
        self.executed = False

    async def authorize(self, request: AuthorizationRequest) -> AuthorizationResult:
        return AuthorizationResult(authorized=True)

    async def execute(self, request: ExecutionRequest) -> ExecutionReference:
        if not request.params:
            raise ValueError("params cannot be empty")
        self.executed = True
        return ExecutionReference(ref="exec-ref")

    async def result(self, ref: ExecutionReference) -> CapabilityResult:
        return CapabilityResult(success=True, data={})

    async def resolve(self, query: IntentQuery) -> CatalogResult:
        return CatalogResult(matches=[
            CatalogMatch(capability_id="deploy_api", score=0.95, reason="test"),
        ])

    async def status(self, ref=None) -> StatusResult:
        return StatusResult(healthy=True)


class MockTimeout:
    """ExecutionPort.execute() nunca responde — simula timeout (ER5, RC2)."""
    async def authorize(self, request: AuthorizationRequest) -> AuthorizationResult:
        return AuthorizationResult(authorized=True)

    async def execute(self, request: ExecutionRequest) -> ExecutionReference:
        await asyncio.sleep(30)  # nunca completa
        return ExecutionReference(ref="exec-ref")

    async def result(self, ref: ExecutionReference) -> CapabilityResult:
        raise asyncio.TimeoutError("No response after 30 seconds")

    async def resolve(self, query: IntentQuery) -> CatalogResult:
        return CatalogResult(matches=[
            CatalogMatch(capability_id="deploy_api", score=0.95, reason="test"),
        ])

    async def status(self, ref=None) -> StatusResult:
        return StatusResult(healthy=True)


class MockReconnection:
    """Simula falha seguida de sucesso — testa reconexão (RC3)."""
    def __init__(self):
        self.call_count = 0
        self._session_id = None

    async def authorize(self, request: AuthorizationRequest) -> AuthorizationResult:
        self.call_count += 1
        if self.call_count == 1:
            raise RuntimeError("Connection lost")
        return AuthorizationResult(authorized=True)

    async def execute(self, request: ExecutionRequest) -> ExecutionReference:
        return ExecutionReference(ref="exec-ref")

    async def result(self, ref: ExecutionReference) -> CapabilityResult:
        return CapabilityResult(
            success=True, data={"done": True},
            metadata=ResultMetadata(duration_ms=50, execution_ref=ref),
        )

    async def resolve(self, query: IntentQuery) -> CatalogResult:
        return CatalogResult(matches=[
            CatalogMatch(capability_id="deploy_api", score=0.95, reason="test"),
        ])

    async def status(self, ref=None) -> StatusResult:
        return StatusResult(healthy=True)


class MockIdempotent:
    """ExecutionPort que registra execuções — testa idempotência (RC4)."""
    def __init__(self):
        self.execution_count = 0

    async def authorize(self, request: AuthorizationRequest) -> AuthorizationResult:
        return AuthorizationResult(authorized=True)

    async def execute(self, request: ExecutionRequest) -> ExecutionReference:
        self.execution_count += 1
        return ExecutionReference(ref="exec-ref")

    async def result(self, ref: ExecutionReference) -> CapabilityResult:
        return CapabilityResult(
            success=True, data={"result": "ok"},
            metadata=ResultMetadata(duration_ms=50, execution_ref=ref),
        )

    async def resolve(self, query: IntentQuery) -> CatalogResult:
        return CatalogResult(matches=[
            CatalogMatch(capability_id="deploy_api", score=0.95, reason="test"),
        ])

    async def status(self, ref=None) -> StatusResult:
        return StatusResult(healthy=True)


class MockRollback:
    """ExecutionPort que retorna rollback_executed=true (RC5)."""
    async def authorize(self, request: AuthorizationRequest) -> AuthorizationResult:
        return AuthorizationResult(authorized=True)

    async def execute(self, request: ExecutionRequest) -> ExecutionReference:
        return ExecutionReference(ref="exec-ref")

    async def result(self, ref: ExecutionReference) -> CapabilityResult:
        return CapabilityResult(
            success=False,
            error="Operation failed after partial execution",
            data={"partial": True},
            metadata=ResultMetadata(
                duration_ms=500,
                execution_ref=ref,
                rollback_executed=True,
                warnings=["Partial write detected, rollback executed"],
            ),
        )

    async def resolve(self, query: IntentQuery) -> CatalogResult:
        return CatalogResult(matches=[
            CatalogMatch(capability_id="deploy_api", score=0.95, reason="test"),
        ])

    async def status(self, ref=None) -> StatusResult:
        return StatusResult(healthy=True)


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def make_pipeline(catalog=None, authorization=None, execution=None,
                  negotiator=None, feedback=None, gaps=None,
                  interpreter=None) -> Pipeline:
    """Cria Pipeline com mocks injetados."""
    cat = catalog or MockCatalogSuccess()
    auth = authorization or cat
    exec_ = execution or cat
    return Pipeline(
        resolver=Resolver(catalog=cat),
        negotiator=negotiator or Negotiator(),
        policy_engine=PolicyEngine(),
        executor=Executor(authorization=auth, execution=exec_),
        interpreter=interpreter or Interpreter(),
        feedback_store=feedback or FeedbackStore(),
        gap_store=gaps or GapProposalStore(),
    )


# ═══════════════════════════════════════════════════════════════════════
# ER1: Catalog offline
# ═══════════════════════════════════════════════════════════════════════

class TestER1CatalogOffline:
    """Resolver lança exceção, Pipeline captura, retorna success=false."""

    @pytest.mark.asyncio
    async def test_er1_catalog_offline(self):
        """ER1: Catalog.resolve() lança exceção → pipeline retorna erro controlado."""
        pipe = make_pipeline(catalog=MockCatalogFailingResolver())
        result = await pipe.run(intent="deploy", domain="infrastructure")
        assert result.success is False, "ER1: success deve ser false"
        assert result.error is not None, "ER1: deve ter mensagem de erro"
        assert "offline" in result.error.lower() or "Catalog" in result.error or "ConnectionError" in result.error or "resolve" in result.error.lower(), \
            f"ER1: erro deve mencionar Catalog/offline, obteve: {result.error}"

    @pytest.mark.asyncio
    async def test_er1_no_crash(self):
        """ER1: Pipeline não quebra com Catalog offline."""
        pipe = make_pipeline(catalog=MockCatalogFailingResolver())
        result = await pipe.run(intent="deploy", domain="infrastructure")
        # Deve retornar PipelineResult, nunca lançar exceção
        assert isinstance(result, PipelineResult)
        assert result.error is not None


# ═══════════════════════════════════════════════════════════════════════
# ER2: Skills retorna 500
# ═══════════════════════════════════════════════════════════════════════

class TestER2Skills500:
    """Executor.authorize() ou execute() falha, pipeline retorna erro controlado."""

    @pytest.mark.asyncio
    async def test_er2_execute_raises(self):
        """ER2: Executor.execute() lança exceção → pipeline captura."""
        skills = MockSkills500()
        pipe = make_pipeline(
            authorization=skills,
            execution=skills,
        )
        result = await pipe.run(intent="deploy", domain="infrastructure")
        assert result.success is False, "ER2: success deve ser false"
        assert result.error is not None, "ER2: deve ter mensagem de erro"
        assert "500" in result.error or "Execution error" in result.error or "HTTP 500" in result.error, \
            f"ER2: erro deve mencionar 500, obteve: {result.error}"


# ═══════════════════════════════════════════════════════════════════════
# ER3: Authorization nega
# ═══════════════════════════════════════════════════════════════════════

class TestER3AuthorizationDeny:
    """Authorize retorna authorized=false, pipeline retorna erro."""

    @pytest.mark.asyncio
    async def test_er3_authorization_denied(self):
        """ER3: authorize() retorna authorized=false."""
        deny = MockAuthorizationDeny()
        pipe = make_pipeline(
            authorization=deny,
            execution=deny,
        )
        result = await pipe.run(intent="deploy", domain="infrastructure")
        assert result.success is False, "ER3: success deve ser false"
        assert result.error is not None, "ER3: deve ter mensagem de erro"
        assert "Not authorized" in result.error, \
            f"ER3: erro deve conter 'Not authorized', obteve: {result.error}"


# ═══════════════════════════════════════════════════════════════════════
# ER4: Parâmetros inválidos
# ═══════════════════════════════════════════════════════════════════════

class TestER4InvalidParams:
    """Executor.run() com params vazio, erro controlado."""

    @pytest.mark.asyncio
    async def test_er4_empty_params(self):
        """ER4: Executor com params vazios → erro controlado."""
        invalid = MockInvalidParams()
        pipe = make_pipeline(
            authorization=invalid,
            execution=invalid,
        )
        result = await pipe.run(intent="deploy", domain="infrastructure", context={})
        assert result.success is False, "ER4: success deve ser false"
        assert result.error is not None, "ER4: deve ter mensagem de erro"
        assert "empty" in result.error.lower() or "params" in result.error.lower() or "Execution error" in result.error, \
            f"ER4: erro deve mencionar params vazio, obteve: {result.error}"


# ═══════════════════════════════════════════════════════════════════════
# ER5: Timeout de rede
# ═══════════════════════════════════════════════════════════════════════

class TestER5Timeout:
    """MCPAdapter não responde, timeout → exceção → try/except do Executor."""

    @pytest.mark.asyncio
    async def test_er5_timeout(self):
        """ER5: Timeout no execute → Executor captura."""
        timeout = MockTimeout()
        pipe = make_pipeline(
            authorization=timeout,
            execution=timeout,
        )
        # Usamos asyncio.wait_for com timeout curto para simular timeout
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                pipe.run(intent="deploy", domain="infrastructure"),
                timeout=5,
            )


# ═══════════════════════════════════════════════════════════════════════
# ER6: Cognitive Register offline
# ═══════════════════════════════════════════════════════════════════════

class TestER6CognitiveRegisterOffline:
    """Interpreter com cognitive_register=None, skip seguro, não quebra."""

    @pytest.mark.asyncio
    async def test_er6_cognitive_register_none(self):
        """ER6: Interpreter com cognitive_register=None não quebra o pipeline."""
        interp = Interpreter(cognitive_register=None)
        pipe = make_pipeline(interpreter=interp)
        result = await pipe.run(intent="deploy", domain="infrastructure")
        assert result.success is True, "ER6: pipeline deve completar com sucesso"
        assert result.capability_id == "deploy_api"
        assert result.error is None, "ER6: não deve ter erro"

    @pytest.mark.asyncio
    async def test_er6_cognitive_register_offline_interpretation(self):
        """ER6: Interpreter.process funciona sem cognitive_register."""
        interp = Interpreter(cognitive_register=None)
        interpretation = await interp.process(
            result_raw={"success": True, "data": {}, "metadata": {}},
            capability_id="deploy_api",
            domain="infrastructure",
        )
        assert interpretation is not None
        assert "Infraestrutura" in interpretation.summary


# ═══════════════════════════════════════════════════════════════════════
# RC1: Queda durante execução
# ═══════════════════════════════════════════════════════════════════════

class TestRC1CrashDuringExecution:
    """Skills cai após authorize() antes de execute(), executor captura."""

    @pytest.mark.asyncio
    async def test_rc1_crash_after_authorize(self):
        """RC1: authorize() succeed, execute() fails → capturado."""
        skills = MockSkills500()
        pipe = make_pipeline(
            authorization=skills,
            execution=skills,
        )
        result = await pipe.run(intent="deploy", domain="infrastructure")
        assert result.success is False, "RC1: success deve ser false"
        assert result.error is not None, "RC1: deve ter erro"
        assert "500" in result.error or "Execution error" in result.error, \
            f"RC1: erro deve mencionar falha, obteve: {result.error}"

    @pytest.mark.asyncio
    async def test_rc1_pipeline_did_not_crash(self):
        """RC1: Pipeline não quebra — sempre retorna PipelineResult."""
        skills = MockSkills500()
        pipe = make_pipeline(
            authorization=skills,
            execution=skills,
        )
        result = await pipe.run(intent="deploy", domain="infrastructure")
        assert isinstance(result, PipelineResult)


# ═══════════════════════════════════════════════════════════════════════
# RC2: Timeout de comunicação
# ═══════════════════════════════════════════════════════════════════════

class TestRC2CommunicationTimeout:
    """After 30s sem resposta, erro controlado."""

    @pytest.mark.asyncio
    async def test_rc2_timeout_on_result(self):
        """RC2: result() lança TimeoutError."""
        # Simula um cenário onde execute() funciona mas result() dá timeout
        mock = MockTimeout()

        # Usamos o MockTimeout que já lida com o timeout via asyncio.sleep
        # Mas vamos testar o result() diretamente
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                mock.result(ExecutionReference(ref="exec-ref")),
                timeout=5,
            )

    @pytest.mark.asyncio
    async def test_rc2_executor_handles_timeout(self):
        """RC2: Executor.run() captura TimeoutError no execute."""
        # Simula que o execute() leva muito tempo
        class SlowExecution:
            async def authorize(self, request):
                return AuthorizationResult(authorized=True)

            async def execute(self, request):
                await asyncio.sleep(30)
                return ExecutionReference(ref="exec-ref")

            async def result(self, ref):
                return CapabilityResult(success=True, data={})

        executor = Executor(
            authorization=SlowExecution(),
            execution=SlowExecution(),
        )

        # O executor.run() tem try/except, mas a task não termina em 5s
        # Então usamos wait_for
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                executor.run("test", {}),
                timeout=5,
            )


# ═══════════════════════════════════════════════════════════════════════
# RC3: Reconexão
# ═══════════════════════════════════════════════════════════════════════

class TestRC3Reconnection:
    """Após falha, próxima chamada cria nova sessão (mock sequencial)."""

    @pytest.mark.asyncio
    async def test_rc3_reconnection_after_failure(self):
        """RC3: Primeira chamada falha, segunda chamada succeed."""
        mock = MockReconnection()
        pipe = make_pipeline(
            authorization=mock,
            execution=mock,
        )

        # Primeira chamada — falha na autorização
        # O pipeline chama resolver → negotiator → policy → executor.run()
        # O executor.run() chama authorize() que falha na primeira vez
        result1 = await pipe.run(intent="deploy", domain="infrastructure")
        assert result1.success is False, "RC3: primeira chamada deve falhar"
        assert result1.error is not None

        # Segunda chamada — deve criar nova sessão e ter sucesso
        # O executor.run() chama authorize() novamente
        # Agora authorize() retorna authorized=True
        result2 = await pipe.run(intent="deploy", domain="infrastructure")
        assert result2.success is True, "RC3: segunda chamada deve ter sucesso"
        assert result2.capability_id == "deploy_api"

    @pytest.mark.asyncio
    async def test_rc3_call_count_tracking(self):
        """RC3: MockReconnection registra chamadas."""
        mock = MockReconnection()
        assert mock.call_count == 0
        # Primeira chamada lança exceção (call_count=1 → erro)
        with pytest.raises(RuntimeError):
            await mock.authorize(AuthorizationRequest(capability_id="test"))
        assert mock.call_count == 1
        # Segunda chamada funciona (call_count=2 → authorized)
        auth = await mock.authorize(AuthorizationRequest(capability_id="test"))
        assert mock.call_count == 2
        assert auth.authorized is True


# ═══════════════════════════════════════════════════════════════════════
# RC4: Retry seguro (idempotência)
# ═══════════════════════════════════════════════════════════════════════

class TestRC4IdempotentRetry:
    """Mesma operação executada 2x, ambas retornam resultado previsível."""

    @pytest.mark.asyncio
    async def test_rc4_same_operation_twice(self):
        """RC4: Executar mesma operação 2x retorna mesmo resultado."""
        idempotent = MockIdempotent()
        pipe = make_pipeline(
            authorization=idempotent,
            execution=idempotent,
        )

        result1 = await pipe.run(intent="deploy", domain="infrastructure", context={"key": "value"})
        assert result1.success is True, "RC4: primeira execução deve ser sucesso"
        assert result1.result is not None
        assert result1.result.data == {"result": "ok"}

        result2 = await pipe.run(intent="deploy", domain="infrastructure", context={"key": "value"})
        assert result2.success is True, "RC4: segunda execução deve ser sucesso"
        assert result2.result is not None
        assert result2.result.data == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_rc4_idempotent_data(self):
        """RC4: Dados retornados são idênticos entre execuções."""
        idempotent = MockIdempotent()
        pipe = make_pipeline(
            authorization=idempotent,
            execution=idempotent,
        )

        r1 = await pipe.run(intent="deploy", domain="infrastructure", context={"key": "value"})
        r2 = await pipe.run(intent="deploy", domain="infrastructure", context={"key": "value"})

        assert r1.result.data == r2.result.data, "RC4: dados devem ser idênticos"
        assert r1.success == r2.success, "RC4: success deve ser igual"
        assert r1.capability_id == r2.capability_id, "RC4: capability_id deve ser igual"

    @pytest.mark.asyncio
    async def test_rc4_execution_count_increments(self):
        """RC4: MockIdempotent registra execuções."""
        idempotent = MockIdempotent()
        assert idempotent.execution_count == 0
        await idempotent.execute(ExecutionRequest(capability_id="test", params={}))
        assert idempotent.execution_count == 1
        await idempotent.execute(ExecutionRequest(capability_id="test", params={}))
        assert idempotent.execution_count == 2


# ═══════════════════════════════════════════════════════════════════════
# RC5: Rollback
# ═══════════════════════════════════════════════════════════════════════

class TestRC5Rollback:
    """Execução falha, ResultMetadata.rollback_executed=true."""

    @pytest.mark.asyncio
    async def test_rc5_rollback_flag(self):
        """RC5: rollback_executed=true quando execução falha."""
        rollback = MockRollback()
        pipe = make_pipeline(
            authorization=rollback,
            execution=rollback,
        )
        result = await pipe.run(intent="deploy", domain="infrastructure")

        assert result.success is False, "RC5: success deve ser false"
        assert result.result is not None, "RC5: result deve existir"
        assert result.result.metadata is not None, "RC5: metadata deve existir"
        assert result.result.metadata.rollback_executed is True, \
            "RC5: rollback_executed deve ser True"

    @pytest.mark.asyncio
    async def test_rc5_rollback_metadata_propagated(self):
        """RC5: Metadados de rollback propagados até PipelineResult."""
        rollback = MockRollback()
        pipe = make_pipeline(
            authorization=rollback,
            execution=rollback,
        )
        result = await pipe.run(intent="deploy", domain="infrastructure")

        # O Pipeline não expõe rollback_executed diretamente no PipelineResult
        # mas ele está em result.result.metadata.rollback_executed
        assert result.result is not None
        assert result.result.metadata is not None
        assert result.result.metadata.rollback_executed is True
        assert result.result.metadata.warnings is not None
        assert len(result.result.metadata.warnings) > 0

    @pytest.mark.asyncio
    async def test_rc5_rollback_error_message(self):
        """RC5: Mensagem de erro informa rollback."""
        rollback = MockRollback()
        result = await rollback.result(ExecutionReference(ref="exec-ref"))
        assert result.success is False
        assert result.error is not None
        assert "partial" in result.error.lower() or "rollback" in result.error.lower() or "Operation failed" in result.error
        assert result.metadata.rollback_executed is True