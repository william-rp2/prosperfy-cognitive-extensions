#!/usr/bin/env python3
"""
Fase F — Concorrência: Cenários CN1-CN4.

Testes assíncronos com asyncio.gather para paralelismo cooperativo.
Cada cenário verifica que operações simultâneas não causam race conditions,
perda de dados ou corrupção de estado.

Cenários:
  CN1: Duas execuções simultâneas (deploy + backup) → ambas completam, sem race condition
  CN2: Mesma Capability simultânea (2x deploy_evolution_api) → ambas executam
  CN3: Múltiplos usuários, mesma intenção → feedbacks isolados por usuário
  CN4: Atualização concorrente de feedback → FeedbackStore não corrompe
"""

import asyncio
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
    PolicyEngine, PolicyResult, PolicyVerdict,
)
from capability_intelligence.executor import Executor
from capability_intelligence.interpreter import Interpreter
from capability_intelligence.feedback_store import FeedbackStore, LocalFeedback
from capability_intelligence.gap_proposal import GapProposalStore
from capability_intelligence.pipeline import Pipeline, PipelineResult


# ======================================================================
# Mocks: implementam Protocolos de transporte (AuthorizationPort,
# ExecutionPort, CatalogPort)
# ======================================================================

class MockTransport:
    """Transport mock que rastreia concorrência ativa.

    Attributes:
        active_count: número de execuções atualmente em andamento
        max_concurrent: pico de concorrência observado
        executions: lista de (capability_id, event) rastreando cada execução
        _lock: asyncio.Lock para proteger estado compartilhado
    """

    def __init__(self, matches: list[CatalogMatch] | None = None,
                 exec_delay: float = 0.01):
        self._matches = matches or [
            CatalogMatch(capability_id="deploy_api", score=0.95, reason="test"),
        ]
        self._exec_delay = exec_delay
        self._authorized = True
        self.active_count = 0
        self.max_concurrent = 0
        self.executions: list[tuple[str, str]] = []
        self._lock = asyncio.Lock()
        self._call_counter = 0

    async def resolve(self, query: IntentQuery) -> CatalogResult:
        return CatalogResult(matches=self._matches)

    async def authorize(self, request: AuthorizationRequest) -> AuthorizationResult:
        return AuthorizationResult(authorized=self._authorized)

    async def execute(self, request: ExecutionRequest) -> ExecutionReference:
        self._call_counter += 1
        ref = ExecutionReference(
            ref=f"exec-{request.capability_id}-{self._call_counter}"
        )
        async with self._lock:
            self.active_count += 1
            self.max_concurrent = max(self.max_concurrent, self.active_count)
            self.executions.append((request.capability_id, "start"))
        # Simula trabalho assíncrono
        await asyncio.sleep(self._exec_delay)
        async with self._lock:
            self.active_count -= 1
            self.executions.append((request.capability_id, "end"))
        return ref

    async def result(self, ref: ExecutionReference) -> CapabilityResult:
        return CapabilityResult(
            success=True, data={"done": True, "ref": ref.ref},
            metadata=ResultMetadata(
                duration_ms=100,
                execution_ref=ref,
            ),
        )

    async def status(self, ref: ExecutionReference | None = None) -> StatusResult:
        return StatusResult(healthy=True, capabilities_total=10)


class MockCatalog:
    """CatalogPort simples que retorna match configurável."""

    def __init__(self, capability_id: str = "deploy_api", score: float = 0.95):
        self._matches = [
            CatalogMatch(capability_id=capability_id, score=score, reason="test"),
        ]

    async def resolve(self, query: IntentQuery) -> CatalogResult:
        return CatalogResult(matches=self._matches)


class MockAuth:
    """AuthorizationPort que permite todas as operações."""

    def __init__(self, allowed: bool = True):
        self._allowed = allowed

    async def authorize(self, request: AuthorizationRequest) -> AuthorizationResult:
        return AuthorizationResult(authorized=self._allowed)


class MockExec:
    """ExecutionPort que rastreia quantas vezes foi chamado."""

    def __init__(self, exec_delay: float = 0.01):
        self._exec_delay = exec_delay
        self.call_count = 0
        self.refs: list[str] = []

    async def execute(self, request: ExecutionRequest) -> ExecutionReference:
        self.call_count += 1
        ref = ExecutionReference(ref=f"exec-{request.capability_id}-{self.call_count}")
        self.refs.append(ref.ref)
        await asyncio.sleep(self._exec_delay)
        return ref

    async def result(self, ref: ExecutionReference) -> CapabilityResult:
        return CapabilityResult(
            success=True, data={"done": True, "ref": ref.ref},
            metadata=ResultMetadata(
                duration_ms=100,
                execution_ref=ref,
            ),
        )

    async def status(self, ref: ExecutionReference | None = None) -> StatusResult:
        return StatusResult(healthy=True, capabilities_total=10)


