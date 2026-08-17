"""
credential_bootstrap.py — Secure runtime credential assignment for DB roles.

Version 2: PostgreSQL does not accept bind parameters in ALTER ROLE PASSWORD.
Uses server-side quote_literal($1) for safe escaping — password never concatenated raw.
"""

from __future__ import annotations

import logging

import asyncpg

from .redaction import sanitize_exception

logger = logging.getLogger(__name__)

BOOTSTRAP_VERSION = "2"
APP_ROLE = "cognitive_app"
WORKER_ROLE = "cognitive_worker"
ALLOWED_ROLES = frozenset({APP_ROLE, WORKER_ROLE})


async def bootstrap_role_passwords(
    conn: asyncpg.Connection,
    app_password: str,
    worker_password: str,
) -> None:
    """
    Assign LOGIN credentials to cognitive_app and cognitive_worker.

    Idempotent: re-run updates password via ALTER ROLE; does not touch RLS/grants.
    """
    try:
        await set_role_password(conn, APP_ROLE, app_password)
        await set_role_password(conn, WORKER_ROLE, worker_password)
    except Exception as exc:
        raise RuntimeError(
            f"Credential bootstrap failed: {sanitize_exception(exc)}"
        ) from None

    logger.info(
        "Credential bootstrap v%s applied for roles %s, %s",
        BOOTSTRAP_VERSION,
        APP_ROLE,
        WORKER_ROLE,
    )


async def set_role_password(
    conn: asyncpg.Connection,
    role_name: str,
    password: str,
) -> None:
    """
    Set role password using PostgreSQL quote_literal for safe escaping.

    role_name must be allowlisted — never accept arbitrary user input.
    """
    if role_name not in ALLOWED_ROLES:
        raise ValueError(f"Role not allowlisted: {role_name}")

    exists = await conn.fetchval(
        "SELECT 1 FROM pg_roles WHERE rolname = $1",
        role_name,
    )
    if not exists:
        raise RuntimeError(f"Role {role_name} not found — run migrations first")

    quoted_password = await conn.fetchval(
        "SELECT quote_literal($1::text)",
        password,
    )
    await conn.execute(f"ALTER ROLE {role_name} LOGIN")
    await conn.execute(f"ALTER ROLE {role_name} PASSWORD {quoted_password}")
