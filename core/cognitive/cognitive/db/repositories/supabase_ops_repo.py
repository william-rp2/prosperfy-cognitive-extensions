"""
db/repositories/supabase_ops_repo.py — Repositórios de Supabase Ops (P0).

supabase_projects: registry local dos projetos Supabase conectados via
Compose MCP (plano, keepalive_enabled, status operacional). Escrita via
admin_connection — mesmo padrão de TenantResourceRepository.upsert em
resource_repo.py. Leitura via tenant_transaction (RLS enforced).

supabase_keepalive_runs: histórico append-only de execuções. Mesmo padrão de
PostgresAuditWriter (audit_repo.py) — INSERT e SELECT via tenant_transaction
(RLS + WITH CHECK garantem tenant_id correto).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..connection import admin_connection, tenant_transaction

logger = logging.getLogger(__name__)


@dataclass
class SupabaseProjectRow:
    id: str
    tenant_id: str
    composio_account: str
    project_ref: str
    display_name: str
    region: str | None
    plan: str
    plan_source: str
    keepalive_enabled: bool
    status: str
    last_success_at: datetime | None
    last_latency_ms: int | None
    consecutive_failures: int
    last_error_code: str | None
    next_run_at: datetime | None
    active: bool


@dataclass
class SupabaseKeepaliveRunRow:
    id: str
    tenant_id: str
    project_id: str
    started_at: datetime
    ended_at: datetime
    status: str
    latency_ms: int | None
    error_code: str | None
    error_message: str | None
    triggered_by: str
    correlation_id: str
    created_at: datetime


_PROJECT_COLUMNS = (
    "id, tenant_id, composio_account, project_ref, display_name, region, "
    "plan, plan_source, keepalive_enabled, status, last_success_at, "
    "last_latency_ms, consecutive_failures, last_error_code, next_run_at, active"
)


def _row_to_project(row: Any) -> SupabaseProjectRow:
    return SupabaseProjectRow(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        composio_account=row["composio_account"],
        project_ref=row["project_ref"],
        display_name=row["display_name"],
        region=row["region"],
        plan=row["plan"],
        plan_source=row["plan_source"],
        keepalive_enabled=row["keepalive_enabled"],
        status=row["status"],
        last_success_at=row["last_success_at"],
        last_latency_ms=row["last_latency_ms"],
        consecutive_failures=row["consecutive_failures"],
        last_error_code=row["last_error_code"],
        next_run_at=row["next_run_at"],
        active=row["active"],
    )


def _row_to_run(row: Any) -> SupabaseKeepaliveRunRow:
    return SupabaseKeepaliveRunRow(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        project_id=str(row["project_id"]),
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        status=row["status"],
        latency_ms=row["latency_ms"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        triggered_by=row["triggered_by"],
        correlation_id=row["correlation_id"],
        created_at=row["created_at"],
    )


class SupabaseProjectRepository:
    """Registry de projetos Supabase conectados (plano, keepalive, status operacional)."""

    async def upsert(
        self,
        tenant_id: str,
        composio_account: str,
        project_ref: str,
        display_name: str,
        region: str | None = None,
        plan: str = "unknown",
        plan_source: str = "undetermined",
        keepalive_enabled: bool = False,
    ) -> SupabaseProjectRow:
        """Cria ou atualiza METADADOS de um projeto (descoberta/reconciliação
        com o Compose MCP). Nunca mexe em status/last_success_at/
        consecutive_failures — isso é exclusivo de record_run_result()."""
        async with admin_connection() as conn:
            row = await conn.fetchrow(
                f"""
                INSERT INTO supabase_projects(
                    tenant_id, composio_account, project_ref, display_name,
                    region, plan, plan_source, keepalive_enabled
                ) VALUES($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (tenant_id, project_ref)
                DO UPDATE SET
                    composio_account  = EXCLUDED.composio_account,
                    display_name      = EXCLUDED.display_name,
                    region            = EXCLUDED.region,
                    plan              = EXCLUDED.plan,
                    plan_source       = EXCLUDED.plan_source,
                    keepalive_enabled = EXCLUDED.keepalive_enabled,
                    active            = true,
                    updated_at        = NOW()
                RETURNING {_PROJECT_COLUMNS}
                """,
                uuid.UUID(tenant_id), composio_account, project_ref, display_name,
                region, plan, plan_source, keepalive_enabled,
            )
        return _row_to_project(row)

    async def list_all(self, tenant_id: str) -> list[SupabaseProjectRow]:
        async with tenant_transaction(tenant_id) as conn:
            rows = await conn.fetch(
                f"SELECT {_PROJECT_COLUMNS} FROM supabase_projects "
                "WHERE tenant_id = $1 AND active = true ORDER BY display_name",
                uuid.UUID(tenant_id),
            )
        return [_row_to_project(r) for r in rows]

    async def list_keepalive_enabled(self, tenant_id: str) -> list[SupabaseProjectRow]:
        async with tenant_transaction(tenant_id) as conn:
            rows = await conn.fetch(
                f"SELECT {_PROJECT_COLUMNS} FROM supabase_projects "
                "WHERE tenant_id = $1 AND active = true AND keepalive_enabled = true "
                "ORDER BY display_name",
                uuid.UUID(tenant_id),
            )
        return [_row_to_project(r) for r in rows]

    async def get_by_ref(self, tenant_id: str, project_ref: str) -> SupabaseProjectRow | None:
        async with tenant_transaction(tenant_id) as conn:
            row = await conn.fetchrow(
                f"SELECT {_PROJECT_COLUMNS} FROM supabase_projects "
                "WHERE tenant_id = $1 AND project_ref = $2",
                uuid.UUID(tenant_id), project_ref,
            )
        return _row_to_project(row) if row else None

    async def find_by_name(self, tenant_id: str, name_query: str) -> list[SupabaseProjectRow]:
        """Busca case-insensitive por display_name (WhatsApp: 'Teste agora o Supabase X')."""
        async with tenant_transaction(tenant_id) as conn:
            rows = await conn.fetch(
                f"SELECT {_PROJECT_COLUMNS} FROM supabase_projects "
                "WHERE tenant_id = $1 AND active = true AND display_name ILIKE $2 "
                "ORDER BY display_name",
                uuid.UUID(tenant_id), f"%{name_query}%",
            )
        return [_row_to_project(r) for r in rows]

    async def record_run_result(
        self,
        tenant_id: str,
        project_id: str,
        run_status: str,
        latency_ms: int | None,
        error_code: str | None,
        next_run_at: datetime | None,
    ) -> dict[str, Any]:
        """
        Atualiza o estado operacional do projeto após UMA execução.

        run_status: 'success' | 'failure' (vocabulário de
        supabase_keepalive_runs.status — 'skipped' nunca chega aqui, não
        muda o estado operacional). 'failure' incrementa
        consecutive_failures atomicamente (CASE lê o valor PRÉ-update, sem
        race); status vira 'failed' na 2ª falha consecutiva (doc §8: "2
        falhas consecutivas: alerta"), 'warning' na 1ª.

        Retorna {status, consecutive_failures} pós-update, para o service
        decidir se dispara alerta.
        """
        async with admin_connection() as conn:
            if run_status == "success":
                row = await conn.fetchrow(
                    """
                    UPDATE supabase_projects SET
                        last_success_at = NOW(),
                        last_latency_ms = $3,
                        consecutive_failures = 0,
                        last_error_code = NULL,
                        status = 'healthy',
                        next_run_at = $4,
                        updated_at = NOW()
                    WHERE tenant_id = $1 AND id = $2
                    RETURNING status, consecutive_failures
                    """,
                    uuid.UUID(tenant_id), uuid.UUID(project_id), latency_ms, next_run_at,
                )
            else:
                row = await conn.fetchrow(
                    """
                    UPDATE supabase_projects SET
                        consecutive_failures = consecutive_failures + 1,
                        last_error_code = $3,
                        status = CASE WHEN consecutive_failures + 1 >= 2
                                      THEN 'failed' ELSE 'warning' END,
                        next_run_at = $4,
                        updated_at = NOW()
                    WHERE tenant_id = $1 AND id = $2
                    RETURNING status, consecutive_failures
                    """,
                    uuid.UUID(tenant_id), uuid.UUID(project_id), error_code, next_run_at,
                )
        return {"status": row["status"], "consecutive_failures": row["consecutive_failures"]} if row else {}

    async def mark_status(self, tenant_id: str, project_id: str, status: str) -> None:
        """Marca status sem side effect de latência/falha (ex.: 'paused' na
        descoberta/reconciliação com o Compose MCP)."""
        async with admin_connection() as conn:
            await conn.execute(
                "UPDATE supabase_projects SET status = $3, updated_at = NOW() "
                "WHERE tenant_id = $1 AND id = $2",
                uuid.UUID(tenant_id), uuid.UUID(project_id), status,
            )

    async def summary(self, tenant_id: str) -> dict[str, Any]:
        async with tenant_transaction(tenant_id) as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    count(*)                                       AS total,
                    count(*) FILTER (WHERE plan = 'free')          AS free_count,
                    count(*) FILTER (WHERE plan = 'paid')          AS paid_count,
                    count(*) FILTER (WHERE plan = 'unknown')       AS plan_unknown_count,
                    count(*) FILTER (WHERE keepalive_enabled)      AS keepalive_enabled_count,
                    count(*) FILTER (WHERE status = 'healthy')     AS healthy_count,
                    count(*) FILTER (WHERE status = 'warning')     AS warning_count,
                    count(*) FILTER (WHERE status = 'failed')      AS failed_count,
                    count(*) FILTER (WHERE status = 'paused')      AS paused_count,
                    count(*) FILTER (WHERE status = 'unknown')     AS status_unknown_count,
                    max(last_success_at)                           AS last_round_at
                FROM supabase_projects
                WHERE tenant_id = $1 AND active = true
                """,
                uuid.UUID(tenant_id),
            )
        return dict(row) if row else {}


class SupabaseKeepaliveRunRepository:
    """Histórico append-only de execuções de keepalive/health (uma linha por execução)."""

    async def record(
        self,
        tenant_id: str,
        project_id: str,
        started_at: datetime,
        ended_at: datetime,
        status: str,
        latency_ms: int | None,
        error_code: str | None,
        error_message: str | None,
        triggered_by: str,
        correlation_id: str,
    ) -> str:
        """error_message já deve chegar SANITIZADO pelo chamador (nunca DSN/
        token/secret) — trunca defensivamente a 500 chars mesmo assim."""
        async with tenant_transaction(tenant_id) as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO supabase_keepalive_runs(
                    tenant_id, project_id, started_at, ended_at, status,
                    latency_ms, error_code, error_message, triggered_by, correlation_id
                ) VALUES($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id
                """,
                uuid.UUID(tenant_id), uuid.UUID(project_id), started_at, ended_at,
                status, latency_ms, error_code,
                ((error_message or "")[:500] or None),
                triggered_by, correlation_id,
            )
        return str(row["id"])

    async def list_recent_for_project(
        self, tenant_id: str, project_id: str, limit: int = 5,
    ) -> list[SupabaseKeepaliveRunRow]:
        async with tenant_transaction(tenant_id) as conn:
            rows = await conn.fetch(
                """
                SELECT id, tenant_id, project_id, started_at, ended_at, status,
                       latency_ms, error_code, error_message, triggered_by,
                       correlation_id, created_at
                FROM supabase_keepalive_runs
                WHERE tenant_id = $1 AND project_id = $2
                ORDER BY created_at DESC LIMIT $3
                """,
                uuid.UUID(tenant_id), uuid.UUID(project_id), limit,
            )
        return [_row_to_run(r) for r in rows]

    async def count_consecutive_recent_failures(
        self, tenant_id: str, project_id: str, lookback: int = 5,
    ) -> int:
        """Cross-check independente de supabase_projects.consecutive_failures
        (que é a fonte primária) — conta falhas consecutivas nas últimas
        `lookback` execuções, parando no primeiro 'success'/'skipped'."""
        runs = await self.list_recent_for_project(tenant_id, project_id, limit=lookback)
        count = 0
        for run in runs:
            if run.status != "failure":
                break
            count += 1
        return count
