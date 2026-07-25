#!/usr/bin/env python3
"""
Fase D — Validacao Funcional: Autorizacao (A1-A8).

Cenarios:
  A1: observer em list_containers → ALLOW (operacao segura)
  A2: observer em deploy_evolution_api → DENY (requer operator)
  A3: operator em deploy_evolution_api em staging → ALLOW
  A4: operator em deploy_evolution_api em production → REQUIRE_APPROVAL
  A5: admin → qualquer acao → ALLOW
  A6: operator em delete_database → DENY (requer admin)
  A7: sem perfil (nao autenticado) → qualquer acao → DENY
  A8: admin em capability inexistente → erro sem mascarar autorizacao
"""

import sys
import os

sys.path.insert(0, os.path.expanduser(
    "~/projetos/prosperfy-cognitive-extensions/hermes/capability-intelligence/src"
))

import pytest

from capability_intelligence.models import (
    CatalogMatch, CatalogResult, Domain, IntentQuery,
    AuthorizationRequest, AuthorizationResult,
    CapabilityResult, ExecutionReference, ExecutionRequest, ResultMetadata, StatusResult,
)
from capability_intelligence.resolver import Resolver
from capability_intelligence.negotiator import Negotiator
from capability_intelligence.policy_engine import (
    PolicyEngine, PolicyResult, PolicyVerdict, policy_environment_allowed,
)
from capability_intelligence.executor import Executor
from capability_intelligence.interpreter import Interpreter
from capability_intelligence.feedback_store import FeedbackStore, LocalFeedback
from capability_intelligence.gap_proposal import GapProposalStore
from capability_intelligence.pipeline import Pipeline, PipelineResult


# ======================================================================
# Mocks de perfil de autorizacao (implementam AuthorizationPort)
# ======================================================================

class MockObserverProfile:
    """Perfil observer: so pode executar operacoes seguras (list_containers).
    deploy_evolution_api → DENY."""

    async def authorize(self, request: AuthorizationRequest) -> AuthorizationResult:
        if request.capability_id == "list_containers":
            return AuthorizationResult(authorized=True)
        return AuthorizationResult(
            authorized=False,
            reason=f"observer cannot execute '{request.capability_id}' (requires operator)",
        )


class MockOperatorProfile:
    """Perfil operator: pode executar deploy_evolution_api, mas nao delete_database."""

    async def authorize(self, request: AuthorizationRequest) -> AuthorizationResult:
        if request.capability_id == "delete_database":
            return AuthorizationResult(
                authorized=False,
                reason="operator cannot delete database (requires admin)",
            )
        return AuthorizationResult(authorized=True)


class MockAdminProfile:
    """Perfil admin: pode executar qualquer acao."""

    async def authorize(self, request: AuthorizationRequest) -> AuthorizationResult:
        return AuthorizationResult(authorized=True)


class MockNoProfile:
    """Sem perfil (nao autenticado): qualquer acao e negada."""

    async def authorize(self, request: AuthorizationRequest) -> AuthorizationResult:
        return AuthorizationResult(
            authorized=False,
            reason="unauthenticated: no profile assigned",
        )


# ======================================================================
# Mock de execucao (implementa ExecutionPort)
# ======================================================================

class MockExecutionSuccess:
    """ExecutionPort que sempre executa com sucesso."""

    async def execute(self, request: ExecutionRequest) -> ExecutionReference:
        return ExecutionReference(ref=f"exec-{request.capability_id}")

    async def result(self, ref: ExecutionReference) -> CapabilityResult:
        return CapabilityResult(
            success=True,
            data={"done": True, "ref": ref.ref},
            metadata=ResultMetadata(
                duration_ms=100,
                execution_ref=ref,
            ),
        )

    async def status(self, ref: ExecutionReference | None = None) -> StatusResult:
        return StatusResult(healthy=True, capabilities_total=10)


# ======================================================================
# Mock de Catalogo (implementa CatalogPort)
# ======================================================================

