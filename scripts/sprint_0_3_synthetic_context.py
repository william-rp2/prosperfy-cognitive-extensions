#!/usr/bin/env python3
"""
Sprint 0.3 — Homolog Synthetic E2E Context Provisioner.

The Homolog Gate's final closure step needs a real end-to-end proof of the
full execution chain (Identity → Registry → ResourceResolver → Policy →
Adapter → live MCP → Result → Audit → Telemetry) against Supabase Homolog
(project ref esvjfkknrzzziafovwrv). That requires a tenant/actor/credential/
grant/resource that actually EXIST in the Homolog database.

This script is the ONLY sanctioned way to create and tear down that data.
It is pure data provisioning against tables already created by migrations
000/001 (tenants, service_identities, tenant_resources, capability_grants)
— it is NOT a migration and must never become one.

Executar NO SERVIDOR/OPERADOR com COGNITIVE_DB_ADMIN_URL configurado para
Homolog. Nunca imprime a DSN completa nem a credential gerada.

Commands:
  bootstrap-homolog-context   Create/upsert the synthetic tenant, service
                              identity, capability grant and resource; write
                              the live credential to a local JSON file.
  show-context                Read-only lookup of the synthetic tenant's
                              ids (never the credential — only its hash is
                              ever stored).
  teardown-homolog-context    Delete every row scoped to the synthetic
                              tenant_id. Idempotent, no-op if absent.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import secrets
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
COGNITIVE_DIR = REPO_ROOT / "core" / "cognitive"
sys.path.insert(0, str(COGNITIVE_DIR))

from cognitive.db.connection import admin_connection, close_pools, create_pools  # noqa: E402
from cognitive.db.repositories.identity_repo import ServiceIdentityRepository  # noqa: E402
from cognitive.db.repositories.resource_repo import TenantResourceRepository  # noqa: E402
from cognitive.gate.redaction import safe_connection_target, sanitize_exception  # noqa: E402
from cognitive.gate.verify_target import verify_target  # noqa: E402

logger = logging.getLogger(__name__)

# ─── Identity constants — exported, imported by name from dev/sprint-0.3-e2e-runner ──
SYNTHETIC_TENANT_SLUG = "homolog-synthetic-e2e"
SYNTHETIC_TENANT_NAME = "Homolog Synthetic E2E"
SYNTHETIC_ACTOR_ID = "homolog-e2e-actor"
SYNTHETIC_PROFILE = "owner-core"
SYNTHETIC_RESOURCE_KEY = "homolog-synthetic-vps"
SYNTHETIC_RESOURCE_TYPE = "vps"
SYNTHETIC_CAPABILITY_ID = "infra.inspect"

# Obviously-synthetic placeholder used only when the operator does not supply
# real (or intentionally-fake-but-reachable) resource params at bootstrap time.
PLACEHOLDER_RESOURCE_PARAMS: dict[str, str] = {
    "host": "synthetic-e2e-placeholder.invalid",
    "type": SYNTHETIC_RESOURCE_TYPE,
}

DEFAULT_CREDENTIAL_OUT = str(
    Path(tempfile.gettempdir()) / "cognitive_homolog_e2e_context.json"
)

# Teardown order — children before parent, to satisfy FK constraints on a
# real Postgres. Verified against core/migrations/000_foundation_tenancy.sql
# and 001_capability_registry_audit.sql: every table below has a tenant_id
# column referencing tenants(id). service_identities/tenant_resources/
# tenant_members/credential_refs/tenant_integrations/capability_grants all
# have ON DELETE CASCADE — audit_events/execution_traces/cost_telemetry do
# NOT, so they are deleted explicitly rather than relying on cascade.
TEARDOWN_TABLES: tuple[str, ...] = (
    "audit_events",
    "execution_traces",
    "cost_telemetry",
    "service_identities",
    "tenant_resources",
    "capability_grants",
    "tenant_members",
    "credential_refs",
    "tenant_integrations",
)


@dataclass(frozen=True)
class SyntheticContext:
    tenant_id: str
    actor_id: str
    credential: str
    resource_key: str
    capability_id: str
    credential_file_path: str


class TargetVerificationError(RuntimeError):
    """Raised when the admin DSN does not verify as the Homolog target."""


def _require_verified_target(admin_dsn: str | None) -> None:
    """Refuse to proceed against anything that isn't the verified Homolog target.

    Reuses cognitive.gate.verify_target.verify_target(), which itself wraps
    verify_homolog_admin_dsn() — never invents its own verification logic.
    """
    report = verify_target(admin_dsn)
    if not report.verified:
        raise TargetVerificationError(f"target verification failed: {report.reason}")


def _generate_synthetic_credential() -> str:
    """Cryptographically secure — secrets.token_urlsafe, never random/fixed."""
    return secrets.token_urlsafe(32)


def _write_credential_file(path: str, payload: dict[str, Any]) -> None:
    """
    Write the credential JSON with 0600-equivalent permissions.

    The file descriptor is opened with mode 0o600 at creation time (subject
    to umask on POSIX, same as chmod would be) so there is no window where
    content already exists but permissions haven't been narrowed. os.chmod
    is called again explicitly afterward as a belt-and-braces guarantee.

    NOTE (Windows): os.chmod's mode bits do not map 1:1 onto NTFS ACLs the
    way they do onto POSIX permission bits. On Windows this call is
    best-effort and does NOT guarantee the file is unreadable by other
    local accounts the way it does on Linux. The Homolog Gate that actually
    runs this script runs on Linux, where the guarantee holds. This
    docstring exists so nobody claims a cross-platform guarantee that
    can't actually be verified here.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload, indent=2))
    finally:
        pass

    try:
        os.chmod(p, 0o600)
    except (OSError, NotImplementedError):
        # Best-effort on platforms where chmod bits don't map to real ACLs.
        pass


