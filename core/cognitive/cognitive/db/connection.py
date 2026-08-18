"""
db/connection.py — Pool asyncpg com contexto de tenant por transação.

Estratégia RLS: SET LOCAL app.current_tenant_id = <tenant_id>
Aplica DENTRO de cada transação — nunca com SET SESSION (perigoso em pools).

Três DSNs:
  COGNITIVE_DB_URL         → cognitive_app (RLS enforced) — path normal da API
  COGNITIVE_DB_WORKER_URL  → cognitive_worker (RLS enforced) — workers/jobs
  COGNITIVE_DB_ADMIN_URL   → cognitive_admin (BYPASSRLS) — migrations e bootstrap
                             (register/deactivate de service identity via
                             CLI/script). OPCIONAL no processo web público
                             desde Sprint 0.3 (SEC-001) — a resolução de
                             identidade em runtime usa app_connection_no_tenant()
                             (pool cognitive_app), não mais admin_connection().
"""

from __future__ import annotations

import contextlib
import logging
import os
from typing import AsyncIterator

import asyncpg

logger = logging.getLogger(__name__)

_app_pool: asyncpg.Pool | None = None
_worker_pool: asyncpg.Pool | None = None
_admin_pool: asyncpg.Pool | None = None


async def create_pools(
    app_dsn: str | None = None,
    worker_dsn: str | None = None,
    admin_dsn: str | None = None,
    min_size: int = 2,
    max_size: int = 10,
) -> None:
    """Inicializa os pools de conexão. Chamar no startup do Gateway."""
    global _app_pool, _worker_pool, _admin_pool

    app_dsn    = app_dsn    or os.getenv("COGNITIVE_DB_URL")
    worker_dsn = worker_dsn or os.getenv("COGNITIVE_DB_WORKER_URL")
    admin_dsn  = admin_dsn  or os.getenv("COGNITIVE_DB_ADMIN_URL")

    if app_dsn:
        _app_pool = await asyncpg.create_pool(app_dsn, min_size=min_size, max_size=max_size)
        logger.info("App pool criado (%s)", app_dsn.split("@")[-1])

    if worker_dsn:
        _worker_pool = await asyncpg.create_pool(worker_dsn, min_size=1, max_size=5)
        logger.info("Worker pool criado")

    if admin_dsn:
        _admin_pool = await asyncpg.create_pool(admin_dsn, min_size=1, max_size=3)
        logger.info("Admin pool criado")


async def close_pools() -> None:
    """Fecha todos os pools. Chamar no shutdown do Gateway."""
    for pool in [_app_pool, _worker_pool, _admin_pool]:
        if pool:
            await pool.close()


def is_db_available() -> bool:
    """Retorna True se o pool da app está disponível."""
    return _app_pool is not None


@contextlib.asynccontextmanager
async def tenant_transaction(tenant_id: str) -> AsyncIterator[asyncpg.Connection]:
    """
    Context manager: abre transação com SET LOCAL app.current_tenant_id.

    Uso:
        async with tenant_transaction("prosperfy") as conn:
            rows = await conn.fetch("SELECT * FROM audit_events")
            # RLS garante apenas dados do tenant "prosperfy"

    Levanta RuntimeError se o pool não estiver inicializado.
    """
    if _app_pool is None:
        raise RuntimeError("DB pool não inicializado. Verificar COGNITIVE_DB_URL.")

    async with _app_pool.acquire() as conn:
        async with conn.transaction():
            # SET LOCAL: aplica somente dentro desta transação
            await conn.execute(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                tenant_id,
            )
            yield conn


@contextlib.asynccontextmanager
async def app_connection_no_tenant() -> AsyncIterator[asyncpg.Connection]:
    """
    Conexão do pool da app (cognitive_app), SEM SET LOCAL de tenant.

    Uso exclusivo: resolução de identidade (credential_hash -> tenant_id),
    que por definição precisa acontecer ANTES de existir tenant context
    (SEC-001). RLS de service_identities permite SELECT irrestrito nessa
    role (o credential_hash é o boundary, ver migration 002); INSERT/UPDATE
    continuam tenant-scoped.

    NÃO usar para nenhuma outra tabela — sem tenant context, qualquer
    outra tabela com RLS tenant-scoped simplesmente não retorna linhas.
    """
    if _app_pool is None:
        raise RuntimeError("DB pool não inicializado. Verificar COGNITIVE_DB_URL.")

    async with _app_pool.acquire() as conn:
        yield conn


@contextlib.asynccontextmanager
async def worker_transaction(tenant_id: str) -> AsyncIterator[asyncpg.Connection]:
    """Transação com cognitive_worker role, com tenant context."""
    if _worker_pool is None:
        raise RuntimeError("Worker pool não inicializado. Verificar COGNITIVE_DB_WORKER_URL.")

    async with _worker_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                tenant_id,
            )
            yield conn


@contextlib.asynccontextmanager
async def admin_connection() -> AsyncIterator[asyncpg.Connection]:
    """
    Conexão admin sem RLS — apenas para migrations, seed e credential lookup.

    NÃO usar como caminho genérico da aplicação (ADR-V2-002).
    """
    if _admin_pool is None:
        raise RuntimeError("Admin pool não inicializado. Verificar COGNITIVE_DB_ADMIN_URL.")

    async with _admin_pool.acquire() as conn:
        yield conn