class MockCatalog:
    """CatalogPort que sempre retorna a Capability solicitada."""

    def __init__(self, capability_id: str = "deploy_api", score: float = 0.95):
        self._matches = [
            CatalogMatch(capability_id=capability_id, score=score, reason="test"),
        ]

    async def resolve(self, query: IntentQuery) -> CatalogResult:
        return CatalogResult(matches=self._matches)


class MockCatalogEmpty:
    """CatalogPort que retorna matches vazio — simula capability inexistente."""

    async def resolve(self, query: IntentQuery) -> CatalogResult:
        return CatalogResult(matches=[])

    async def authorize(self, request: AuthorizationRequest) -> AuthorizationResult:
        return AuthorizationResult(authorized=True)

    async def execute(self, request: ExecutionRequest) -> ExecutionReference:
        return ExecutionReference(ref="exec-ref")

    async def result(self, ref: ExecutionReference) -> CapabilityResult:
        return CapabilityResult(success=True, data={})

    async def status(self, ref: ExecutionReference | None = None) -> StatusResult:
        return StatusResult(healthy=True)


# ======================================================================
# Politica customizada para A4: production requer aprovacao
# ======================================================================

def policy_requires_approval_for_production(
    capability_id: str, environment: str, **kwargs
) -> PolicyVerdict:
    """Deploy em producao de evolution_api requer aprovacao."""
    if capability_id == "deploy_evolution_api" and environment == "production":
        return PolicyVerdict(
            policy="requires_approval",
            result=PolicyResult.REQUIRE_APPROVAL,
            reason="Production deployment requires explicit approval",
        )
    return PolicyVerdict(policy="requires_approval", result=PolicyResult.ALLOW)


# ======================================================================
# Helpers
# ======================================================================

def make_pipeline(
    catalog=None,
    authorization=None,
    execution=None,
    policies=None,
    gaps=None,
) -> Pipeline:
    """Cria Pipeline com mocks injetados."""
    cat = catalog or MockCatalog()
    auth = authorization or MockAdminProfile()
    exec_ = execution or MockExecutionSuccess()
    engine = PolicyEngine(policies=policies or [])

    return Pipeline(
        resolver=Resolver(catalog=cat),
        negotiator=Negotiator(),
        policy_engine=engine,
        executor=Executor(authorization=auth, execution=exec_),
        interpreter=Interpreter(),
        feedback_store=FeedbackStore(),
        gap_store=gaps or GapProposalStore(),
    )


# ======================================================================
# A1: observer em list_containers → ALLOW
# ======================================================================

class TestA1ObserverListContainers:
    """Observer pode executar operacoes seguras como list_containers."""

    @pytest.mark.asyncio
    async def test_a1_observer_list_containers_allowed(self):
        """A1: observer em list_containers → ALLOW."""
        catalog = MockCatalog(capability_id="list_containers")
        pipe = make_pipeline(
            catalog=catalog,
            authorization=MockObserverProfile(),
        )
        result = await pipe.run(
            intent="list containers",
            domain="infrastructure",
        )
        assert result.success is True, (
            f"A1: observer deve poder listar containers, obteve: "
            f"success={result.success}, error={result.error}"
        )
        assert result.capability_id == "list_containers"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_a1_observer_list_containers_not_denied(self):
        """A1: observer nao recebe erro de autorizacao em list_containers."""
        catalog = MockCatalog(capability_id="list_containers")
        pipe = make_pipeline(
            catalog=catalog,
            authorization=MockObserverProfile(),
        )
        result = await pipe.run(
            intent="list containers",
            domain="infrastructure",
        )
        assert result.success is True
        assert "Not authorized" not in (result.error or "")


# ======================================================================
# A2: observer em deploy_evolution_api → DENY
# ======================================================================

