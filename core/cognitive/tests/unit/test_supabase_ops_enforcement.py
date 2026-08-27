"""
tests/unit/test_supabase_ops_enforcement.py — P0 (Supabase Ops + Anti-Hibernação).

Fail-closed enforcement para as 5 capabilities supabase.*:
  - allowlist de tool_name/argumentos no ComposioMcpAdapter/mock (SQL
    arbitrário negado, tool de mutation/migration negada — NO_MUTATION);
  - grant/policy do orchestrator (sem grant -> DENY, cross-tenant -> DENY);
  - isolamento de falha do SupabaseKeepaliveService (1 projeto falha, os
    demais seguem — FAILURE_ISOLATION) + alerta na 2ª falha consecutiva.

ZERO MCP real — fake/recording adapters + repositórios em memória.
NORMAL sem tools Supabase é coberto por
hermes/capability-intelligence/tests/test_capability_router.py (51/51).
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from cognitive.adapters.composio.guard import ForbiddenArgumentError, guard_arguments
from cognitive.adapters.composio.mock import MockComposioAdapter
from cognitive.adapters.supabase_registry.adapter import SupabaseRegistryAdapter
from cognitive.audit.writer import InMemoryAuditWriter
from cognitive.contracts.tenancy import ActorContext, CapabilityGrant
from cognitive.db.repositories.supabase_ops_repo import SupabaseProjectRow
from cognitive.execution.orchestrator import ExecutionOrchestrator
from cognitive.execution.resource_resolver import InMemoryResourceResolver
from cognitive.execution.supabase_keepalive_service import SupabaseKeepaliveService
from cognitive.policy.engine import PolicyEngine
from cognitive.registry.registry import InMemoryCapabilityRegistry
from cognitive.telemetry.recorder import InMemoryTelemetryRecorder

TENANT = "tenant-p0"
OTHER_TENANT = "tenant-other"
PROFILE = "infra-read"


def _ctx(tenant: str = TENANT, actor: str = "actor-p0") -> ActorContext:
    return ActorContext(
        tenant_id=tenant, actor_id=actor, correlation_id="corr-p0",
        credential_ref="ref-p0", profile=PROFILE,
    )


def _project_row(ref: str = "wioorhtdwnfujkrynxij", **overrides: Any) -> SupabaseProjectRow:
    base: dict[str, Any] = dict(
        id=f"id-{ref}", tenant_id=TENANT, composio_account="Supabase - Hermes",
        project_ref=ref, display_name="Hermes", region="sa-east-1",
        plan="free", plan_source="test", keepalive_enabled=True, status="unknown",
        last_success_at=None, last_latency_ms=None, consecutive_failures=0,
        last_error_code=None, next_run_at=None, active=True,
    )
    base.update(overrides)
    return SupabaseProjectRow(**base)


class FakeProjectRepo:
    """Fake in-memory de SupabaseProjectRepository — mesmo shape assíncrono."""

    def __init__(self, rows: list[SupabaseProjectRow] | None = None) -> None:
        self.rows: dict[str, SupabaseProjectRow] = {r.id: r for r in (rows or [])}

    async def list_all(self, tenant_id: str) -> list[SupabaseProjectRow]:
        return [r for r in self.rows.values() if r.tenant_id == tenant_id and r.active]

    async def list_keepalive_enabled(self, tenant_id: str) -> list[SupabaseProjectRow]:
        return [
            r for r in self.rows.values()
            if r.tenant_id == tenant_id and r.active and r.keepalive_enabled
        ]

    async def get_by_ref(self, tenant_id: str, project_ref: str) -> SupabaseProjectRow | None:
        for r in self.rows.values():
            if r.tenant_id == tenant_id and r.project_ref == project_ref:
                return r
        return None

    async def find_by_name(self, tenant_id: str, name_query: str) -> list[SupabaseProjectRow]:
        low = name_query.lower()
        return [
            r for r in self.rows.values()
            if r.tenant_id == tenant_id and r.active and low in r.display_name.lower()
        ]

    async def record_run_result(
        self, tenant_id: str, project_id: str, run_status: str,
        latency_ms: int | None, error_code: str | None, next_run_at: Any,
    ) -> dict[str, Any]:
        row = self.rows[project_id]
        if run_status == "success":
            row.consecutive_failures = 0
            row.status = "healthy"
        else:
            row.consecutive_failures += 1
            row.status = "failed" if row.consecutive_failures >= 2 else "warning"
        return {"status": row.status, "consecutive_failures": row.consecutive_failures}

    async def summary(self, tenant_id: str) -> dict[str, Any]:
        rows = await self.list_all(tenant_id)
        return {"total": len(rows)}


class FakeRunRepo:
    """Fake in-memory de SupabaseKeepaliveRunRepository."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def record(self, **kwargs: Any) -> str:
        self.records.append(kwargs)
        return f"run-{len(self.records)}"

    async def list_recent_for_project(self, tenant_id: str, project_id: str, limit: int = 5):
        return []

    async def count_consecutive_recent_failures(self, tenant_id, project_id, lookback=5) -> int:
        return 0