async def _upsert_tenant(conn: Any, slug: str, name: str) -> Any:
    """Same idempotent ON CONFLICT pattern conftest.py's seeded_tenants fixture uses."""
    row = await conn.fetchrow(
        "INSERT INTO tenants(slug, name) VALUES($1, $2) "
        "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name RETURNING id",
        slug,
        name,
    )
    return row["id"]


async def _upsert_capability_grant(
    conn: Any, tenant_id: Any, profile: str, capability_id: str
) -> None:
    """Matches migration 000's uq_capability_grant unique index."""
    tenant_uuid = tenant_id if isinstance(tenant_id, uuid.UUID) else uuid.UUID(str(tenant_id))
    await conn.execute(
        "INSERT INTO capability_grants(tenant_id, profile, capability_id) "
        "VALUES($1, $2, $3) "
        "ON CONFLICT (tenant_id, profile, capability_id) DO NOTHING",
        tenant_uuid,
        profile,
        capability_id,
    )


async def bootstrap_context(
    admin_dsn: str,
    resource_resolved_params: dict[str, str] | None,
    credential_out: str | None = None,
) -> SyntheticContext:
    """
    Create/upsert the full synthetic E2E context in Homolog. Idempotent:
    safe to run twice with no duplication or error.

    resource_resolved_params is CALLER-supplied (CLI flag / env var) — this
    function never invents a real VPS hostname. If None, an obviously
    synthetic placeholder is used and a warning is printed.
    """
    _require_verified_target(admin_dsn)

    if resource_resolved_params is None:
        resource_resolved_params = dict(PLACEHOLDER_RESOURCE_PARAMS)
        print(
            "WARNING: no resource params supplied (--resource-host or "
            "COGNITIVE_SYNTHETIC_RESOURCE_PARAMS_JSON). Falling back to "
            f"placeholder resource params {resource_resolved_params!r}. "
            "The live-MCP step of the E2E run will NOT produce a meaningful "
            "result against this placeholder — override at bootstrap time "
            "with the real (or intentionally-fake-but-reachable) VPS target."
        )

    await create_pools(admin_dsn=admin_dsn, min_size=1, max_size=2)
    try:
        async with admin_connection() as conn:
            tenant_id_raw = await _upsert_tenant(
                conn, SYNTHETIC_TENANT_SLUG, SYNTHETIC_TENANT_NAME
            )
        tenant_id = str(tenant_id_raw)

        credential = _generate_synthetic_credential()

        identity_repo = ServiceIdentityRepository()
        await identity_repo.register(
            tenant_id, SYNTHETIC_ACTOR_ID, credential, SYNTHETIC_PROFILE
        )

        async with admin_connection() as conn:
            await _upsert_capability_grant(
                conn, tenant_id_raw, SYNTHETIC_PROFILE, SYNTHETIC_CAPABILITY_ID
            )

        resource_repo = TenantResourceRepository()
        await resource_repo.upsert(
            tenant_id,
            SYNTHETIC_RESOURCE_KEY,
            SYNTHETIC_RESOURCE_TYPE,
            resource_resolved_params,
        )
    finally:
        await close_pools()

    out_path = credential_out or DEFAULT_CREDENTIAL_OUT
    payload = {
        "tenant_id": tenant_id,
        "actor_id": SYNTHETIC_ACTOR_ID,
        "credential": credential,
        "resource_key": SYNTHETIC_RESOURCE_KEY,
        "capability_id": SYNTHETIC_CAPABILITY_ID,
    }
    _write_credential_file(out_path, payload)

    return SyntheticContext(
        tenant_id=tenant_id,
        actor_id=SYNTHETIC_ACTOR_ID,
        credential=credential,
        resource_key=SYNTHETIC_RESOURCE_KEY,
        capability_id=SYNTHETIC_CAPABILITY_ID,
        credential_file_path=out_path,
    )