class TestA2ObserverDeployDenied:
    """Observer nao pode executar deploy_evolution_api."""

    @pytest.mark.asyncio
    async def test_a2_observer_deploy_denied(self):
        """A2: observer em deploy_evolution_api → DENY."""
        catalog = MockCatalog(capability_id="deploy_evolution_api")
        pipe = make_pipeline(
            catalog=catalog,
            authorization=MockObserverProfile(),
        )
        result = await pipe.run(
            intent="deploy evolution api",
            domain="infrastructure",
        )
        assert result.success is False, (
            f"A2: observer deve ser negado em deploy, obteve: "
            f"success={result.success}"
        )
        assert result.error is not None
        assert "Not authorized" in result.error, (
            f"A2: erro deve conter 'Not authorized', obteve: {result.error}"
        )

    @pytest.mark.asyncio
    async def test_a2_observer_deploy_reason(self):
        """A2: observer recebe motivo claro de negacao."""
        catalog = MockCatalog(capability_id="deploy_evolution_api")
        pipe = make_pipeline(
            catalog=catalog,
            authorization=MockObserverProfile(),
        )
        result = await pipe.run(
            intent="deploy evolution api",
            domain="infrastructure",
        )
        assert result.error is not None
        assert "observer" in result.error.lower(), (
            f"A2: motivo deve mencionar observer, obteve: {result.error}"
        )


# ======================================================================
# A3: operator em deploy_evolution_api em staging → ALLOW
# ======================================================================

class TestA3OperatorDeployStaging:
    """Operator pode deployar em staging."""

    @pytest.mark.asyncio
    async def test_a3_operator_deploy_staging_allowed(self):
        """A3: operator em deploy_evolution_api em staging → ALLOW."""
        catalog = MockCatalog(capability_id="deploy_evolution_api")
        pipe = make_pipeline(
            catalog=catalog,
            authorization=MockOperatorProfile(),
            policies=[policy_environment_allowed],
        )
        result = await pipe.run(
            intent="deploy evolution api",
            domain="infrastructure",
            environment="staging",
        )
        assert result.success is True, (
            f"A3: operator deve poder deployar em staging, obteve: "
            f"success={result.success}, error={result.error}"
        )
        assert result.capability_id == "deploy_evolution_api"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_a3_operator_deploy_staging_no_approval(self):
        """A3: staging nao requer aprovacao."""
        catalog = MockCatalog(capability_id="deploy_evolution_api")
        pipe = make_pipeline(
            catalog=catalog,
            authorization=MockOperatorProfile(),
            policies=[policy_environment_allowed],
        )
        result = await pipe.run(
            intent="deploy evolution api",
            domain="infrastructure",
            environment="staging",
        )
        assert result.requires_approval is False, (
            f"A3: staging nao deve requerer aprovacao, obteve: "
            f"requires_approval={result.requires_approval}"
        )


# ======================================================================
# A4: operator em deploy_evolution_api em production → REQUIRE_APPROVAL
# ======================================================================

class TestA4OperatorDeployProductionRequiresApproval:
    """Operator precisa de aprovacao para deploy em production."""

    @pytest.mark.asyncio
    async def test_a4_operator_deploy_production_requires_approval(self):
        """A4: operator em production → REQUIRE_APPROVAL."""
        catalog = MockCatalog(capability_id="deploy_evolution_api")
        pipe = make_pipeline(
            catalog=catalog,
            authorization=MockOperatorProfile(),
            policies=[
                policy_environment_allowed,
                policy_requires_approval_for_production,
            ],
        )
        result = await pipe.run(
            intent="deploy evolution api",
            domain="infrastructure",
            environment="production",
        )
        assert result.requires_approval is True, (
            f"A4: production deve requerer aprovacao, obteve: "
            f"requires_approval={result.requires_approval}"
        )
        assert result.success is False, (
            f"A4: success deve ser false quando requer aprovacao, "
            f"obteve: {result.success}"
        )
        assert result.capability_id == "deploy_evolution_api"

    @pytest.mark.asyncio
    async def test_a4_operator_deploy_production_not_executed(self):
        """A4: Capability nao e executada quando requer aprovacao."""
        catalog = MockCatalog(capability_id="deploy_evolution_api")
        pipe = make_pipeline(
            catalog=catalog,
            authorization=MockOperatorProfile(),
            policies=[
                policy_environment_allowed,
                policy_requires_approval_for_production,
            ],
        )
        result = await pipe.run(
            intent="deploy evolution api",
            domain="infrastructure",
            environment="production",
        )
        assert result.execution_ref is None, (
            f"A4: nao deve haver execution_ref quando requer aprovacao, "
            f"obteve: {result.execution_ref}"
        )