def _build_orchestrator(
    composio_adapter=None,
    registry_adapter=None,
    grant_capability_ids: tuple[str, ...] = (),
    grant_tenant: str = TENANT,
) -> ExecutionOrchestrator:
    registry = InMemoryCapabilityRegistry()
    registry.load_from_yaml()
    for cap_id in grant_capability_ids:
        registry.register_grant(
            CapabilityGrant(tenant_id=grant_tenant, profile=PROFILE, capability_id=cap_id),
        )
    return ExecutionOrchestrator(
        registry=registry,
        policy_engine=PolicyEngine(),
        # fallback nunca deveria ser exercido pelas capabilities supabase.* —
        # se cair aqui é sinal de bug de roteamento de adapter.
        skills_adapter=MockComposioAdapter(),
        audit_writer=InMemoryAuditWriter(),
        telemetry_recorder=InMemoryTelemetryRecorder(),
        resource_resolver=InMemoryResourceResolver(),
        composio_adapter=composio_adapter,
        registry_adapter=registry_adapter,
    )


# ─── Positivos ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_keepalive_run_positive_exact_args():
    adapter = MockComposioAdapter()
    orch = _build_orchestrator(composio_adapter=adapter, grant_capability_ids=("supabase.keepalive.run",))

    result = await orch.execute(
        ctx=_ctx(),
        capability_id="supabase.keepalive.run",
        params={"ref": "wioorhtdwnfujkrynxij", "account": "Supabase - Hermes", "query": "SELECT now()"},
    )

    assert result.status.value == "completed"
    assert len(adapter.calls) == 1
    tool_name, tool_args = adapter.calls[0]
    assert tool_name == "SUPABASE_RUN_READ_ONLY_QUERY"
    assert tool_args == {
        "ref": "wioorhtdwnfujkrynxij", "account": "Supabase - Hermes", "query": "SELECT now()",
    }


@pytest.mark.asyncio
async def test_projects_read_positive_via_registry_adapter():
    repo = FakeProjectRepo([_project_row()])
    registry_adapter = SupabaseRegistryAdapter(project_repo=repo, run_repo=FakeRunRepo())
    orch = _build_orchestrator(
        registry_adapter=registry_adapter, grant_capability_ids=("supabase.projects.read",),
    )

    result = await orch.execute(ctx=_ctx(), capability_id="supabase.projects.read", params={})

    assert result.status.value == "completed"
    tool_result = result.data["supabase_registry.list_projects"]
    assert tool_result["success"] is True
    projects = tool_result["data"]["projects"]
    assert projects[0]["project_ref"] == "wioorhtdwnfujkrynxij"
    assert projects[0]["composio_account"] == "Supabase - Hermes"


@pytest.mark.asyncio
async def test_ops_summary_positive_roundtrip():
    repo = FakeProjectRepo([_project_row(), _project_row(ref="aaaaaaaaaaaaaaaaaaaa", id="id-2", plan="unknown")])
    registry_adapter = SupabaseRegistryAdapter(project_repo=repo, run_repo=FakeRunRepo())
    orch = _build_orchestrator(
        registry_adapter=registry_adapter, grant_capability_ids=("supabase.ops.summary",),
    )

    result = await orch.execute(ctx=_ctx(), capability_id="supabase.ops.summary", params={})

    assert result.status.value == "completed"
    data = result.data["supabase_registry.summary"]["data"]
    assert data["summary"]["total"] == 2
    assert len(data["projects"]) == 2