async def show_context(admin_dsn: str) -> dict[str, str] | None:
    """Read-only. Never returns/prints the credential — only its hash exists in DB."""
    _require_verified_target(admin_dsn)

    await create_pools(admin_dsn=admin_dsn, min_size=1, max_size=2)
    try:
        async with admin_connection() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM tenants WHERE slug = $1", SYNTHETIC_TENANT_SLUG
            )
    finally:
        await close_pools()

    if row is None:
        return None

    return {
        "tenant_id": str(row["id"]),
        "actor_id": SYNTHETIC_ACTOR_ID,
        "resource_key": SYNTHETIC_RESOURCE_KEY,
        "capability_id": SYNTHETIC_CAPABILITY_ID,
    }


def _parse_delete_count(status: str) -> int:
    """asyncpg conn.execute() returns a status string like 'DELETE 3'."""
    if not status:
        return 0
    parts = status.split()
    return int(parts[-1]) if parts and parts[-1].isdigit() else 0


async def teardown_context(admin_dsn: str) -> dict[str, int]:
    """
    Delete every row scoped to the synthetic tenant_id, found by slug.
    Idempotent: running it when nothing exists is a graceful no-op.

    Constrained EXACTLY to rows belonging to the synthetic tenant — every
    DELETE is `WHERE tenant_id = $1` against one specific looked-up id.
    Never a wildcard/pattern delete, never DROP/TRUNCATE, never touches
    RLS policies, roles, or any other tenant's data.
    """
    _require_verified_target(admin_dsn)

    await create_pools(admin_dsn=admin_dsn, min_size=1, max_size=2)
    try:
        async with admin_connection() as conn:
            tenant_id = await conn.fetchval(
                "SELECT id FROM tenants WHERE slug = $1", SYNTHETIC_TENANT_SLUG
            )

            if tenant_id is None:
                print("already torn down, nothing to do")
                return {}

            counts: dict[str, int] = {}
            for table in TEARDOWN_TABLES:
                assert table in TEARDOWN_TABLES  # defensive: fixed whitelist only
                status = await conn.execute(
                    f"DELETE FROM {table} WHERE tenant_id = $1", tenant_id
                )
                counts[table] = _parse_delete_count(status)

            status = await conn.execute("DELETE FROM tenants WHERE id = $1", tenant_id)
            counts["tenants"] = _parse_delete_count(status)
    finally:
        await close_pools()

    for table, count in counts.items():
        print(f"deleted {table}={count}")
    return counts


