"""
gateway/app.py — FastAPI application factory do Cognitive Gateway V2.

COGNITIVE_MODE=in_memory → retrocompat Sprint 0.1 (sem DB obrigatório)
COGNITIVE_MODE=database  → DB obrigatório; fail-closed se indisponível
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from ..adapters.prosperfy_skills.client import ProsperfySkillsAdapter
from ..adapters.prosperfy_skills.mock import MockSkillsAdapter
from ..audit.writer import InMemoryAuditWriter
from ..config.runtime import is_database_mode, is_in_memory_mode, require_database_config
from ..contracts.tenancy import CapabilityGrant
from ..execution.orchestrator import ExecutionOrchestrator
from ..execution.resource_resolver import InMemoryResourceResolver, ResourceResolver
from ..policy.engine import PolicyEngine
from ..registry.registry import InMemoryCapabilityRegistry
from ..registry.grant_resolver import RegistryGrantResolver
from ..telemetry.recorder import InMemoryTelemetryRecorder
from ..tenancy.identity_resolver import IdentityResolver
from .routes import capabilities, health, resources, status, trello_webhook
from .metadata import api_version, deployment_environment

logger = logging.getLogger(__name__)


def _require_live_mcp_secret() -> None:
    """
    Fail-closed eager check: COGNITIVE_LIVE_MCP=1 exige MCP_PROSPERFYSKILLS_API_KEY.

    Executa ANTES de construir o ProsperfySkillsAdapter — recusa a inicialização
    do gateway inteiro (nunca um warning silencioso). Defense in depth: o check
    tardio em ProsperfySkillsAdapter.invoke_tool() (client.py) permanece intacto
    para o caso de a env var ser removida após o startup sem restart do processo.

    Nunca interpola os.environ nem qualquer valor parcial/malformado na mensagem
    — não há valor a vazar (a variável está ausente/vazia), mas a mensagem também
    não deve revelar se algo foi tentado.
    """
    if os.getenv("MCP_PROSPERFYSKILLS_API_KEY", "").strip():
        return
    raise RuntimeError(
        "COGNITIVE_LIVE_MCP=1 exige MCP_PROSPERFYSKILLS_API_KEY configurada "
        "(env var ausente, vazia ou somente espaços). Configure o secret via "
        "EnvironmentFile do systemd (0600, service user) antes de iniciar o "
        "gateway — ver docs/cognitive-v2/COGNITIVE-DEPLOY-READINESS.md."
    )


def _build_services(app: FastAPI) -> None:
    """Constrói e injeta todos os serviços no app.state."""
    require_database_config()
    use_db = is_database_mode()

    registry = InMemoryCapabilityRegistry()
    registry.load_from_yaml()
    policy_engine = PolicyEngine()

    live_mcp = os.getenv("COGNITIVE_LIVE_MCP", "0") == "1"
    if live_mcp:
        _require_live_mcp_secret()
        logger.info("COGNITIVE_LIVE_MCP=1 — usando ProsperfySkillsAdapter real")
        skills_adapter = ProsperfySkillsAdapter()
    else:
        logger.info("COGNITIVE_LIVE_MCP=0 — usando MockSkillsAdapter (dev/CI)")
        skills_adapter = MockSkillsAdapter()

    if use_db:
        from ..db.repositories.audit_repo import PostgresAuditWriter
        from ..db.repositories.identity_repo import ServiceIdentityRepository
        from ..db.repositories.resource_repo import TenantResourceRepository
        from ..db.repositories.telemetry_repo import PostgresTelemetryRecorder
        from ..db.repositories.tenancy_repo import GrantRepository
        from ..db.repositories.work_repo import (
            IdeaRepository,
            ProjectRepository,
            TaskRepository,
            WorkEventRepository,
            WorkLinkRepository,
        )
        from ..db.repositories.work_trello_repo import (
            SyncOutboxRepository,
            TrelloBindingRepository,
        )
        from ..registry.grant_resolver import PostgresGrantResolver
        from ..adapters.work_management.adapter import WorkManagementAdapter
        from ..services.work_service import WorkService

        audit_writer = PostgresAuditWriter()
        # Sprint 0.3 (fechamento E2E): antes deste fix, telemetry_recorder
        # era fiado incondicionalmente como InMemoryTelemetryRecorder mais
        # abaixo (fora deste if/else) — cost_telemetry nunca recebia linha
        # nenhuma em database mode, só audit_events persistia de verdade.
        telemetry_recorder = PostgresTelemetryRecorder()
        identity_resolver = IdentityResolver(
            identity_repo=ServiceIdentityRepository(),
            database_mode=True,
        )
        resource_repo = TenantResourceRepository()
        # SEC/ADR-V2-002 §3 (Sprint 0.3): resolve params.resource -> concretos
        # antes do adapter. Sem isso, ExecutionOrchestrator recebia
        # resource_resolver=None e "resource" lógico ia cru pro adapter.
        resource_resolver = ResourceResolver(resource_repo)
        # Sprint 0.3 RETURN_TO_DEV (Item A): em database mode a resolução de
        # grant passa a consultar capability_grants via GrantRepository (RLS
        # por tenant_transaction). Sem este wiring, grants persistidos eram
        # ignorados → todo tenant em database mode levava DENY [no_grant].
        grant_resolver = PostgresGrantResolver(repo=GrantRepository())
        # Track P1 (Work Management): WorkService/WorkManagementAdapter só
        # existem em database mode — o domínio inteiro (work_ideas/
        # work_projects/work_tasks/...) é Postgres-backed via
        # tenant_transaction (RLS), sem fallback in-memory (mesmo padrão de
        # audit_writer/telemetry_recorder acima).
        work_service = WorkService(
            idea_repo=IdeaRepository(),
            project_repo=ProjectRepository(),
            task_repo=TaskRepository(),
            link_repo=WorkLinkRepository(),
            event_repo=WorkEventRepository(),
            outbox_repo=SyncOutboxRepository(),
            binding_repo=TrelloBindingRepository(),
        )
        extra_adapters: dict[str, object] = {
            "work_management": WorkManagementAdapter(work_service),
        }
        logger.info("Runtime: database mode (Postgres) — work_management adapter ativo")

        # Track P1: TrelloSyncEngine — SEMPRE construído em database mode
        # (é só objeto Python; TrelloClient.is_configured() é checado em
        # runtime por cada operação). Sem TRELLO_API_KEY/TRELLO_TOKEN, todo
        # drain/reconcile vira no-op (skipped_not_configured) — nunca
        # levanta no startup. Isso é o que permite reportar
        # HUMAN_BLOCKER=TRELLO_AUTH sem travar o resto do gateway.
        from ..adapters.trello.client import TrelloClient
        from ..adapters.trello.sync import TrelloSyncEngine

        trello_sync_engine = TrelloSyncEngine(
            client=TrelloClient(),
            idea_repo=IdeaRepository(),
            project_repo=ProjectRepository(),
            task_repo=TaskRepository(),
            binding_repo=TrelloBindingRepository(),
            outbox_repo=SyncOutboxRepository(),
            event_repo=WorkEventRepository(),
        )
    else:
        audit_writer = InMemoryAuditWriter()
        telemetry_recorder = InMemoryTelemetryRecorder()
        identity_resolver = IdentityResolver(identity_repo=None, database_mode=False)
        resource_resolver = InMemoryResourceResolver()
        # Sem DB não há WorkService (precisa de tenant_transaction/pool real)
        # — capabilities work.* registradas mas sem adapter extra caem no
        # fallback (skills_adapter) e falham de forma explícita, nunca
        # silenciosa (RuntimeError "capability desconhecida" no skills mock).
        extra_adapters = {}
        trello_sync_engine = None
        # Mesmo resolvedor que o orchestrator usa por default em in-memory:
        # exposto no app.state para a rota de descoberta aplicar a mesma
        # elegibilidade por grant (sem grant → lista vazia).
        grant_resolver = RegistryGrantResolver(registry)
        dev_tenant = os.getenv("COGNITIVE_DEV_TENANT_ID", "prosperfy")
        resource_resolver.register(
            dev_tenant, "prosperfy-main",
            {"host": "mock-vps.prosperfy.com.br", "type": "vps"},
        )
        resource_repo = None
        dev_credential = os.getenv("COGNITIVE_GATEWAY_CREDENTIAL", "dev-secret")
        dev_actor = os.getenv("COGNITIVE_DEV_ACTOR_ID", "william")
        identity_resolver.register_static(dev_credential, dev_tenant, dev_actor, "owner-core")
        logger.info("Runtime: in_memory mode")

    orchestrator = ExecutionOrchestrator(
        registry=registry,
        policy_engine=policy_engine,
        skills_adapter=skills_adapter,
        audit_writer=audit_writer,
        telemetry_recorder=telemetry_recorder,
        resource_resolver=resource_resolver,
        grant_resolver=grant_resolver,
        adapters=extra_adapters,
    )

    if is_in_memory_mode():
        dev_tenant = os.getenv("COGNITIVE_DEV_TENANT_ID", "prosperfy")
        for cap in registry.list_all():
            registry.register_grant(CapabilityGrant(
                tenant_id=dev_tenant,
                profile="owner-core",
                capability_id=cap.id,
            ))

    app.state.registry = registry
    app.state.orchestrator = orchestrator
    app.state.grant_resolver = grant_resolver
    app.state.audit_writer = audit_writer
    app.state.telemetry_recorder = telemetry_recorder
    app.state.identity_resolver = identity_resolver
    app.state.resource_resolver = resource_resolver
    app.state.use_db = use_db
    app.state.resource_repo = resource_repo if use_db else None
    app.state.trello_sync_engine = trello_sync_engine
    app.state.trello_board_binding = None  # preenchido best-effort no lifespan (precisa de I/O async)


async def _trello_background_loop(app: FastAPI) -> None:
    """Task de background: drena outbox (DB->Trello) e reconcilia por
    polling (Trello->DB, fallback do webhook). Gated por
    COGNITIVE_TRELLO_POLL_ENABLED=1 (default OFF — nunca liga sozinho).
    Ambos os métodos do TrelloSyncEngine já são no-op seguro sem
    TRELLO_API_KEY/TRELLO_TOKEN (ver client.is_configured())."""
    import asyncio

    interval = float(os.getenv("COGNITIVE_TRELLO_POLL_INTERVAL_SECONDS", "90"))
    dev_tenant = os.getenv("COGNITIVE_DEV_TENANT_ID", "prosperfy")
    engine = app.state.trello_sync_engine
    while True:
        try:
            drained = await engine.drain_outbox_once(dev_tenant)
            reconciled = await engine.reconcile_poll(dev_tenant)
            if drained.get("processed") or reconciled.get("scanned"):
                logger.info("trello_background_loop drained=%s reconciled=%s", drained, reconciled)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("trello_background_loop: iteração falhou (non-fatal, retry no próximo ciclo)")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle: startup — inicializa pools DB (+ Trello board binding
    best-effort + background loop opcional). shutdown — fecha pools."""
    trello_task = None
    if is_database_mode():
        from ..db.connection import create_pools, close_pools

        db_url = os.getenv("COGNITIVE_DB_URL")
        worker_url = os.getenv("COGNITIVE_DB_WORKER_URL")
        admin_url = os.getenv("COGNITIVE_DB_ADMIN_URL")
        await create_pools(app_dsn=db_url, worker_dsn=worker_url, admin_dsn=admin_url)
        logger.info("DB pools inicializados")

        if app.state.trello_sync_engine is not None:
            dev_tenant = os.getenv("COGNITIVE_DEV_TENANT_ID", "prosperfy")
            try:
                app.state.trello_board_binding = await app.state.trello_sync_engine.get_board_binding(dev_tenant)
            except Exception:
                logger.warning("lifespan: board Trello ainda não vinculado (ou DB indisponível no startup)")

            if os.getenv("COGNITIVE_TRELLO_POLL_ENABLED", "0") == "1":
                import asyncio
                trello_task = asyncio.create_task(_trello_background_loop(app))
                logger.info("Trello background loop iniciado (outbox drain + reconciliation poll)")
            else:
                logger.info("COGNITIVE_TRELLO_POLL_ENABLED=0 — Trello sync só sob demanda (sem loop de fundo)")

    yield

    if trello_task is not None:
        trello_task.cancel()
    if is_database_mode():
        from ..db.connection import close_pools
        await close_pools()
        logger.info("DB pools encerrados")


def create_app() -> FastAPI:
    """Cria e configura a FastAPI application do Cognitive Gateway."""
    env = deployment_environment()
    app = FastAPI(
        title="Prosperfy Cognitive API",
        description=(
            "Prosperfy Cognitive Core V2 — Gateway independente do Hermes (ADR-V2-005). "
            f"Environment: {env}."
        ),
        version=api_version(),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    cors_origins = [
        o.strip()
        for o in os.getenv("COGNITIVE_CORS_ORIGINS", "").split(",")
        if o.strip()
    ]
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "X-Tenant-Id",
                "X-Actor-Id",
                "X-Correlation-Id",
            ],
        )

    _build_services(app)

    app.include_router(health.router)
    app.include_router(status.router)
    app.include_router(capabilities.router)
    app.include_router(resources.router)
    app.include_router(trello_webhook.router)

    logger.info(
        "Prosperfy Cognitive API v%s env=%s capabilities=%d mode=%s",
        api_version(),
        deployment_environment(),
        len(app.state.registry.list_all()),
        "database" if app.state.use_db else "in_memory",
    )
    return app


app = create_app()