# ─── Negativos: SQL arbitrário / mutation (gate NO_MUTATION) ────────────

@pytest.mark.parametrize("bad_query", [
    "DROP TABLE users",
    "DELETE FROM projects",
    "SELECT * FROM users",
    "SELECT 1; DROP TABLE x;",
    "select now() -- comment injection",
    "UPDATE projects SET plan = 'free'",
])
def test_guard_rejects_arbitrary_sql(bad_query):
    with pytest.raises(ForbiddenArgumentError):
        guard_arguments("SUPABASE_RUN_READ_ONLY_QUERY", {"ref": "wioorhtdwnfujkrynxij", "query": bad_query})


@pytest.mark.parametrize("tool_name", [
    "SUPABASE_BETA_RUN_SQL_QUERY",  # SQL livre/DDL — nunca pela capability
    "SUPABASE_SELECT_FROM_TABLE",   # fora da allowlist
    "SUPABASE_APPLY_MIGRATION",     # hipotética, também fora da allowlist
])
def test_guard_rejects_tool_name_outside_allowlist(tool_name):
    with pytest.raises(ForbiddenArgumentError):
        guard_arguments(tool_name, {"ref": "wioorhtdwnfujkrynxij", "query": "SELECT 1"})


@pytest.mark.asyncio
async def test_keepalive_run_end_to_end_denies_arbitrary_sql():
    """Mesmo através do orchestrator inteiro (não só o guard isolado),
    SQL fora do allowlist fixo nunca chega a rede — falha fechada."""
    adapter = MockComposioAdapter()
    orch = _build_orchestrator(composio_adapter=adapter, grant_capability_ids=("supabase.keepalive.run",))

    result = await orch.execute(
        ctx=_ctx(),
        capability_id="supabase.keepalive.run",
        params={"ref": "wioorhtdwnfujkrynxij", "account": "Supabase - Hermes", "query": "DROP TABLE users"},
    )

    assert result.status.value == "failed"
    assert adapter.calls == []


# ─── Negativos: grant/policy (fail-closed) ───────────────────────────────

@pytest.mark.asyncio
async def test_keepalive_run_no_grant_denies():
    adapter = MockComposioAdapter()
    orch = _build_orchestrator(composio_adapter=adapter, grant_capability_ids=())  # sem grant nenhum

    result = await orch.execute(
        ctx=_ctx(),
        capability_id="supabase.keepalive.run",
        params={"ref": "wioorhtdwnfujkrynxij", "account": "Supabase - Hermes", "query": "SELECT 1"},
    )

    assert result.status.value == "failed"
    assert "Denied" in (result.error or "")
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_keepalive_run_cross_tenant_grant_denies():
    adapter = MockComposioAdapter()
    # grant existe, mas para OUTRO tenant — PolicyEngine.evaluate() Step 2
    # (cross_tenant_guard) precisa recusar mesmo se o grant_resolver
    # (in-memory, por capability_id só) devolvesse esse grant por engano.
    orch = _build_orchestrator(
        composio_adapter=adapter,
        grant_capability_ids=("supabase.keepalive.run",),
        grant_tenant=OTHER_TENANT,
    )

    result = await orch.execute(
        ctx=_ctx(tenant=TENANT),
        capability_id="supabase.keepalive.run",
        params={"ref": "wioorhtdwnfujkrynxij", "account": "Supabase - Hermes", "query": "SELECT 1"},
    )

    assert result.status.value == "failed"
    assert adapter.calls == []


# ─── Isolamento de falha (gate FAILURE_ISOLATION) ────────────────────────