# ─── CLI ──────────────────────────────────────────────────────────────────


def _admin_url() -> str:
    return os.getenv("COGNITIVE_DB_ADMIN_URL", "")


def _resolve_resource_params(resource_host: str | None) -> dict[str, str] | None:
    if resource_host:
        return {"host": resource_host, "type": SYNTHETIC_RESOURCE_TYPE}

    env_json = os.getenv("COGNITIVE_SYNTHETIC_RESOURCE_PARAMS_JSON")
    if env_json:
        try:
            parsed = json.loads(env_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f"invalid COGNITIVE_SYNTHETIC_RESOURCE_PARAMS_JSON: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise SystemExit(
                "COGNITIVE_SYNTHETIC_RESOURCE_PARAMS_JSON must be a JSON object"
            )
        return parsed

    return None


def cmd_bootstrap_homolog_context(args: argparse.Namespace) -> int:
    admin_dsn = _admin_url()
    print(f"target={safe_connection_target(admin_dsn)}")

    resource_params = _resolve_resource_params(args.resource_host)

    try:
        context = asyncio.run(
            bootstrap_context(admin_dsn, resource_params, credential_out=args.credential_out)
        )
    except TargetVerificationError as exc:
        print(f"target_verification_failed={exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 — operator script, never leak raw errors
        print(f"bootstrap_failed={sanitize_exception(exc)}")
        return 1

    print(f"tenant_id={context.tenant_id}")
    print(f"actor_id={context.actor_id}")
    print(f"resource_key={context.resource_key}")
    print(f"capability_id={context.capability_id}")
    print(f"credential_file={context.credential_file_path}")
    print("=" * 72)
    print("WARNING: the file above contains a LIVE synthetic credential.")
    print("This script's teardown step does NOT delete this file — that is")
    print("the operator's responsibility after the E2E run completes (Gate")
    print("closure sequence step 12).")
    print("NEVER commit this file to git.")
    print("=" * 72)
    return 0


def cmd_show_context(_args: argparse.Namespace) -> int:
    admin_dsn = _admin_url()
    try:
        result = asyncio.run(show_context(admin_dsn))
    except TargetVerificationError as exc:
        print(f"target_verification_failed={exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"show_context_failed={sanitize_exception(exc)}")
        return 1

    if result is None:
        print("synthetic tenant not found — bootstrap-homolog-context has not run")
        return 0

    for key, value in result.items():
        print(f"{key}={value}")
    return 0


def cmd_teardown_homolog_context(_args: argparse.Namespace) -> int:
    admin_dsn = _admin_url()
    print(f"target={safe_connection_target(admin_dsn)}")

    try:
        asyncio.run(teardown_context(admin_dsn))
    except TargetVerificationError as exc:
        print(f"target_verification_failed={exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"teardown_failed={sanitize_exception(exc)}")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sprint 0.3 — Homolog synthetic E2E context provisioner"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    boot = sub.add_parser(
        "bootstrap-homolog-context",
        help="Create/upsert the synthetic tenant/identity/grant/resource and write the credential file",
    )
    boot.add_argument(
        "--resource-host",
        default=None,
        help="Real (or intentionally-fake-but-reachable) VPS host for infra.inspect MCP tools",
    )
    boot.add_argument(
        "--credential-out",
        default=None,
        help=f"Path for the credential JSON file (default: {DEFAULT_CREDENTIAL_OUT})",
    )

    sub.add_parser("show-context", help="Read-only lookup of the synthetic context (never the credential)")
    sub.add_parser("teardown-homolog-context", help="Delete every row scoped to the synthetic tenant")

    args = parser.parse_args()

    handlers = {
        "bootstrap-homolog-context": cmd_bootstrap_homolog_context,
        "show-context": cmd_show_context,
        "teardown-homolog-context": cmd_teardown_homolog_context,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