# ======================================================================
# Helpers
# ======================================================================

def make_pipeline(catalog=None, authorization=None, execution=None,
                  feedback=None, gaps=None) -> Pipeline:
    """Factory de Pipeline com mocks injetados."""
    cat = catalog or MockCatalog()
    auth = authorization or MockAuth()
    exec_ = execution or MockExec()
    return Pipeline(
        resolver=Resolver(catalog=cat),
        negotiator=Negotiator(),
        policy_engine=PolicyEngine(),
        executor=Executor(authorization=auth, execution=exec_),
        interpreter=Interpreter(),
        feedback_store=feedback or FeedbackStore(),
        gap_store=gaps or GapProposalStore(),
    )


# ======================================================================
# CN1: Duas execuções simultâneas (deploy + backup)
# ======================================================================

class TestCN1ConcurrentDifferentCapabilities:
    """CN1: Duas execuções simultâneas de Capabilities diferentes.

    Verifica que deploy e backup rodam concorrentemente sem race condition,
    ambas completam com sucesso, e o pico de concorrência observado é > 1.
    """

    @pytest.mark.asyncio
    async def test_cn1_both_complete_successfully(self):
        """CN1: deploy + backup simultâneos → ambas completam."""
        transport = MockTransport(
            matches=[
                CatalogMatch(capability_id="deploy_api", score=0.95, reason="deploy"),
            ],
            exec_delay=0.02,
        )
        pipe_deploy = make_pipeline(
            catalog=MockCatalog(capability_id="deploy_api"),
            execution=transport,
            authorization=transport,
        )
        transport._matches = [
            CatalogMatch(capability_id="backup_data", score=0.95, reason="backup"),
        ]
        pipe_backup = make_pipeline(
            catalog=MockCatalog(capability_id="backup_data"),
            execution=transport,
            authorization=transport,
        )

        r1, r2 = await asyncio.gather(
            pipe_deploy.run(intent="deploy api", domain="infrastructure"),
            pipe_backup.run(intent="backup data", domain="data"),
        )

        assert r1.success, f"CN1: deploy falhou: {r1.error}"
        assert r2.success, f"CN1: backup falhou: {r2.error}"
        assert r1.capability_id == "deploy_api"
        assert r2.capability_id == "backup_data"

    @pytest.mark.asyncio
    async def test_cn1_concurrent_peak_observed(self):
        """CN1: Pico de concorrência > 1 durante execução simultânea."""
        transport = MockTransport(
            matches=[
                CatalogMatch(capability_id="deploy_api", score=0.95, reason="deploy"),
            ],
            exec_delay=0.02,
        )
        pipe_deploy = make_pipeline(
            catalog=MockCatalog(capability_id="deploy_api"),
            execution=transport,
            authorization=transport,
        )
        transport._matches = [
            CatalogMatch(capability_id="backup_data", score=0.95, reason="backup"),
        ]
        pipe_backup = make_pipeline(
            catalog=MockCatalog(capability_id="backup_data"),
            execution=transport,
            authorization=transport,
        )

        await asyncio.gather(
            pipe_deploy.run(intent="deploy api", domain="infrastructure"),
            pipe_backup.run(intent="backup data", domain="data"),
        )

        assert transport.max_concurrent > 1, (
            f"CN1: pico de concorrência deveria ser > 1, "
            f"obteve max_concurrent={transport.max_concurrent}"
        )

    @pytest.mark.asyncio
    async def test_cn1_no_race_condition(self):
        """CN1: Sem race condition — execuções iniciam e terminam ordenadamente."""
        transport = MockTransport(
            matches=[
                CatalogMatch(capability_id="deploy_api", score=0.95, reason="deploy"),
            ],
            exec_delay=0.02,
        )
        pipe_deploy = make_pipeline(
            catalog=MockCatalog(capability_id="deploy_api"),
            execution=transport,
            authorization=transport,
        )
        transport._matches = [
            CatalogMatch(capability_id="backup_data", score=0.95, reason="backup"),
        ]
        pipe_backup = make_pipeline(
            catalog=MockCatalog(capability_id="backup_data"),
            execution=transport,
            authorization=transport,
        )

        await asyncio.gather(
            pipe_deploy.run(intent="deploy api", domain="infrastructure"),
            pipe_backup.run(intent="backup data", domain="data"),
        )

        # Verifica que cada execução iniciou e terminou uma vez
        deploy_starts = [e for e in transport.executions if e[0] == "deploy_api" and e[1] == "start"]
        deploy_ends = [e for e in transport.executions if e[0] == "deploy_api" and e[1] == "end"]
        backup_starts = [e for e in transport.executions if e[0] == "backup_data" and e[1] == "start"]
        backup_ends = [e for e in transport.executions if e[0] == "backup_data" and e[1] == "end"]

        assert len(deploy_starts) == 1, f"deploy_api start count: {len(deploy_starts)}"
        assert len(deploy_ends) == 1, f"deploy_api end count: {len(deploy_ends)}"
        assert len(backup_starts) == 1, f"backup_data start count: {len(backup_starts)}"
        assert len(backup_ends) == 1, f"backup_data end count: {len(backup_ends)}"

        # Nenhum evento a mais (sem vazamento)
        assert len(transport.executions) == 4, (
            f"Esperado 4 eventos (2 start + 2 end), obteve {len(transport.executions)}"
        )