class FlakyComposioAdapter:
    """Projetos em `fail_refs` sempre falham (transporte); os demais
    funcionam — simula doc §9 item 9: 'Simular falha de um resource sem
    afetar os demais'."""

    def __init__(self, fail_refs: set[str]) -> None:
        self._fail_refs = fail_refs
        self.calls: list[tuple[str, dict]] = []

    async def invoke_tool(self, tool_name, arguments, tenant_id, correlation_id):
        self.calls.append((tool_name, dict(arguments)))
        if arguments.get("ref") in self._fail_refs:
            raise RuntimeError("Compose MCP indisponível (simulado)")
        return {"success": True, "data": {"result": [{"now": "2026-01-01T00:00:00Z"}], "rows_returned": 1}}

    async def health(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_keepalive_service_isolates_single_project_failure():
    good = _project_row(ref="aaaaaaaaaaaaaaaaaaaa", id="id-good", display_name="Good")
    bad = _project_row(ref="bbbbbbbbbbbbbbbbbbbb", id="id-bad", display_name="Bad")
    project_repo = FakeProjectRepo([good, bad])
    run_repo = FakeRunRepo()

    adapter = FlakyComposioAdapter(fail_refs={"bbbbbbbbbbbbbbbbbbbb"})
    orch = _build_orchestrator(composio_adapter=adapter, grant_capability_ids=("supabase.keepalive.run",))
    service = SupabaseKeepaliveService(
        orch, project_repo=project_repo, run_repo=run_repo, retry_delays_seconds=(),
    )

    result = await service.run_all(tenant_id=TENANT)

    assert result.success_count == 1
    assert result.failure_count == 1
    statuses = {o.project_ref: o.status for o in result.outcomes}
    assert statuses["aaaaaaaaaaaaaaaaaaaa"] == "success"
    assert statuses["bbbbbbbbbbbbbbbbbbbb"] == "failure"
    # os DOIS foram tentados — a falha de um não impediu o outro de rodar
    assert len(adapter.calls) == 2
    assert len(run_repo.records) == 2


@pytest.mark.asyncio
async def test_keepalive_service_no_projects_enabled_returns_empty_round():
    project_repo = FakeProjectRepo([])  # nenhum projeto keepalive_enabled
    run_repo = FakeRunRepo()
    adapter = FlakyComposioAdapter(fail_refs=set())
    orch = _build_orchestrator(composio_adapter=adapter, grant_capability_ids=("supabase.keepalive.run",))
    service = SupabaseKeepaliveService(
        orch, project_repo=project_repo, run_repo=run_repo, retry_delays_seconds=(),
    )

    result = await service.run_all(tenant_id=TENANT)

    assert result.success_count == 0
    assert result.failure_count == 0
    assert result.outcomes == []
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_keepalive_service_alert_on_second_consecutive_failure():
    project = _project_row(ref="cccccccccccccccccccc", id="id-c", consecutive_failures=1)
    project_repo = FakeProjectRepo([project])
    run_repo = FakeRunRepo()

    adapter = FlakyComposioAdapter(fail_refs={"cccccccccccccccccccc"})
    orch = _build_orchestrator(composio_adapter=adapter, grant_capability_ids=("supabase.keepalive.run",))
    service = SupabaseKeepaliveService(
        orch, project_repo=project_repo, run_repo=run_repo, retry_delays_seconds=(),
    )

    result = await service.run_all(tenant_id=TENANT)

    assert result.failure_count == 1
    assert len(result.alerts) == 1
    assert result.alerts[0].consecutive_failures == 2


@pytest.mark.asyncio
async def test_keepalive_service_first_failure_no_alert_yet():
    project = _project_row(ref="dddddddddddddddddddd", id="id-d", consecutive_failures=0)
    project_repo = FakeProjectRepo([project])
    run_repo = FakeRunRepo()

    adapter = FlakyComposioAdapter(fail_refs={"dddddddddddddddddddd"})
    orch = _build_orchestrator(composio_adapter=adapter, grant_capability_ids=("supabase.keepalive.run",))
    service = SupabaseKeepaliveService(
        orch, project_repo=project_repo, run_repo=run_repo, retry_delays_seconds=(),
    )

    result = await service.run_all(tenant_id=TENANT)

    assert result.failure_count == 1
    assert len(result.alerts) == 0  # 1ª falha isolada — doc §8: não incomodar ainda


# ─── Retry (doc §4.1/§8: RETRY=1m,5m,30m, máx. 3 retries por janela) ────

class FlakyThenRecoversAdapter:
    """Falha nas N primeiras chamadas por ref, sucesso a partir da (N+1)ª —
    simula uma indisponibilidade transitória do Compose MCP que o retry
    consegue superar dentro da mesma janela."""

    def __init__(self, fail_first_n: int) -> None:
        self._fail_first_n = fail_first_n
        self.call_count = 0

    async def invoke_tool(self, tool_name, arguments, tenant_id, correlation_id):
        self.call_count += 1
        if self.call_count <= self._fail_first_n:
            raise RuntimeError(f"transiente (tentativa {self.call_count})")
        return {"success": True, "data": {"result": [{"now": "2026-01-01T00:00:00Z"}], "rows_returned": 1}}

    async def health(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_keepalive_retries_and_recovers_within_window():
    """1ª tentativa falha, retry (delay injetado ~0) sucede — resultado
    final é 'success', uma ÚNICA linha de run persistida (não uma por
    tentativa)."""
    project = _project_row(ref="eeeeeeeeeeeeeeeeeeee", id="id-e")
    project_repo = FakeProjectRepo([project])
    run_repo = FakeRunRepo()

    adapter = FlakyThenRecoversAdapter(fail_first_n=1)
    orch = _build_orchestrator(composio_adapter=adapter, grant_capability_ids=("supabase.keepalive.run",))
    service = SupabaseKeepaliveService(
        orch, project_repo=project_repo, run_repo=run_repo,
        retry_delays_seconds=(0.001, 0.001, 0.001),
    )

    result = await service.run_all(tenant_id=TENANT)

    assert result.success_count == 1
    assert result.failure_count == 0
    assert adapter.call_count == 2  # 1ª falhou, 2ª (retry) sucedeu
    assert len(run_repo.records) == 1  # 1 linha por PROJETO/EXECUÇÃO, não por tentativa


@pytest.mark.asyncio
async def test_keepalive_exhausts_all_retries_then_fails():
    """Falha em TODAS as tentativas (1 original + 3 retries = 4 chamadas) —
    esgota o orçamento de retry da janela e reporta failure final."""
    project = _project_row(ref="ffffffffffffffffffff", id="id-f")
    project_repo = FakeProjectRepo([project])
    run_repo = FakeRunRepo()

    adapter = FlakyThenRecoversAdapter(fail_first_n=999)  # nunca recupera
    orch = _build_orchestrator(composio_adapter=adapter, grant_capability_ids=("supabase.keepalive.run",))
    service = SupabaseKeepaliveService(
        orch, project_repo=project_repo, run_repo=run_repo,
        retry_delays_seconds=(0.001, 0.001, 0.001),
    )

    result = await service.run_all(tenant_id=TENANT)

    assert result.failure_count == 1
    assert adapter.call_count == 4  # 1 original + 3 retries (doc: máx. 3 retries)
    assert len(run_repo.records) == 1


@pytest.mark.asyncio
async def test_keepalive_retry_is_round_level_not_per_project():
    """Regressão de design: o retry precisa ser aplicado à RODADA (todos os
    projetos pendentes juntos em cada passagem), não a cada projeto
    isoladamente. Com retry por-projeto, N projetos falhando em série
    custariam N * soma(delays) de wall-clock; com retry por-rodada custa
    sempre soma(delays), não importa quantos projetos falhem. Prova com 5
    projetos falhando e delays pequenos porém mensuráveis: o tempo total
    fica preso a ~soma(delays), não escala com o número de projetos."""
    n_projects = 5
    delays = (0.05, 0.05, 0.05)
    projects = [
        _project_row(ref=f"{chr(97 + i)}" * 20, id=f"id-multi-{i}", display_name=f"P{i}")
        for i in range(n_projects)
    ]
    project_repo = FakeProjectRepo(projects)
    run_repo = FakeRunRepo()

    adapter = FlakyThenRecoversAdapter(fail_first_n=999)  # nenhum projeto nunca recupera
    orch = _build_orchestrator(composio_adapter=adapter, grant_capability_ids=("supabase.keepalive.run",))
    service = SupabaseKeepaliveService(
        orch, project_repo=project_repo, run_repo=run_repo, retry_delays_seconds=delays,
    )

    start = time.monotonic()
    result = await service.run_all(tenant_id=TENANT)
    elapsed = time.monotonic() - start

    assert result.failure_count == n_projects
    # 4 passagens (1 + 3 retries) * 5 projetos = 20 chamadas ao adapter
    assert adapter.call_count == n_projects * 4
    # tempo total ~ soma(delays) = 0.15s, independente de n_projects — se o
    # retry fosse por-projeto isolado, isso escalaria para ~0.75s (5x)
    assert elapsed < sum(delays) + 0.5, f"elapsed={elapsed:.3f}s sugere retry por-projeto, não por-rodada"
