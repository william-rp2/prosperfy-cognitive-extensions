#!/usr/bin/env python3
"""
scripts/manage_service_identity.py — Operator CLI for service identity lifecycle.

Sprint 0.4 (0.4 --- Auth/service identities): the only supported way to call
ServiceIdentityRepository.register()/deactivate()/rotate() is this script —
never a HTTP route. See core/cognitive/cognitive/db/repositories/identity_repo.py
module docstring: identity provisioning must never be reachable from the
public web process. This script is meant to be run by a human operator or
the Homolog Gate process, connecting via COGNITIVE_DB_ADMIN_URL
(cognitive_admin, BYPASSRLS) — the same admin pool migrations use.

Credential discipline:
  - Credentials are generated here with `secrets.token_urlsafe(32)` — never
    `random` — and are printed to stdout EXACTLY ONCE, on --register and
    --rotate. They are never stored in plaintext anywhere (only
    hash_credential()'s sha256 is persisted, per identity_repo.py) and are
    never written to the logger — only non-secret fields (id/tenant_id/
    actor_id/profile) are logged.
  - --deactivate never echoes the raw token back — at most a truncated
    hash_credential() prefix, for operator confirmation.

--rotate depends on ServiceIdentityRepository.rotate(old_credential,
new_credential), added by dev/sprint-0.4-db-identity (merged). The
hasattr() guard in cmd_rotate() is kept as defense-in-depth — if this
script is ever checked out against an older/reverted identity_repo.py
without rotate(), --rotate still prints a clear, actionable error and
exits 1 instead of raising a raw AttributeError.

--list was intentionally NOT implemented: doing it "cleanly" would require
a new ServiceIdentityRepository method beyond register()/deactivate()/
lookup()/rotate() — new repo surface that could conflict with the parallel
DB workstream's changes to the same file. Skipped per Sprint 0.4 CLI brief.

Usage:
  python core/cognitive/scripts/manage_service_identity.py \\
      --register --tenant-id <uuid> --actor-id <id> [--profile <profile>]

  python core/cognitive/scripts/manage_service_identity.py \\
      --rotate --old-credential <token>

  python core/cognitive/scripts/manage_service_identity.py \\
      --deactivate --credential <token>

Exit codes: 0 success, 1 on ValueError/operational failure (clear stderr
message, no traceback for expected error paths). Unexpected exceptions
still surface a traceback.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import secrets
import sys
from pathlib import Path

# core/cognitive/scripts/manage_service_identity.py -> parents[1] == core/cognitive
# (same target the migrations runner reaches from its own location) so that
# `import cognitive...` resolves regardless of the caller's cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cognitive.db.connection import admin_connection, close_pools, create_pools  # noqa: E402
from cognitive.db.repositories.identity_repo import (  # noqa: E402
    ServiceIdentityRepository,
    hash_credential,
)
from cognitive.gate.redaction import safe_connection_target  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("manage_service_identity")

# secrets.token_urlsafe(32) -> 32 bytes of entropy (256 bits), ~43 url-safe
# base64 chars. NEVER use `random` for credential generation.
CREDENTIAL_ENTROPY_BYTES = 32

DEFAULT_ADMIN_DSN = "postgresql://cognitive_admin:dev-postgres-secret@localhost:5440/cognitive_dev"


def generate_credential() -> str:
    return secrets.token_urlsafe(CREDENTIAL_ENTROPY_BYTES)


def _print_one_time_credential(credential: str, context: str) -> None:
    """
    Prints `credential` to stdout exactly once. Callers must call this at
    most once per successful register()/rotate() — never store the result,
    never pass it to logger.*.
    """
    banner = "=" * 74
    print(banner)
    print("CREDENTIAL — SHOWN EXACTLY ONCE. It will never be displayed again")
    print("and is NOT stored in plaintext anywhere (only its sha256 hash is")
    print("persisted, per hash_credential()). Copy it now.")
    print(f"Context: {context}")
    print()
    print(credential)
    print()
    print(banner)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manage_service_identity.py",
        description=(
            "Operator CLI for service identity provisioning "
            "(never HTTP-reachable — see identity_repo.py docstring)."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--register", action="store_true", help="Registrar nova service identity")
    mode.add_argument("--rotate", action="store_true", help="Rotacionar credential existente")
    mode.add_argument("--deactivate", action="store_true", help="Desativar (revogar) credential")

    parser.add_argument("--tenant-id", metavar="UUID", help="Tenant id (obrigatório com --register)")
    parser.add_argument("--actor-id", metavar="ID", help="Actor id (obrigatório com --register)")
    parser.add_argument(
        "--profile", default="owner-core", metavar="PROFILE",
        help="Profile da identity (default: owner-core, só usado com --register)",
    )
    parser.add_argument(
        "--old-credential", metavar="TOKEN",
        help="Credential atual a rotacionar (obrigatório com --rotate)",
    )
    parser.add_argument(
        "--credential", metavar="TOKEN",
        help="Credential a desativar (obrigatório com --deactivate)",
    )
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.register:
        missing = [
            flag for flag, value in (("--tenant-id", args.tenant_id), ("--actor-id", args.actor_id))
            if not value
        ]
        if missing:
            parser.error(f"--register requires {', '.join(missing)}")
    elif args.rotate:
        if not args.old_credential:
            parser.error("--rotate requires --old-credential")
    elif args.deactivate:
        if not args.credential:
            parser.error("--deactivate requires --credential")


async def cmd_register(args: argparse.Namespace, repo: ServiceIdentityRepository) -> int:
    credential = generate_credential()
    try:
        row = await repo.register(
            tenant_id=args.tenant_id,
            actor_id=args.actor_id,
            credential=credential,
            profile=args.profile,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    logger.info(
        "service identity registered id=%s tenant_id=%s actor_id=%s profile=%s",
        row.id, row.tenant_id, row.actor_id, row.profile,
    )
    _print_one_time_credential(
        credential,
        context=f"tenant={row.tenant_id} actor={row.actor_id} profile={row.profile}",
    )
    return 0


async def cmd_rotate(args: argparse.Namespace, repo: ServiceIdentityRepository) -> int:
    if not hasattr(repo, "rotate"):
        print(
            "ERROR: ServiceIdentityRepository.rotate() is not available yet on this "
            "checkout. --rotate depends on the rotate(old_credential, new_credential) "
            "method added by the parallel workstream on branch "
            "dev/sprint-0.4-db-identity — merge that branch into dev/sprint-0.4 first, "
            "then retry.",
            file=sys.stderr,
        )
        return 1

    new_credential = generate_credential()
    try:
        row = await repo.rotate(args.old_credential, new_credential)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    logger.info(
        "service identity rotated id=%s tenant_id=%s actor_id=%s profile=%s",
        row.id, row.tenant_id, row.actor_id, row.profile,
    )
    _print_one_time_credential(
        new_credential,
        context=f"tenant={row.tenant_id} actor={row.actor_id} profile={row.profile} (rotated)",
    )
    return 0


async def cmd_deactivate(args: argparse.Namespace, repo: ServiceIdentityRepository) -> int:
    try:
        await repo.deactivate(args.credential)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    truncated = hash_credential(args.credential)[:12]
    logger.info("service identity deactivated credential_hash_prefix=%s", truncated)
    print(f"Credential revoked (hash prefix: {truncated}...). Raw token never echoed.")
    return 0


async def _async_main(args: argparse.Namespace) -> int:
    admin_dsn = os.getenv("COGNITIVE_DB_ADMIN_URL", DEFAULT_ADMIN_DSN)
    logger.info("Conectando ao banco: %s", safe_connection_target(admin_dsn))
    await create_pools(admin_dsn=admin_dsn)
    try:
        # Touch the pool once up front so a misconfigured admin DSN fails
        # fast with a clear message, before we attempt any repo call.
        async with admin_connection():
            pass

        repo = ServiceIdentityRepository()
        if args.register:
            return await cmd_register(args, repo)
        if args.rotate:
            return await cmd_rotate(args, repo)
        if args.deactivate:
            return await cmd_deactivate(args, repo)
        return 1
    finally:
        await close_pools()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(parser, args)

    try:
        return asyncio.run(_async_main(args))
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