# ======================================================================
# CN2: Mesma Capability simultânea (2x deploy_evolution_api)
# ======================================================================

class TestCN2SameCapabilityConcurrent:
    """CN2: Duas execuções simultâneas da MESMA Capability.

    Verifica que ambas executam, sem bloqueio ou race condition,
    e que cada execução gera seu próprio reference.
    """

    @pytest.mark.asyncio
    async def test_cn2_both_execute_independently(self):
        """CN2: 2x deploy_evolution_api → ambas executam."""
        transport = MockTransport(
            matches=[
                CatalogMatch(capability_id="deploy_evolution_api", score=0.95, reason="deploy"),
            ],
            exec_delay=0.02,
        )
        pipe = make_pipeline(
            catalog=MockCatalog(capability_id="deploy_evolution_api"),
            execution=transport,
            authorization=transport,
        )

        r1, r2 = await asyncio.gather(
            pipe.run(intent="deploy evolution api", domain="infrastructure"),
            pipe.run(intent="deploy evolution api", domain="infrastructure"),
        )

        assert r1.success, f"CN2: primeira execução falhou: {r1.error}"
        assert r2.success, f"CN2: segunda execução falhou: {r2.error}"
        assert r1.capability_id == "deploy_evolution_api"
        assert r2.capability_id == "deploy_evolution_api"

        # Cada execução gerou seu próprio ref
        assert r1.execution_ref is not None
        assert r2.execution_ref is not None
        assert r1.execution_ref.ref != r2.execution_ref.ref, (
            "CN2: execuções devem ter refs diferentes"
        )

    @pytest.mark.asyncio
    async def test_cn2_concurrent_peak_observed(self):
        """CN2: Pico de concorrência > 1 na mesma Capability."""
        transport = MockTransport(
            matches=[
                CatalogMatch(capability_id="deploy_evolution_api", score=0.95, reason="deploy"),
            ],
            exec_delay=0.02,
        )
        pipe = make_pipeline(
            catalog=MockCatalog(capability_id="deploy_evolution_api"),
            execution=transport,
            authorization=transport,
        )

        await asyncio.gather(
            pipe.run(intent="deploy evolution api", domain="infrastructure"),
            pipe.run(intent="deploy evolution api", domain="infrastructure"),
        )

        assert transport.max_concurrent > 1, (
            f"CN2: pico de concorrência deveria ser > 1 para mesma Capability, "
            f"obteve max_concurrent={transport.max_concurrent}"
        )

    @pytest.mark.asyncio
    async def test_cn2_no_data_corruption_in_execution_tracking(self):
        """CN2: Rastreamento de execuções não corrompe."""
        transport = MockTransport(
            matches=[
                CatalogMatch(capability_id="deploy_evolution_api", score=0.95, reason="deploy"),
            ],
            exec_delay=0.02,
        )
        pipe = make_pipeline(
            catalog=MockCatalog(capability_id="deploy_evolution_api"),
            execution=transport,
            authorization=transport,
        )

        await asyncio.gather(
            pipe.run(intent="deploy evolution api", domain="infrastructure"),
            pipe.run(intent="deploy evolution api", domain="infrastructure"),
        )

        # Verifica que temos exatamente 2 start + 2 end para deploy_evolution_api
        starts = [e for e in transport.executions if e[1] == "start"]
        ends = [e for e in transport.executions if e[1] == "end"]
        assert len(starts) == 2, f"CN2: esperado 2 starts, obteve {len(starts)}"
        assert len(ends) == 2, f"CN2: esperado 2 ends, obteve {len(ends)}"
        assert transport.active_count == 0, (
            f"CN2: active_count deveria ser 0 após gather, "
            f"obteve {transport.active_count}"
        )


