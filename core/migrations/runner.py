"""
migrations/runner.py — Migration runner minimalista para o Cognitive Core.

Sem Alembic — dependência pesada desnecessária para Sprint 0.2.
Conecta como cognitive_admin (BYPASSRLS) para criar/destruir schema.

Contrato de atomicidade (Sprint 0.3, hotfix pós-Gate):
  Cada migration = UMA unidade atômica = (executar o arquivo SQL inteiro +
  gravar a linha de tracking em _migrations) dentro de UMA única transação
  explícita (`async with conn.transaction()`). Se qualquer statement do
  arquivo falhar, TUDO é revertido — inclusive a linha de tracking, que
  nunca chega a existir. Migrations são aplicadas uma de cada vez, cada
  qual em sua própria transação — a falha da migration N nunca reverte
  migrations 1..N-1 já commitadas.

  Antes deste hotfix, o arquivo inteiro ia num `conn.execute(sql)` e o
  INSERT de tracking em outro `conn.execute(...)` separado — duas
  chamadas, duas transações implícitas (protocolo simples do Postgres já
  agrupa múltiplos statements de UM `execute()` sem params numa transação
  implícita só; ver docs.postgresql.org/current/protocol-flow.html —
  mas isso não cobria o intervalo ENTRE a execução do arquivo e o INSERT
  de tracking. Um crash exatamente nesse intervalo deixaria a migration
  aplicada porém não rastreada).

Uso:
  python runner.py --up               # aplicar todas as pending
  python runner.py --up 001           # aplicar até versão 001
  python runner.py --down 0           # reverter até versão 0 (estado limpo)
  python runner.py --status           # listar estado atual
  python runner.py --verify           # checksum de cada migration aplicada
  python runner.py --inspect 002      # diagnóstico de estado residual (CLEAN/PARTIAL/APPLIED)
                                       # antes de reaplicar uma migration que falhou no meio
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


async def apply_one_migration(conn: asyncpg.Connection, version: str, path: Path) -> None:
    """
    Aplica UMA migration como unidade atômica: SQL do arquivo + tracking
    row, na mesma transação explícita. Qualquer falha reverte os dois —
    nunca fica "SQL aplicado, tracking ausente" nem o inverso.
    """
    sql = path.read_text(encoding="utf-8")
    checksum = file_checksum(path)

    async with conn.transaction():
        await conn.execute(sql)
        await conn.execute(
            "INSERT INTO _migrations(version, checksum) VALUES($1, $2)",
            version, checksum,
        )


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
        try:
            await apply_one_migration(conn, version, path)
        except Exception:
            logger.error(
                "FAILED: %s — transação revertida (SQL + tracking), migration permanece PENDING. "
                "Rode `--inspect %s` antes de tentar de novo.",
                version, version,
            )
            raise
        logger.info("DONE: %s (checksum=%s)", version, file_checksum(path))


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
        async with conn.transaction():
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


# ─── Reconciliation: diagnóstico de estado residual antes de retry ─────────
#
# Fingerprint mínimo por migration: um pequeno conjunto de sinais de estado
# do banco que juntos indicam se os efeitos daquele arquivo específico já
# aconteceram, parcialmente ou não. Não substitui `_migrations` como fonte
# de verdade sobre "está aplicada" — é um raio-x pra decidir se é seguro
# reaplicar depois de uma falha no meio do arquivo.
INSPECTION_QUERIES: dict[str, list[tuple[str, str]]] = {
    "002": [
        (
            "function_exists",
            "SELECT EXISTS (SELECT 1 FROM pg_proc WHERE proname = "
            "'resolve_service_identity_by_credential_hash') AS v",
        ),
        (
            "function_owner_is_cognitive_admin",
            "SELECT COALESCE((SELECT pg_get_userbyid(proowner) = 'cognitive_admin' "
            "FROM pg_proc WHERE proname = 'resolve_service_identity_by_credential_hash'), false) AS v",
        ),
        (
            "public_has_execute_on_function",
            "SELECT COALESCE(has_function_privilege('public', "
            "'resolve_service_identity_by_credential_hash(text)', 'EXECUTE'), false) AS v",
        ),
        (
            "cognitive_app_has_direct_select_on_table",
            "SELECT has_table_privilege('cognitive_app', 'service_identities', 'SELECT') AS v",
        ),
        (
            "old_tenant_isolation_policy_exists",
            "SELECT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'service_identities' "
            "AND policyname = 'tenant_isolation') AS v",
        ),
    ],
}


async def inspect_migration(conn: asyncpg.Connection, version: str) -> str:
    """
    Roda o fingerprint de `version` e imprime um diagnóstico legível.
    Não decide sozinho se é seguro reaplicar — dá ao operador humano/Gate
    a evidência pra decidir. Versões sem fingerprint cadastrado avisam e
    caem pra só reportar o status via `_migrations`.
    """
    await ensure_migrations_table(conn)
    applied = await get_applied(conn)
    tracked = version in applied

    print(f"\n=== Inspect: migration {version} ===")
    print(f"  tracked in _migrations: {tracked}")

    queries = INSPECTION_QUERIES.get(version)
    if not queries:
        print(f"  (sem fingerprint cadastrado para {version} — só o tracking acima é verificado)")
        print()
        return "APPLIED" if tracked else "UNKNOWN"

    signals: dict[str, bool] = {}
    for name, query in queries:
        try:
            value = await conn.fetchval(query)
        except Exception as exc:
            logger.warning("inspect(%s): sinal '%s' falhou ao consultar: %s", version, name, exc)
            value = None
        signals[name] = bool(value)
        print(f"  {name}: {value}")

    any_signal_true = any(signals.values())

    if tracked:
        verdict = "APPLIED"
    elif not any_signal_true:
        verdict = "CLEAN"
    else:
        verdict = "PARTIAL"

    print(f"  VERDICT: {verdict}")
    if verdict == "PARTIAL":
        print(
            "  ATENÇÃO: sinais de execução parcial encontrados sem tracking correspondente. "
            "NÃO rode --up direto — revise os sinais acima e decida uma migration de "
            "reconciliação versionada antes de reaplicar."
        )
    print()
    return verdict


async def main() -> None:
    parser = argparse.ArgumentParser(description="Cognitive migration runner")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--up", nargs="?", const="", metavar="VERSION",
                       help="Aplicar migrations (opcional: até VERSION)")
    group.add_argument("--down", type=int, metavar="TARGET",
                       help="Reverter migrations até (exclusive) TARGET (ex: --down 0 = reverter tudo)")
    group.add_argument("--status", action="store_true", help="Mostrar estado atual")
    group.add_argument("--verify", action="store_true", help="Verificar checksums de migrations aplicadas")
    group.add_argument("--inspect", metavar="VERSION",
                       help="Diagnosticar estado residual de uma migration antes de reaplicar")

    args = parser.parse_args()

    db_url = os.getenv("COGNITIVE_DB_ADMIN_URL",
                       "postgresql://cognitive_admin:dev-postgres-secret@localhost:5440/cognitive_dev")

    logger.info("Conectando ao banco: %s", safe_connection_target(db_url))
    conn = await asyncpg.connect(db_url)

    try:
        if args.status:
            await run_status(conn)
        elif args.verify:
            await ensure_migrations_table(conn)
            applied = await get_applied(conn)
            mismatches = []
            for version, path in MIGRATIONS:
                if version not in applied:
                    continue
                checksum = file_checksum(path)
                if applied[version] != checksum:
                    mismatches.append(version)
                    logger.error("CHECKSUM MISMATCH: %s", version)
            if mismatches:
                sys.exit(1)
            logger.info("Todos os checksums conferem (%d migrations aplicadas).", len(applied))
        elif args.inspect is not None:
            verdict = await inspect_migration(conn, args.inspect)
            if verdict == "PARTIAL":
                sys.exit(1)
        elif args.up is not None:
            target = args.up or None
            await run_up(conn, target)
        elif args.down is not None:
            await run_down(conn, args.down)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
