"""Post-bootstrap authentication and privilege validation."""

from __future__ import annotations

from dataclasses import dataclass

import asyncpg

from .redaction import sanitize_exception


@dataclass(frozen=True)
class RoleAuthResult:
    ok: bool
    current_user: str | None
    reason: str
    rolcanlogin: bool | None = None
    rolsuper: bool | None = None
    rolbypassrls: bool | None = None
    privilege_escape_blocked: bool | None = None


async def verify_role_connection(dsn: str, expected_role: str) -> RoleAuthResult:
    """Connect with role DSN and validate current_user + privileges."""
    try:
        conn = await asyncpg.connect(dsn)
    except Exception as exc:
        return RoleAuthResult(
            ok=False,
            current_user=None,
            reason=f"authentication failed: {sanitize_exception(exc)}",
        )

    try:
        current_user = await conn.fetchval("SELECT current_user")
        if current_user != expected_role:
            return RoleAuthResult(
                ok=False,
                current_user=current_user,
                reason=f"expected role {expected_role}, got {current_user}",
            )

        priv = await conn.fetchrow(
            """
            SELECT rolcanlogin, rolsuper, rolbypassrls
            FROM pg_roles
            WHERE rolname = current_user
            """
        )
        if priv is None:
            return RoleAuthResult(
                ok=False,
                current_user=current_user,
                reason="role metadata not found",
            )

        if not priv["rolcanlogin"]:
            return RoleAuthResult(
                ok=False,
                current_user=current_user,
                reason="LOGIN is false",
                rolcanlogin=False,
                rolsuper=priv["rolsuper"],
                rolbypassrls=priv["rolbypassrls"],
            )
        if priv["rolsuper"]:
            return RoleAuthResult(
                ok=False,
                current_user=current_user,
                reason="SUPERUSER must be false",
                rolcanlogin=True,
                rolsuper=True,
                rolbypassrls=priv["rolbypassrls"],
            )
        if priv["rolbypassrls"]:
            return RoleAuthResult(
                ok=False,
                current_user=current_user,
                reason="BYPASSRLS must be false",
                rolcanlogin=True,
                rolsuper=False,
                rolbypassrls=True,
            )

        escape_blocked = await _privilege_escape_blocked(conn)

        return RoleAuthResult(
            ok=True,
            current_user=current_user,
            reason="authenticated",
            rolcanlogin=True,
            rolsuper=False,
            rolbypassrls=False,
            privilege_escape_blocked=escape_blocked,
        )
    finally:
        await conn.close()


async def _privilege_escape_blocked(conn: asyncpg.Connection) -> bool:
    for privileged in ("cognitive_admin", "postgres"):
        try:
            await conn.execute(f"SET ROLE {privileged}")
            return False
        except asyncpg.InsufficientPrivilegeError:
            continue
        except Exception:
            return False
    return True
