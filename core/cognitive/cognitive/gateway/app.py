"""
gateway/app.py — FastAPI application factory do Cognitive Gateway.

Monta a aplicação com todos os serviços injetados via app.state.
Clientes: Hermes (futuro), Finance App, bots, workers — nunca específico do Hermes.
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI

from ..adapters.prosperfy_skills.client import ProsperfySkillsAdapter
from ..adapters.prosperfy_skills.mock import MockSkillsAdapter
from ..audit.writer import InMemoryAuditWriter
from ..contracts.tenancy import CapabilityGrant
from ..execution.orchestrator import ExecutionOrchestrator
from ..policy.engine import PolicyEngine
from ..registry.registry import InMemoryCapabilityRegistry
from ..telemetry.recorder import InMemoryTelemetryRecorder
from ..tenancy.context import register_static_credential
from .routes import capabilities, health, status

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """
    Cria e configura a FastAPI application do Cognitive Gateway.

    Serviços injetados via app.state (Sprint 0.1: in-memory).
    """
    app = FastAPI(
        title="Prosperfy Cognitive Gateway",
        description="Cognitive Core V2 — independente do Hermes (ADR-V2-005)",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ─── Serviços ────────────────────────────────────────────────────────
    registry = InMemoryCapabilityRegistry()
    registry.load_from_yaml()

    policy_engine = PolicyEngine()
    audit_writer = InMemoryAuditWriter()
    telemetry_recorder = InMemoryTelemetryRecorder()

    # Adapter: mock por default; real quando COGNITIVE_LIVE_MCP=1
    live_mcp = os.getenv("COGNITIVE_LIVE_MCP", "0") == "1"
    if live_mcp:
        logger.info("COGNITIVE_LIVE_MCP=1 — usando ProsperfySkillsAdapter real")
        skills_adapter = ProsperfySkillsAdapter()
    else:
        logger.info("COGNITIVE_LIVE_MCP=0 — usando MockSkillsAdapter (default dev/CI)")
        skills_adapter = MockSkillsAdapter()

    orchestrator = ExecutionOrchestrator(
        registry=registry,
        policy_engine=policy_engine,
        skills_adapter=skills_adapter,
        audit_writer=audit_writer,
        telemetry_recorder=telemetry_recorder,
    )

    # ─── Injeção via app.state ───────────────────────────────────────────
    app.state.registry = registry
    app.state.orchestrator = orchestrator
    app.state.audit_writer = audit_writer
    app.state.telemetry_recorder = telemetry_recorder

    # ─── Credenciais estáticas de desenvolvimento ────────────────────────
    # Sprint 0.1: credential estática. Sprint 0.4+: service_identities no banco.
    dev_credential = os.getenv("COGNITIVE_GATEWAY_CREDENTIAL", "dev-secret")
    dev_tenant = os.getenv("COGNITIVE_DEV_TENANT_ID", "prosperfy")
    dev_actor = os.getenv("COGNITIVE_DEV_ACTOR_ID", "william")
    register_static_credential(dev_credential, dev_tenant, dev_actor, profile="owner-core")

    # ─── Grant dev: todos os capabilities para o tenant dev ──────────────
    for cap in registry.list_all():
        registry.register_grant(CapabilityGrant(
            tenant_id=dev_tenant,
            profile="owner-core",
            capability_id=cap.id,
        ))

    # ─── Rotas ──────────────────────────────────────────────────────────
    app.include_router(health.router)
    app.include_router(status.router)
    app.include_router(capabilities.router)

    logger.info(
        "Cognitive Gateway iniciado — tenants registrados, capabilities=%d",
        len(registry.list_all()),
    )
    return app


app = create_app()
