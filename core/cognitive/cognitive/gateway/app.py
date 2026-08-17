"""
gateway/app.py — FastAPI application factory do Cognitive Gateway V2.

COGNITIVE_MODE=in_memory → retrocompat Sprint 0.1 (sem DB obrigatório)
COGNITIVE_MODE=database  → DB obrigatório; fail-closed se indisponível
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from contextlib import asynccontextmanager

from ..adapters.prosperfy_skills.client import ProsperfySkillsAdapter
from ..adapters.prosperfy_skills.mock import MockSkillsAdapter
from ..audit.writer import InMemoryAuditWriter
from ..config.runtime import is_database_mode, is_in_memory_mode, require_database_config
from ..contracts.tenancy import CapabilityGrant
from ..execution.orchestrator import ExecutionOrchestrator
from ..execution.resource_resolver import InMemoryResourceResolver
from ..policy.engine import PolicyEngine
from ..registry.registry import InMemoryCapabilityRegistry
from ..telemetry.recorder import InMemoryTelemetryRecorder
from ..tenancy.identity_resolver import IdentityResolver
from .routes import capabilities, health, status

logger = logging.getLogger(__name__)


def _build_services(app: FastAPI) -> None:
    """Constrói e injeta todos os serviços no app.state."""
    require_database_config()
    use_db = is_database_mode()

    registry = InMemoryCapabilityRegistry()
    registry.load_from_yaml()
    policy_engine = PolicyEngine()

    live_mcp = os.getenv("COGNITIVE_LIVE_MCP", "0") == "1"
    if live_mcp:
        logger.info("COGNITIVE_LIVE_MCP=1 — usando ProsperfySkillsAdapter real")
        skills_adapter = ProsperfySkillsAdapter()
    else:
        logger.info("COGNITIVE_LIVE_MCP=0 — usando MockSkillsAdapter (dev/CI)")
        skills_adapter = MockSkillsAdapter()

    if use_db:
        from ..db.repositories.audit_repo import PostgresAuditWriter
        from ..db.repositories.identity_repo import ServiceIdentityRepository
        from ..db.repositories.resource_repo import TenantResourceRepository

        audit_writer = PostgresAuditWriter()
        identity_resolver = IdentityResolver(
            identity_repo=ServiceIdentityRepository(),
            database_mode=True,
        )
        resource_resolver = None
        resource_repo = TenantResourceRepository()
        logger.info("Runtime: database mode (Postgres)")
    else:
        audit_writer = InMemoryAuditWriter()
        identity_resolver = IdentityResolver(identity_repo=None, database_mode=False)
        resource_resolver = InMemoryResourceResolver()
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

    telemetry_recorder = InMemoryTelemetryRecorder()

    orchestrator = ExecutionOrchestrator(
        registry=registry,
        policy_engine=policy_engine,
        skills_adapter=skills_adapter,
        audit_writer=audit_writer,
        telemetry_recorder=telemetry_recorder,
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
    app.state.audit_writer = audit_writer
    app.state.telemetry_recorder = telemetry_recorder
    app.state.identity_resolver = identity_resolver
    app.state.resource_resolver = resource_resolver
    app.state.use_db = use_db
    app.state.resource_repo = resource_repo if use_db else None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle: startup — inicializa pools DB. shutdown — fecha pools."""
    if is_database_mode():
        from ..db.connection import create_pools, close_pools

        db_url = os.getenv("COGNITIVE_DB_URL")
        worker_url = os.getenv("COGNITIVE_DB_WORKER_URL")
        admin_url = os.getenv("COGNITIVE_DB_ADMIN_URL")
        await create_pools(app_dsn=db_url, worker_dsn=worker_url, admin_dsn=admin_url)
        logger.info("DB pools inicializados")

    yield

    if is_database_mode():
        from ..db.connection import close_pools
        await close_pools()
        logger.info("DB pools encerrados")


def create_app() -> FastAPI:
    """Cria e configura a FastAPI application do Cognitive Gateway."""
    app = FastAPI(
        title="Prosperfy Cognitive Gateway",
        description="Cognitive Core V2 — independente do Hermes (ADR-V2-005)",
        version="0.2.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    _build_services(app)

    app.include_router(health.router)
    app.include_router(status.router)
    app.include_router(capabilities.router)

    logger.info(
        "Cognitive Gateway v0.2.0 — capabilities=%d mode=%s",
        len(app.state.registry.list_all()),
        "database" if app.state.use_db else "in_memory",
    )
    return app


app = create_app()