# ======================================================================
# A5: admin → qualquer acao → ALLOW
# ======================================================================

class TestA5AdminAnyAction:
    """Admin pode executar qualquer acao."""

    @pytest.mark.asyncio
    async def test_a5_admin_list_containers(self):
        """A5: admin pode list_containers."""
        catalog = MockCatalog(capability_id="list_containers")
        pipe = make_pipeline(
            catalog=catalog,
            authorization=MockAdminProfile(),
        )
        result = await pipe.run(
            intent="list containers",
            domain="infrastructure",
        )
        assert result.success is True, (
            f"A5: admin deve poder listar containers, obteve: "
            f"success={result.success}"
        )

    @pytest.mark.asyncio
    async def test_a5_admin_deploy_evolution_api(self):
        """A5: admin pode deploy_evolution_api."""
        catalog = MockCatalog(capability_id="deploy_evolution_api")
        pipe = make_pipeline(
            catalog=catalog,
            authorization=MockAdminProfile(),
        )
        result = await pipe.run(
            intent="deploy evolution api",
            domain="infrastructure",
        )
        assert result.success is True, (
            f"A5: admin deve poder deployar, obteve: "
            f"success={result.success}"
        )

    @pytest.mark.asyncio
    async def test_a5_admin_delete_database(self):
        """A5: admin pode delete_database."""
        catalog = MockCatalog(capability_id="delete_database")
        pipe = make_pipeline(
            catalog=catalog,
            authorization=MockAdminProfile(),
        )
        result = await pipe.run(
            intent="delete database",
            domain="infrastructure",
        )
        assert result.success is True, (
            f"A5: admin deve poder deletar database, obteve: "
            f"success={result.success}"
        )


# ======================================================================
# A6: operator em delete_database → DENY (requer admin)
# ======================================================================

class TestA6OperatorDeleteDatabaseDenied:
    """Operator nao pode deletar database (requer admin)."""

    @pytest.mark.asyncio
    async def test_a6_operator_delete_database_denied(self):
        """A6: operator em delete_database → DENY."""
        catalog = MockCatalog(capability_id="delete_database")
        pipe = make_pipeline(
            catalog=catalog,
            authorization=MockOperatorProfile(),
        )
        result = await pipe.run(
            intent="delete database",
            domain="infrastructure",
        )
        assert result.success is False, (
            f"A6: operator deve ser negado em delete_database, obteve: "
            f"success={result.success}"
        )
        assert result.error is not None
        assert "Not authorized" in result.error, (
            f"A6: erro deve conter 'Not authorized', obteve: {result.error}"
        )

    @pytest.mark.asyncio
    async def test_a6_operator_delete_database_reason(self):
        """A6: operator recebe motivo claro de negacao."""
        catalog = MockCatalog(capability_id="delete_database")
        pipe = make_pipeline(
            catalog=catalog,
            authorization=MockOperatorProfile(),
        )
        result = await pipe.run(
            intent="delete database",
            domain="infrastructure",
        )
        assert result.error is not None
        assert "admin" in result.error.lower(), (
            f"A6: motivo deve mencionar admin, obteve: {result.error}"
        )


# ======================================================================
# A7: sem perfil (nao autenticado) → qualquer acao → DENY
# ======================================================================

