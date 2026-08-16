"""
gateway/app.py — FastAPI application factory do Cognitive Gateway V2.

Sprint 0.2: suporta DB (asyncpg) quando COGNITIVE_DB_URL disponível.
            Fallback automático para in-memory (Sprint 0.1 retrocompat.).

Serviços injetados via app.state.
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from contextlib import asynccontextmanager

from ..adapters.prosperfy_skills.client import ProsperfySkillsAdapter
from ..adapters.prosperfy_skills.mock import MockSkillsAdapter
from ..audit.writer import InMemoryAuditWriter
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
    # ─── Registry ───────────────────────────────────────────────────────
    registry = InMemoryCapabilityRegistry()
    registry.load_from_yaml()

    # ─── Policy ─────────────────────────────────────────────────────────
    policy_engine = PolicyEngine()

    # ─── Adapter ────────────────────────────────────────────────────────
    live_mcp = os.getenv("COGNITIVE_LIVE_MCP", "0") == "1"
    if live_mcp:
        logger.info("COGNITIVE_LIVE_MCP=1 — usando ProsperfySkillsAdapter real")
        skills_adapter = ProsperfySkillsAdapter()
    else:
        logger.info("COGNITIVE_LIVE_MCP=0 — usando MockSkillsAdapter (dev/CI)")
        skills_adapter = MockSkillsAdapter()

    # ─── Audit + Telemetry ───────────────────────────────────────────────
    db_url = os.getenv("COGNITIVE_DB_URL")
    use_db = bool(db_url)

    if use_db:
        from ..db.repositories.audit_repo import PostgresAuditWriter
        audit_writer = PostgresAuditWriter()
        logger.info("Audit: PostgresAuditWriter (DB disponível)")
    else:
        audit_writer = InMemoryAuditWriter()
        logger.info("Audit: InMemoryAuditWriter (sem COGNITIVE_DB_URL)")

    telemetry_recorder = InMemoryTelemetryRecorder()

    # ─── Resource Resolver ───────────────────────────────────────────────
    if use_db:
        from ..db.repositories.resource_repo import TenantResourceRepository
        resource_resolver = None  # lazy init — ResourceResolver usa TenantResourceRepository
        # Injetado separadamente para que routes possam acessar
        resource_repo = TenantResourceRepository()
    else:
        resource_resolver = InMemoryResourceResolver()
        # Seed resource dev para testes sem DB
        dev_tenant = os.getenv("COGNITIVE_DEV_TENANT_ID", "prosperfy")
        resource_resolver.register(
            dev_tenant, "prosperfy-main",
            {"host": "mock-vps.prosperfy.com.br", "type": "vps"},
        )
        resource_repo = None

    # ─── Identity Resolver ───────────────────────────────────────────────
    if use_db:
        from ..db.repositories.identity_repo import ServiceIdentityRepository
        identity_resolver = IdentityResolver(identity_repo=ServiceIdentityRepository())
        logger.info("Identity: ServiceIdentityRepository (DB)")
    else:
        identity_resolver = IdentityResolver(identity_repo=None)
        # Credencial dev estática
        dev_credential = os.getenv("COGNITIVE_GATEWAY_CREDENTIAL", "dev-secret")
        dev_tenant = os.getenv("COGNITIVE_DEV_TENANT_ID", "prosperfy")
        dev_actor = os.getenv("COGNITIVE_DEV_ACTOR_ID", "william")
        identity_resolver.register_static(dev_credential, dev_tenant, dev_actor, "owner-core")
        logger.info("Identity: static in-memory (sem COGNITIVE_DB_URL)")

    # ─── Orchestrator ────────────────────────────────────────────────────
    orchestrator = ExecutionOrchestrator(
        registry=registry,
        policy_engine=policy_engine,
        skills_adapter=skills_adapter,
        audit_writer=audit_writer,
        telemetry_recorder=telemetry_recorder,
    )

    # ─── Grants dev (in-memory sem DB) ──────────────────────────────────
    if not use_db:
        dev_tenant = os.getenv("COGNITIVE_DEV_TENANT_ID", "prosperfy")
        for cap in registry.list_all():
            registry.register_grant(CapabilityGrant(
                tenant_id=dev_tenant,
                profile="owner-core",
                capability_id=cap.id,
            ))

    # ─── Injeção via app.state ───────────────────────────────────────────
    app.state.registry = registry
    app.state.orchestrator = orchestrator
    app.state.audit_writer = audit_writer
    app.state.telemetry_recorder = telemetry_recorder
    app.state.identity_resolver = identity_resolver
    app.state.resource_resolver = resource_resolver
    app.state.use_db = use_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle: startup — inicializa pools DB. shutdown — fecha pools."""
    db_url = os.getenv("COGNITIVE_DB_URL")
    worker_url = os.getenv("COGNITIVE_DB_WORKER_URL")
    admin_url = os.getenv("COGNITIVE_DB_ADMIN_URL")

    if db_url:
        from ..db.connection import create_pools, close_pools
        await create_pools(app_dsn=db_url, worker_dsn=worker_url, admin_dsn=admin_url)
        logger.info("DB pools inicializados")

    yield  # app rodando

    if db_url:
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
        "Cognitive Gateway v0.2.0 — capabilities=%d use_db=%s",
        len(app.state.registry.list_all()),
        app.state.use_db,
    )
    return app


app = create_app()
