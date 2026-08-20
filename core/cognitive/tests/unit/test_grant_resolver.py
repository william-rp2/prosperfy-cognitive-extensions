"""
tests/unit/test_grant_resolver.py — FIX Sprint 0.3 RETURN_TO_DEV (Item A).

Cobre a resolução de grants em database mode:
  - PostgresGrantResolver consulta a fonte persistida (capability_grants via
    GrantRepository com RLS) em vez de depender da lista in-memory do registry.
  - grant válido → resolvido; sem grant → None (DENY);
    grant de outro tenant → None; profile incorreto → None;
    capability diferente → None; grant inativo → None.
  - erro de DB/transação → None (fail-closed), com log sanitizado.
  - RegistryGrantResolver preserva a semântica in-memory (sem regressão).
  - Orquestrador em database mode: grant do tenant certo → ALLOW + adapter é
    chamado; sem grant/outro tenant → DENY e adapter NUNCA é chamado.

Sem DB real: GrantRepository é substituído por um FakeGrantRepository que
simula o filtro de tenant (equivalente à RLS no banco). A prova real contra
Postgres (RLS de verdade, incl. linhas de outro tenant invisíveis) fica em
tests/db/test_grants_database_mode.py (VPS_REQUIRED).
"""

from __future__ import annotations

import logging

import pytest

from cognitive.audit.writer import InMemoryAuditWriter
from cognitive.contracts.tenancy import ActorContext, CapabilityGrant
from cognitive.execution.orchestrator import ExecutionOrchestrator
from cognitive.execution.resource_resolver import InMemoryResourceResolver
from cognitive.policy.engine import PolicyEngine
from cognitive.registry.grant_resolver import (
    GrantResolverPort,
    PostgresGrantResolver,
    RegistryGrantResolver,
)
from cognitive.registry.registry import InMemoryCapabilityRegistry
from cognitive.telemetry.recorder import InMemoryTelemetryRecorder

CANARY = "55a0ccf2" + "b" * 32


class FakeGrantRepository:
    """Fake de GrantRepository — sem asyncpg. Simula o filtro RLS por tenant
    (via tenant_id no match) para que o teste unitário reproduza o contrato
    de isolamento sem depender de banco configurado."""

    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []
        self.get_calls: list[tuple[str, str, str]] = []
        self.fail_on = False

    def _match(self, row: dict, tenant_id: str, profile: str, capability_id: str) -> bool:
        return (
            row["tenant_id"] == tenant_id
            and row["profile"] == profile
            and row["capability_id"] == capability_id
            and row.get("active", True)
        )

    async def get_grant(self, tenant_id, profile, capability_id):
        self.get_calls.append((tenant_id, profile, capability_id))
        if self.fail_on:
            # Erro realista de conexão/DB: DSN com credencial — o sanitizer
            # precisa remover o segredo do log.
            raise RuntimeError(
                f"[asyncpg] connection failed: "
                f"postgresql://cognitive_app:{CANARY}@db.invalid:5432/postgres"
            )
        for row in self.rows:
            if self._match(row, tenant_id, profile, capability_id):
                return CapabilityGrant(
                    tenant_id=row["tenant_id"],
                    profile=row["profile"],
                    capability_id=row["capability_id"],
                    policy_override=row.get("policy_override"),
                )
        return None

    async def list_for_tenant_profile(self, tenant_id, profile):
        if self.fail_on:
            raise RuntimeError(
                f"[asyncpg] connection failed: "
                f"postgresql://cognitive_app:{CANARY}@db.invalid:5432/postgres"
            )
        return [
            CapabilityGrant(
                tenant_id=r["tenant_id"],
                profile=r["profile"],
                capability_id=r["capability_id"],
                policy_override=r.get("policy_override"),
            )
            for r in self.rows
            if r["tenant_id"] == tenant_id
            and r["profile"] == profile
            and r.get("active", True)
        ]


GRANT_A = {
    "tenant_id": "tenant-a",
    "profile": "owner-core",
    "capability_id": "infra.inspect",
}


# ─── PostgresGrantResolver (database mode) ────────────────────────────────