# ======================================================================
# CN3: Múltiplos usuários, mesma intenção
# ======================================================================

class TestCN3MultipleUsersSameIntent:
    """CN3: Múltiplos usuários executam a mesma intenção simultaneamente.

    Verifica que cada usuário tem seu próprio feedback no FeedbackStore,
    sem vazamento ou mistura de dados entre usuários.
    """

    @pytest.mark.asyncio
    async def test_cn3_feedbacks_isolated_per_user(self):
        """CN3: Feedbacks isolados por usuário."""
        feedback = FeedbackStore()
        transport = MockTransport(
            matches=[
                CatalogMatch(capability_id="deploy_api", score=0.95, reason="deploy"),
            ],
            exec_delay=0.01,
        )
        pipe = make_pipeline(
            catalog=MockCatalog(capability_id="deploy_api"),
            execution=transport,
            authorization=transport,
            feedback=feedback,
        )

        users = ["alice", "bob", "charlie"]
        results = await asyncio.gather(*[
            pipe.run(intent="deploy web app", domain="infrastructure", user=user)
            for user in users
        ])

        # Todos executaram com sucesso
        for r, user in zip(results, users):
            assert r.success, f"CN3: {user} falhou: {r.error}"

        # Feedbacks registrados (3 execuções → 3 feedbacks)
        all_feedbacks = feedback._feedbacks
        assert len(all_feedbacks) == 3, (
            f"CN3: esperado 3 feedbacks, obteve {len(all_feedbacks)}"
        )

        # Todos os feedbacks têm o mesmo intent_query_hash
        hashes = {f.intent_query_hash for f in all_feedbacks}
        assert len(hashes) == 1, (
            f"CN3: todos os feedbacks deveriam ter mesmo hash, "
            f"obteve {len(hashes)} hashes diferentes"
        )

    @pytest.mark.asyncio
    async def test_cn3_success_rate_per_user(self):
        """CN3: Taxa de sucesso calculada corretamente apesar da concorrência."""
        feedback = FeedbackStore()
        transport = MockTransport(
            matches=[
                CatalogMatch(capability_id="deploy_api", score=0.95, reason="deploy"),
            ],
            exec_delay=0.01,
        )

        # Alice faz 3 deploys bem-sucedidos, Bob faz 1 sucesso + 1 falha
        for user, count, fails in [("alice", 3, 0), ("bob", 2, 1)]:
            for i in range(count):
                pipe = make_pipeline(
                    catalog=MockCatalog(capability_id="deploy_api"),
                    execution=transport,
                    authorization=transport,
                    feedback=feedback,
                )
                transport._authorized = i >= fails  # simula falha se i < fails
                await pipe.run(
                    intent="deploy web app", domain="infrastructure", user=user,
                )
                transport._authorized = True  # reset

        # Todos os feedbacks têm capability_id="deploy_api"
        rate = feedback.get_success_rate("deploy_api")
        # 3 sucessos da alice + 1 sucesso do bob = 4 / 5 total
        expected = 4 / 5
        assert rate == expected, (
            f"CN3: success_rate esperado {expected}, obteve {rate}"
        )


# ======================================================================
# CN4: Atualização concorrente de feedback → FeedbackStore não corrompe
# ======================================================================