class TestA7NoProfileDenied:
    """Sem perfil (nao autenticado) nao pode executar nada."""

    @pytest.mark.asyncio
    async def test_a7_no_profile_list_containers(self):
        """A7: sem perfil nao pode list_containers."""
        catalog = MockCatalog(capability_id="list_containers")
        pipe = make_pipeline(
            catalog=catalog,
            authorization=MockNoProfile(),
        )
        result = await pipe.run(
            intent="list containers",
            domain="infrastructure",
        )
        assert result.success is False, (
            f"A7: sem perfil nao pode listar containers, obteve: "
            f"success={result.success}"
        )
        assert result.error is not None
        assert "Not authorized" in result.error, (
            f"A7: erro deve conter 'Not authorized', obteve: {result.error}"
        )

    @pytest.mark.asyncio
    async def test_a7_no_profile_deploy_evolution_api(self):
        """A7: sem perfil nao pode deploy_evolution_api."""
        catalog = MockCatalog(capability_id="deploy_evolution_api")
        pipe = make_pipeline(
            catalog=catalog,
            authorization=MockNoProfile(),
        )
        result = await pipe.run(
            intent="deploy evolution api",
            domain="infrastructure",
        )
        assert result.success is False
        assert result.error is not None
        assert "Not authorized" in result.error

    @pytest.mark.asyncio
    async def test_a7_no_profile_delete_database(self):
        """A7: sem perfil nao pode delete_database."""
        catalog = MockCatalog(capability_id="delete_database")
        pipe = make_pipeline(
            catalog=catalog,
            authorization=MockNoProfile(),
        )
        result = await pipe.run(
            intent="delete database",
            domain="infrastructure",
        )
        assert result.success is False
        assert result.error is not None
        assert "Not authorized" in result.error

    @pytest.mark.asyncio
    async def test_a7_no_profile_reason(self):
        """A7: sem perfil recebe motivo claro de negacao."""
        catalog = MockCatalog(capability_id="list_containers")
        pipe = make_pipeline(
            catalog=catalog,
            authorization=MockNoProfile(),
        )
        result = await pipe.run(
            intent="list containers",
            domain="infrastructure",
        )
        assert result.error is not None
        assert "unauthenticated" in result.error.lower() or "no profile" in result.error.lower() or "not authorized" in result.error.lower(), (
            f"A7: motivo deve indicar falta de autenticacao/perfil, obteve: {result.error}"
        )


# ======================================================================
# A8: Admin + Capability inexistente
# ======================================================================

class TestA8AdminInexistentCapability:
    """Admin executa capability inexistente — erro nao deve ser mascarado."""

    @pytest.mark.asyncio
    async def test_a8_capability_not_found(self):
        """A8: capability inexistente → erro controlado, nao bypass de seguranca."""
        cat = MockCatalogEmpty()
        pipe = make_pipeline(
            catalog=cat,
            authorization=cat,
        )
        result = await pipe.run(
            intent="nonexistent_capability_v2",
            domain="infrastructure",
        )
        assert result.error is not None, (
            "A8: deve retornar erro — capability nao existe"
        )
        assert "not authorized" not in result.error.lower(), (
            "A8: autorizacao nao deve mascarar o erro. "
            f"Admin autenticado nao pode receber 'Not authorized'. Erro: {result.error}"
        )
        assert result.success is False, "A8: success deve ser false"

    @pytest.mark.asyncio
    async def test_a8_no_security_bypass(self):
        """A8: capability inexistente nao causa bypass de seguranca."""
        cat = MockCatalogEmpty()
        pipe = make_pipeline(
            catalog=cat,
            authorization=cat,
        )
        result = await pipe.run(
            intent="malicious_intent",
            domain="infrastructure",
        )
        assert result.success is False, (
            "A8: admin nao pode executar capability inexistente. "
            "Nenhum bypass de seguranca deve ocorrer."
        )

    @pytest.mark.asyncio
    async def test_a8_gap_registered_for_audit(self):
        """A8: capability inexistente registra gap para auditoria."""
        gaps = GapProposalStore()
        cat = MockCatalogEmpty()
        pipe = make_pipeline(
            catalog=cat,
            authorization=cat,
            gaps=gaps,
        )
        await pipe.run(
            intent="nonexistent_capability_v2",
            domain="infrastructure",
        )
        gap_list = gaps.list_gaps()
        assert len(gap_list) > 0, (
            "A8: capability inexistente deve registrar gap para auditoria"
        )
        assert any(
            "nonexistent" in g.intent for g in gap_list
        ), "A8: gap deve conter a intencao original"