class TestPostgresGrantResolver:
    def test_satisfies_port(self):
        resolver = PostgresGrantResolver(repo=FakeGrantRepository())
        assert isinstance(resolver, GrantResolverPort)

    @pytest.mark.asyncio
    async def test_valid_grant_permitted(self):
        repo = FakeGrantRepository(rows=[dict(GRANT_A)])
        resolver = PostgresGrantResolver(repo=repo)
        grant = await resolver.resolve_grant("tenant-a", "owner-core", "infra.inspect")
        assert grant is not None
        assert grant.tenant_id == "tenant-a"
        assert grant.capability_id == "infra.inspect"
        # Prova que consultou a fonte persistida (não a lista in-memory do
        # registry — que está vazia) e que o tenant é propagado na consulta.
        assert repo.get_calls[-1] == ("tenant-a", "owner-core", "infra.inspect")

    @pytest.mark.asyncio
    async def test_no_grant_returns_none(self):
        resolver = PostgresGrantResolver(repo=FakeGrantRepository([]))
        assert await resolver.resolve_grant("tenant-a", "owner-core", "infra.inspect") is None

    @pytest.mark.asyncio
    async def test_other_tenant_grant_not_leaked(self):
        """Grant de tenant-a não é visível para tenant-b (isolamento RLS)."""
        repo = FakeGrantRepository(rows=[dict(GRANT_A)])
        resolver = PostgresGrantResolver(repo=repo)
        grant = await resolver.resolve_grant("tenant-b", "owner-core", "infra.inspect")
        assert grant is None
        assert repo.get_calls[-1] == ("tenant-b", "owner-core", "infra.inspect")

    @pytest.mark.asyncio
    async def test_wrong_profile_returns_none(self):
        repo = FakeGrantRepository(rows=[dict(GRANT_A)])
        resolver = PostgresGrantResolver(repo=repo)
        assert await resolver.resolve_grant("tenant-a", "infra-read", "infra.inspect") is None

    @pytest.mark.asyncio
    async def test_wrong_capability_returns_none(self):
        repo = FakeGrantRepository(rows=[dict(GRANT_A)])
        resolver = PostgresGrantResolver(repo=repo)
        assert await resolver.resolve_grant("tenant-a", "owner-core", "finance.report") is None

    @pytest.mark.asyncio
    async def test_inactive_grant_returns_none(self):
        row = dict(GRANT_A)
        row["active"] = False
        resolver = PostgresGrantResolver(repo=FakeGrantRepository(rows=[row]))
        assert await resolver.resolve_grant("tenant-a", "owner-core", "infra.inspect") is None

    @pytest.mark.asyncio
    async def test_policy_override_returned(self):
        row = dict(GRANT_A)
        row["policy_override"] = "confirm"
        resolver = PostgresGrantResolver(repo=FakeGrantRepository(rows=[row]))
        grant = await resolver.resolve_grant("tenant-a", "owner-core", "infra.inspect")
        assert grant is not None
        assert grant.policy_override == "confirm"

    @pytest.mark.asyncio
    async def test_db_error_fail_closed_deny(self, caplog):
        """Erro de DB → None (DENY), com log sanitizado (nunca o segredo)."""
        repo = FakeGrantRepository(rows=[dict(GRANT_A)])
        repo.fail_on = True
        resolver = PostgresGrantResolver(repo=repo)
        with caplog.at_level(logging.ERROR):
            grant = await resolver.resolve_grant("tenant-a", "owner-core", "infra.inspect")
        assert grant is None
        assert any("fail-closed DENY" in r.getMessage() for r in caplog.records)
        for record in caplog.records:
            assert CANARY not in record.getMessage()

    @pytest.mark.asyncio
    async def test_list_for_tenant_profile(self):
        repo = FakeGrantRepository(rows=[dict(GRANT_A)])
        resolver = PostgresGrantResolver(repo=repo)
        grants = await resolver.list_for_tenant_profile("tenant-a", "owner-core")
        assert [g.capability_id for g in grants] == ["infra.inspect"]
        assert await resolver.list_for_tenant_profile("tenant-b", "owner-core") == []

    @pytest.mark.asyncio
    async def test_db_error_listing_fail_closed_empty(self, caplog):
        repo = FakeGrantRepository(rows=[dict(GRANT_A)])
        repo.fail_on = True
        resolver = PostgresGrantResolver(repo=repo)
        with caplog.at_level(logging.ERROR):
            grants = await resolver.list_for_tenant_profile("tenant-a", "owner-core")
        assert grants == []
        for record in caplog.records:
            assert CANARY not in record.getMessage()


# ─── RegistryGrantResolver (in-memory, sem regressão) ─────────────────────

