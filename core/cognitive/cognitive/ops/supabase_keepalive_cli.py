"""
ops/supabase_keepalive_cli.py — Entrypoint determinístico do scheduler de
keepalive Supabase (P0). Disparado pelo systemd timer
(ops/supabase-ops/supabase-keepalive.timer), NUNCA por uma conversa do LLM
— zero import de qualquer cliente LLM neste módulo
(NORMAL_CHAT_ROUTER_LLM_CALLS=0 também vale aqui).

Uso:
    COGNITIVE_DB_URL=... COGNITIVE_DB_ADMIN_URL=... \\
    COGNITIVE_LIVE_COMPOSIO_MCP=1 COMPOSIO_MCP_URL=... COMPOSIO_MCP_API_KEY=... \\
    COGNITIVE_TENANT_SLUG=prosperfy-homolog \\
    python -m cognitive.ops.supabase_keepalive_cli

Exit code:
    0 — round executado (mesmo com falhas PARCIAIS de projeto — essas são
        esperadas/tratadas por projeto, doc §9: não é motivo de systemd
        marcar a unit como failed; ver KeepaliveRoundResult.failure_count
        no log/stdout).
    1 — falha FATAL antes/fora do round (config ausente, DB inacessível,
        tenant não encontrado, Compose MCP não configurado) — aí sim a
        unit deve ficar failed para o systemd timer/journal sinalizar.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

logger = logging.getLogger("cognitive.ops.supabase_keepalive")


def _configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("COGNITIVE_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _build_service():
    """Monta o SupabaseKeepaliveService com adapters/repos REAIS — mesmo
    padrão de live-mode de gateway/app.py._build_services(), sem FastAPI em
    volta (script standalone, sem servidor HTTP, chamado direto pelo
    systemd timer)."""
    from ..adapters.composio.client import ComposioMcpAdapter
    from ..adapters.supabase_registry.adapter import SupabaseRegistryAdapter
    from ..db.connection import create_pools
    from ..db.repositories.audit_repo import PostgresAuditWriter
    from ..db.repositories.resource_repo import TenantResourceRepository
    from ..db.repositories.supabase_ops_repo import (
        SupabaseKeepaliveRunRepository,
        SupabaseProjectRepository,
    )
    from ..db.repositories.telemetry_repo import PostgresTelemetryRecorder
    from ..db.repositories.tenancy_repo import GrantRepository, TenantRepository
    from ..execution.orchestrator import ExecutionOrchestrator
    from ..execution.resource_resolver import ResourceResolver
    from ..execution.supabase_keepalive_service import SupabaseKeepaliveService
    from ..policy.engine import PolicyEngine
    from ..registry.grant_resolver import PostgresGrantResolver
    from ..registry.registry import InMemoryCapabilityRegistry

    db_url = os.getenv("COGNITIVE_DB_URL")
    admin_url = os.getenv("COGNITIVE_DB_ADMIN_URL")
    worker_url = os.getenv("COGNITIVE_DB_WORKER_URL")
    if not db_url:
        raise RuntimeError("COGNITIVE_DB_URL ausente — scheduler exige database mode.")
    if not admin_url:
        raise RuntimeError(
            "COGNITIVE_DB_ADMIN_URL ausente — supabase_projects usa "
            "admin_connection() para os writes do registry (mesmo padrão de "
            "TenantResourceRepository.upsert em resource_repo.py)."
        )
    await create_pools(app_dsn=db_url, worker_dsn=worker_url, admin_dsn=admin_url)

    tenant_slug = os.getenv("COGNITIVE_TENANT_SLUG", "prosperfy-homolog")
    tenant = await TenantRepository().get_by_slug(tenant_slug)
    if tenant is None:
        raise RuntimeError(f"Tenant '{tenant_slug}' não encontrado (COGNITIVE_TENANT_SLUG).")

    registry = InMemoryCapabilityRegistry()
    registry.load_from_yaml()

    live_composio = os.getenv("COGNITIVE_LIVE_COMPOSIO_MCP", "0") == "1"
    if not live_composio:
        raise RuntimeError(
            "COGNITIVE_LIVE_COMPOSIO_MCP != 1 — o scheduler é um caminho live "
            "por definição (doc §4.1: nunca usar conversa do LLM nem mock pra "
            "acordar o keepalive real)."
        )
    composio_adapter = ComposioMcpAdapter()

    registry_adapter = SupabaseRegistryAdapter(
        project_repo=SupabaseProjectRepository(),
        run_repo=SupabaseKeepaliveRunRepository(),
    )

    orchestrator = ExecutionOrchestrator(
        registry=registry,
        policy_engine=PolicyEngine(),
        # Fallback nunca deveria ser exercido por nenhuma capability supabase.*
        # — usar o registry_adapter aqui (em vez do ProsperfySkillsAdapter) evita
        # que este script precise de MCP_PROSPERFYSKILLS_API_KEY, que não tem
        # nenhuma relação com este scheduler.
        skills_adapter=registry_adapter,
        audit_writer=PostgresAuditWriter(),
        telemetry_recorder=PostgresTelemetryRecorder(),
        resource_resolver=ResourceResolver(TenantResourceRepository()),
        grant_resolver=PostgresGrantResolver(repo=GrantRepository()),
        composio_adapter=composio_adapter,
        registry_adapter=registry_adapter,
    )

    service = SupabaseKeepaliveService(
        orchestrator,
        project_repo=SupabaseProjectRepository(),
        run_repo=SupabaseKeepaliveRunRepository(),
    )
    # TenantRepository devolve id como uuid.UUID. Todo o caminho abaixo
    # (run_all -> repositories -> tenant_transaction) tipa tenant_id como str,
    # e set_config('app.current_tenant_id', $1, true) exige TEXT — passar o
    # UUID cru quebra com DataError no primeiro acesso ao banco. Coerção feita
    # aqui, na fronteira, para o resto do fluxo receber o tipo que declara.
    return service, str(tenant.id)


async def _run() -> int:
    from ..db.connection import close_pools

    service, tenant_id = await _build_service()
    try:
        result = await service.run_all(tenant_id=tenant_id, triggered_by="scheduler")
    finally:
        await close_pools()

    summary = result.to_dict()
    logger.info("KEEPALIVE_ROUND %s", json.dumps(summary, ensure_ascii=False))
    for alert in result.alerts:
        logger.warning(
            "KEEPALIVE_ALERT project_ref=%s consecutive_failures=%d error_code=%s",
            alert.project_ref, alert.consecutive_failures, alert.error_code,
        )
    print(json.dumps(summary, ensure_ascii=False))
    return 0  # falhas PARCIAIS de projeto nunca viram exit != 0 (isolamento — doc §9)


def main() -> int:
    _configure_logging()
    try:
        return asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 — falha FATAL (fora do loop por projeto)
        logger.error("KEEPALIVE_ROUND_FATAL %s: %s", type(exc).__name__, exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
