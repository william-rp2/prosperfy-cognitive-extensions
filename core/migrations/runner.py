"""
migrations/runner.py — Migration runner minimalista para o Cognitive Core.

Sem Alembic — dependência pesada desnecessária para Sprint 0.2.
Conecta como cognitive_admin (BYPASSRLS) para criar/destruir schema.

Uso:
  python runner.py --up               # aplicar todas as pending
  python runner.py --up 001           # aplicar até versão 001
  python runner.py --down 0           # reverter até versão 0 (estado limpo)
  python runner.py --status           # listar estado atual
  python runner.py --verify           # checksum de cada migration aplicada
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

import asyncpg

# Redaction for safe logging (host only)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cognitive"))
try:
    from cognitive.gate.redaction import safe_connection_target
except ImportError:
    def safe_connection_target(dsn: str) -> str:
        return dsn.split("@")[-1] if "@" in dsn else "unknown"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("migrations")

MIGRATIONS_DIR = Path(__file__).parent
ROLLBACK_DIR = MIGRATIONS_DIR / "rollback"

# Migrations em ordem determinística
MIGRATIONS: list[tuple[str, Path]] = sorted(
    [(p.stem, p) for p in MIGRATIONS_DIR.glob("[0-9]*.sql")],
    key=lambda x: x[0],
)


def file_checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


async def ensure_migrations_table(conn: asyncpg.Connection) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            version     TEXT        PRIMARY KEY,
            applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            checksum    TEXT        NOT NULL
        )
    """)


async def get_applied(conn: asyncpg.Connection) -> dict[str, str]:
    rows = await conn.fetch("SELECT version, checksum FROM _migrations ORDER BY version")
    return {r["version"]: r["checksum"] for r in rows}


async def run_up(conn: asyncpg.Connection, target: str | None = None) -> None:
    await ensure_migrations_table(conn)
    applied = await get_applied(conn)

    for version, path in MIGRATIONS:
        if target and version > target:
            break
        if version in applied:
            checksum = file_checksum(path)
            if applied[version] != checksum:
                logger.error(
                    "CHECKSUM MISMATCH: %s esperado=%s atual=%s",
                    version, applied[version], checksum,
                )
                sys.exit(1)
            logger.info("SKIP (already applied): %s", version)
            continue

        logger.info("APPLYING: %s (%s)", version, path.name)
        sql = path.read_text(encoding="utf-8")
        await conn.execute(sql)
        checksum = file_checksum(path)
        await conn.execute(
            "INSERT INTO _migrations(version, checksum) VALUES($1, $2)",
            version, checksum,
        )
        logger.info("DONE: %s (checksum=%s)", version, checksum)


async def run_down(conn: asyncpg.Connection, target: int) -> None:
    await ensure_migrations_table(conn)
    applied = await get_applied(conn)

    # Reverter em ordem inversa até (exclusive) target
    versions_to_revert = sorted(
        [v for v in applied if int(v.split("_")[0]) > target],
        reverse=True,
    )

    for version in versions_to_revert:
        rollback_path = ROLLBACK_DIR / f"{version}_rollback.sql"
        if not rollback_path.exists():
            logger.error("Rollback não encontrado para %s: %s", version, rollback_path)
            sys.exit(1)

        logger.info("REVERTING: %s", version)
        sql = rollback_path.read_text(encoding="utf-8")
        await conn.execute(sql)
        await conn.execute("DELETE FROM _migrations WHERE version = $1", version)
        logger.info("REVERTED: %s", version)


async def run_status(conn: asyncpg.Connection) -> None:
    await ensure_migrations_table(conn)
    applied = await get_applied(conn)

    print("\n=== Migration Status ===")
    for version, path in MIGRATIONS:
        checksum = file_checksum(path)
        if version in applied:
            match = "✓" if applied[version] == checksum else "✗ MISMATCH"
            print(f"  APPLIED  [{match}] {version}")
        else:
            print(f"  PENDING         {version}")
    print()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Cognitive migration runner")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--up", nargs="?", const="", metavar="VERSION",
                       help="Aplicar migrations (opcional: até VERSION)")
    group.add_argument("--down", type=int, metavar="TARGET",
                       help="Reverter migrations até (exclusive) TARGET (ex: --down 0 = reverter tudo)")
    group.add_argument("--status", action="store_true", help="Mostrar estado atual")

    args = parser.parse_args()

    db_url = os.getenv("COGNITIVE_DB_ADMIN_URL",
                       "postgresql://cognitive_admin:dev-postgres-secret@localhost:5440/cognitive_dev")

    logger.info("Conectando ao banco: %s", safe_connection_target(db_url))
    conn = await asyncpg.connect(db_url)

    try:
        if args.status:
            await run_status(conn)
        elif args.up is not None:
            target = args.up or None
            await run_up(conn, target)
        elif args.down is not None:
            await run_down(conn, args.down)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