class TestRegistryGrantResolver:
    @staticmethod
    def _registry() -> InMemoryCapabilityRegistry:
        registry = InMemoryCapabilityRegistry()
        registry.load_from_yaml()
        registry.register_grant(CapabilityGrant(
            tenant_id="tenant-a",
            profile="owner-core",
            capability_id="infra.inspect",
        ))
        return registry

    @pytest.mark.asyncio
    async def test_resolves_in_memory_grant(self):
        resolver = RegistryGrantResolver(self._registry())
        grant = await resolver.resolve_grant("tenant-a", "owner-core", "infra.inspect")
        assert grant is not None
        assert grant.tenant_id == "tenant-a"

    @pytest.mark.asyncio
    async def test_other_tenant_not_resolved(self):
        resolver = RegistryGrantResolver(self._registry())
        assert await resolver.resolve_grant("tenant-b", "owner-core", "infra.inspect") is None

    @pytest.mark.asyncio
    async def test_list_for_tenant_profile_builds_from_registry(self):
        resolver = RegistryGrantResolver(self._registry())
        grants = await resolver.list_for_tenant_profile("tenant-a", "owner-core")
        assert "infra.inspect" in [g.capability_id for g in grants]
        assert await resolver.list_for_tenant_profile("tenant-b", "owner-core") == []


# ─── Orquestrador em database mode ─────────────────────────────────────────

class SpyAdapter:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def invoke_tool(self, tool_name, arguments, tenant_id, correlation_id):
        self.calls.append((tool_name, dict(arguments)))
        return {"success": True, "data": {"spy": True}}

    async def health(self) -> bool:
        return True


def _build_orchestrator(adapter, rows):
    registry = InMemoryCapabilityRegistry()
    registry.load_from_yaml()
    resource_resolver = InMemoryResourceResolver()
    resource_resolver.register("tenant-a", "prosperfy-main", {"host": "mock-vps-a.test", "type": "vps"})
    resource_resolver.register("tenant-b", "prosperfy-main", {"host": "mock-vps-b.test", "type": "vps"})
    audit_writer = InMemoryAuditWriter()
    telemetry_recorder = InMemoryTelemetryRecorder()
    orchestrator = ExecutionOrchestrator(
        registry=registry,
        policy_engine=PolicyEngine(),
        skills_adapter=adapter,
        audit_writer=audit_writer,
        telemetry_recorder=telemetry_recorder,
        resource_resolver=resource_resolver,
        grant_resolver=PostgresGrantResolver(repo=FakeGrantRepository(rows=rows)),
    )
    return orchestrator, audit_writer, telemetry_recorder


def _ctx(tenant, profile="owner-core"):
    return ActorContext(
        tenant_id=tenant,
        actor_id=f"actor-{tenant}",
        correlation_id=f"corr-{tenant}",
        credential_ref="ref",
        profile=profile,
    )


