"""
credential_bootstrap.py — Secure runtime credential assignment for DB roles.

Separates structural migrations from credential bootstrap (Sprint 0.2 gate fix).

Version: 1 — idempotent ALTER ROLE PASSWORD via parameterized queries.
Re-execution updates passwords without recreating roles or altering RLS/grants.
"""

from __future__ import annotations

import logging

import asyncpg

logger = logging.getLogger(__name__)

BOOTSTRAP_VERSION = "1"
APP_ROLE = "cognitive_app"
WORKER_ROLE = "cognitive_worker"


async def bootstrap_role_passwords(
    conn: asyncpg.Connection,
    app_password: str,
    worker_password: str,
) -> None:
    """
    Assign LOGIN credentials to cognitive_app and cognitive_worker.

    Idempotent: safe to re-run; updates password if role already exists.
    Uses parameterized queries — password never interpolated into SQL string.
    """
    await _ensure_login_role(conn, APP_ROLE, app_password)
    await _ensure_login_role(conn, WORKER_ROLE, worker_password)
    logger.info(
        "Credential bootstrap v%s applied for roles %s, %s",
        BOOTSTRAP_VERSION,
        APP_ROLE,
        WORKER_ROLE,
    )


async def _ensure_login_role(
    conn: asyncpg.Connection,
    role_name: str,
    password: str,
) -> None:
    exists = await conn.fetchval(
        "SELECT 1 FROM pg_roles WHERE rolname = $1",
        role_name,
    )
    if not exists:
        raise RuntimeError(f"Role {role_name} not found — run migrations first")

    await conn.execute(f"ALTER ROLE {role_name} LOGIN")
    await conn.execute(f"ALTER ROLE {role_name} PASSWORD $1", password)