class TestCN4ConcurrentFeedbackUpdates:
    """CN4: Múltiplas escritas concorrentes no FeedbackStore.

    Verifica que o FeedbackStore não perde dados nem corrompe estado
    quando várias corrotinas escrevem simultaneamente.
    """

    @pytest.mark.asyncio
    async def test_cn4_no_data_loss_with_concurrent_writes(self):
        """CN4: Escritas concorrentes não perdem dados."""
        store = FeedbackStore()

        async def write_feedback(cap_id: str, intent_hash: str,
                                 success: bool, idx: int):
            """Registra um feedback de forma concorrente."""
            store.record(LocalFeedback(
                capability_id=cap_id,
                intent_query_hash=intent_hash,
                success=success,
                duration_ms=idx * 10,
            ))

        TOTAL = 100
        await asyncio.gather(*[
            write_feedback(
                cap_id="deploy_api",
                intent_hash=f"hash_{i % 10}",
                success=i % 3 != 0,  # ~66% success
                idx=i,
            )
            for i in range(TOTAL)
        ])

        assert len(store._feedbacks) == TOTAL, (
            f"CN4: esperado {TOTAL} feedbacks, obteve {len(store._feedbacks)}"
        )

        # get_history com capability específica retorna todos
        history = store.get_history("deploy_api")
        assert len(history) == TOTAL, (
            f"CN4: get_history('deploy_api') deveria retornar {TOTAL}, "
            f"obteve {len(history)}"
        )

    @pytest.mark.asyncio
    async def test_cn4_preferred_capability_consistent(self):
        """CN4: get_preferred_capability consistente após escritas concorrentes."""
        store = FeedbackStore()

        async def write_fb(cap_id: str, intent_hash: str, success: bool = True):
            """Wraps sync store.record in an async function."""
            store.record(LocalFeedback(
                capability_id=cap_id,
                intent_query_hash=intent_hash,
                success=success,
            ))

        async def write_batch(cap_ids: list[str], intent_hash: str, count: int):
            """Escreve feedbacks concorrentes para várias capabilities."""
            await asyncio.gather(*[
                write_fb(
                    cap_id=cap_ids[i % len(cap_ids)],
                    intent_hash=intent_hash,
                )
                for i in range(count)
            ])

        INTENT_HASH = "cn4_test_intent"
        await write_batch(
            cap_ids=["cap_a", "cap_b", "cap_c"],
            intent_hash=INTENT_HASH,
            count=60,  # 20 each
        )

        # Todas aparecem igualmente → preferred pode ser qualquer uma
        preferred = store.get_preferred_capability(INTENT_HASH)
        assert preferred in ("cap_a", "cap_b", "cap_c"), (
            f"CN4: preferred deveria ser uma das 3 capabilities, "
            f"obteve {preferred}"
        )

        # Agora adiciona mais para cap_a dominar
        await write_batch(
            cap_ids=["cap_a", "cap_a", "cap_a", "cap_b", "cap_c"],
            intent_hash=INTENT_HASH,
            count=50,  # 30 cap_a, 10 cap_b, 10 cap_c
        )

        preferred = store.get_preferred_capability(INTENT_HASH)
        assert preferred == "cap_a", (
            f"CN4: após dominância, preferred deveria ser cap_a, "
            f"obteve {preferred}"
        )

    @pytest.mark.asyncio
    async def test_cn4_success_rate_with_concurrent_updates(self):
        """CN4: Taxa de sucesso calculada corretamente com escritas concorrentes."""
        store = FeedbackStore()

        async def write_fb(cap_id: str, intent_hash: str, success: bool):
            store.record(LocalFeedback(
                capability_id=cap_id,
                intent_query_hash=intent_hash,
                success=success,
            ))

        async def write_with_mixed_results(cap_id: str, total: int, fail_every: int):
            """Escreve feedbacks com sucessos e falhas alternados."""
            await asyncio.gather(*[
                write_fb(
                    cap_id=cap_id,
                    intent_hash="test_hash",
                    success=(i % fail_every != 0),
                )
                for i in range(total)
            ])

        await write_with_mixed_results("cap_test", total=50, fail_every=5)
        # 50 registros, 10 falhas (every 5th), 40 sucessos
        rate = store.get_success_rate("cap_test")
        expected = 40 / 50  # = 0.8
        assert rate == expected, (
            f"CN4: success_rate esperado {expected}, obteve {rate}"
        )

    @pytest.mark.asyncio
    async def test_cn4_multiple_capabilities_no_crosstalk(self):
        """CN4: Capacidades diferentes não misturam dados."""
        store = FeedbackStore()

        caps = ["alpha", "beta", "gamma"]
        per_cap = 30

        async def write_fb(cap_id: str, idx: int):
            store.record(LocalFeedback(
                capability_id=cap_id,
                intent_query_hash=f"hash_{cap_id}_{idx}",
                success=True,
            ))

        async def write_for_cap(cap_id: str):
            await asyncio.gather(*[
                write_fb(cap_id=cap_id, idx=i)
                for i in range(per_cap)
            ])

        await asyncio.gather(*[write_for_cap(c) for c in caps])

        for cap_id in caps:
            history = store.get_history(cap_id)
            assert len(history) == per_cap, (
                f"CN4: {cap_id} esperado {per_cap} feedbacks, "
                f"obteve {len(history)}"
            )

        # Total geral
        assert len(store._feedbacks) == per_cap * len(caps), (
            f"CN4: total esperado {per_cap * len(caps)}, "
            f"obteve {len(store._feedbacks)}"
        )