class TestDatabaseModeOrchestratorGrants:
    @pytest.mark.asyncio
    async def test_database_mode_grant_allows_execution(self):
        spy = SpyAdapter()
        orchestrator, _, _ = _build_orchestrator(
            spy, rows=[dict(GRANT_A)],
        )
        result = await orchestrator.execute(
            ctx=_ctx("tenant-a"),
            capability_id="infra.inspect",
            params={"resource": "prosperfy-main"},
        )
        assert result.status.value == "completed"
        assert len(spy.calls) > 0, "grant persistido no DB deve permitir execução"

    @pytest.mark.asyncio
    async def test_database_mode_no_grant_denies_without_adapter_call(self):
        spy = SpyAdapter()
        orchestrator, audit_writer, _ = _build_orchestrator(
            spy, rows=[dict(GRANT_A)],
        )
        result = await orchestrator.execute(
            ctx=_ctx("tenant-b"),  # tenant-b NÃO tem grant
            capability_id="infra.inspect",
            params={"resource": "prosperfy-main"},
        )
        assert result.status.value == "failed"
        assert "não possui grant" in (result.error or "")
        assert spy.calls == [], "sem grant → adapter NUNCA é chamado"
        events = audit_writer.get_all_for_tenant("tenant-b")
        assert events and events[-1].outcome.value == "denied"

    @pytest.mark.asyncio
    async def test_database_mode_wrong_profile_denies(self):
        spy = SpyAdapter()
        orchestrator, _, _ = _build_orchestrator(
            spy, rows=[dict(GRANT_A)],
        )
        result = await orchestrator.execute(
            ctx=_ctx("tenant-a", profile="observer"),
            capability_id="infra.inspect",
            params={"resource": "prosperfy-main"},
        )
        assert result.status.value == "failed"
        assert spy.calls == []

    @pytest.mark.asyncio
    async def test_database_mode_cross_tenant_grant_denied(self):
        """Defense-in-depth: mesmo que o repo devolva um grant de OUTRO tenant
        (simulando um bug de DB), o cross_tenant_guard do PolicyEngine nega."""
        spy = SpyAdapter()
        # Repo "buggy": ignora o tenant_id no match e devolve o grant de A
        # para qualquer pergunta.
        class LeakyRepo(FakeGrantRepository):
            async def get_grant(self, tenant_id, profile, capability_id):
                self.get_calls.append((tenant_id, profile, capability_id))
                return CapabilityGrant(**GRANT_A)

        registry = InMemoryCapabilityRegistry()
        registry.load_from_yaml()
        resource_resolver = InMemoryResourceResolver()
        resource_resolver.register("tenant-b", "prosperfy-main", {"host": "mock-vps-b.test", "type": "vps"})
        orchestrator = ExecutionOrchestrator(
            registry=registry,
            policy_engine=PolicyEngine(),
            skills_adapter=spy,
            audit_writer=InMemoryAuditWriter(),
            telemetry_recorder=InMemoryTelemetryRecorder(),
            resource_resolver=resource_resolver,
            grant_resolver=PostgresGrantResolver(repo=LeakyRepo(rows=[dict(GRANT_A)])),
        )
        result = await orchestrator.execute(
            ctx=_ctx("tenant-b"),
            capability_id="infra.inspect",
            params={"resource": "prosperfy-main"},
        )
        assert result.status.value == "failed"
        assert "Cross-tenant" in (result.error or "")
        assert spy.calls == []

    @pytest.mark.asyncio
    async def test_database_mode_db_error_fail_closed_deny(self):
        """Falha de DB na resolução → DENY, adapter nunca chamado."""
        spy = SpyAdapter()
        repo = FakeGrantRepository(rows=[dict(GRANT_A)])
        repo.fail_on = True
        registry = InMemoryCapabilityRegistry()
        registry.load_from_yaml()
        resource_resolver = InMemoryResourceResolver()
        resource_resolver.register("tenant-a", "prosperfy-main", {"host": "mock-vps-a.test", "type": "vps"})
        orchestrator = ExecutionOrchestrator(
            registry=registry,
            policy_engine=PolicyEngine(),
            skills_adapter=spy,
            audit_writer=InMemoryAuditWriter(),
            telemetry_recorder=InMemoryTelemetryRecorder(),
            resource_resolver=resource_resolver,
            grant_resolver=PostgresGrantResolver(repo=repo),
        )
        result = await orchestrator.execute(
            ctx=_ctx("tenant-a"),
            capability_id="infra.inspect",
            params={"resource": "prosperfy-main"},
        )
        assert result.status.value == "failed"
        assert "não possui grant" in (result.error or "")
        assert spy.calls == []

    @pytest.mark.asyncio
    async def test_idempotency_cache_includes_profile_no_bypass(self):
        """Revisão adversarial (Sprint 0.3 closure): um actor de perfil SEM
        grant reenviando a mesma idempotency_key não pode herdar o COMPLETED
        cacheado de um perfil COM grant — a cache key inclui ctx.profile."""
        spy = SpyAdapter()
        orchestrator, audit_writer, _ = _build_orchestrator(
            spy, rows=[dict(GRANT_A)],
        )
        k = "same-key-001"

        # 1) owner-core TEM grant → completes e popula a cache com a chave
        #    (tenant-a, owner-core, infra.inspect, k).
        first = await orchestrator.execute(
            ctx=_ctx("tenant-a", profile="owner-core"),
            capability_id="infra.inspect",
            params={"resource": "prosperfy-main"},
            idempotency_key=k,
        )
        assert first.status.value == "completed"
        first_calls = len(spy.calls)
        assert first_calls > 0

        # 2) MESMO tenant, MESMA capability, MESMA key, MAS profile 'observer'
        #    sem grant → deve ser DENY (refaz o grant check), nunca o COMPLETED
        #    cacheado; adapter não é chamado de novo.
        second = await orchestrator.execute(
            ctx=_ctx("tenant-a", profile="observer"),
            capability_id="infra.inspect",
            params={"resource": "prosperfy-main"},
            idempotency_key=k,
        )
        assert second.status.value == "failed"
        assert "não possui grant" in (second.error or "")
        assert len(spy.calls) == first_calls, "perfil sem grant → adapter NUNCA chamado"

        # 3) owner-core envia de novo a MESMA key → COMPLETED cacheado (dedup
        #    legítimo preservado e independente do profile abaixo).
        third = await orchestrator.execute(
            ctx=_ctx("tenant-a", profile="owner-core"),
            capability_id="infra.inspect",
            params={"resource": "prosperfy-main"},
            idempotency_key=k,
        )
        assert third.status.value == "completed"
        assert len(spy.calls) == first_calls, "reuso legítimo reusa cache sem nova execução"