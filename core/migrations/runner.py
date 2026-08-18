"""
migrations/runner.py — Migration runner minimalista para o Cognitive Core.

Sem Alembic — dependência pesada desnecessária para Sprint 0.2.
Conecta via COGNITIVE_DB_ADMIN_URL — a identidade admin do ambiente
(`postgres` no Supabase, `cognitive_admin` no docker-compose.dev.yml
local) para criar/destruir schema. Migrations nunca assumem que essa
identidade tem um nome fixo (ver SEC-003 em 002_*.sql).

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
                                       # aceita prefixo curto ("002") ou stem completo
  python runner.py --diagnose         # raio-x READ-ONLY do banco inteiro (000/001/002 +
                                       # _migrations) — usar quando _migrations não é confiável
  python runner.py --recover-tracking # ÚNICO comando que escreve — reconstrói só a linha de
                                       # tracking em _migrations, e só quando o diagnóstico
                                       # provar TRACKING_MISSING_ONLY (schema intacto, tracking
                                       # ausente)

Incidente Sprint 0.3 (VPS/Homolog Gate): um teste destrutivo derrubou a
tabela `_migrations` depois de 000/001/002 terem sido aplicadas com
sucesso em Homolog. `--diagnose`/`--recover-tracking` existem pra esse
cenário — determinar o estado REAL do schema sem depender de
`_migrations`, e reconstruir só o tracking quando o schema já está
comprovadamente intacto.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone

import asyncpg

# Redaction for safe logging (host only) + verificação de target Homolog
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cognitive"))
try:
    from cognitive.gate.redaction import safe_connection_target
except ImportError:
    def safe_connection_target(dsn: str) -> str:
        return dsn.split("@")[-1] if "@" in dsn else "unknown"

try:
    from cognitive.config.db_target import verify_homolog_admin_dsn
except ImportError:
    def verify_homolog_admin_dsn(dsn: str) -> tuple[bool, str]:
        return False, "cognitive.config.db_target indisponível"

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
# do banco. Não substitui `_migrations` como fonte de verdade sobre "está
# aplicada" — é um raio-x pra decidir se é seguro reaplicar depois de uma
# falha no meio do arquivo.
#
# IMPORTANTE: nem todo sinal é "false no estado limpo, true se algo de X
# rodou". Alguns sinais vêm de uma migration ANTERIOR (ex.: 001 já concede
# SELECT direto em service_identities e cria a policy tenant_isolation —
# 002 é quem REVOGA isso). Esses são true no estado limpo (só 001 aplicada)
# e só viram false depois que 002 termina. Comparar cada sinal contra um
# fingerprint completo esperado (CLEAN vs APPLIED), em vez de um `any()`
# genérico, evita classificar o estado limpo como resíduo por engano.
INSPECTION_QUERIES: dict[str, list[tuple[str, str]]] = {
    "002": [
        (
            "function_exists",
            # to_regprocedure() (não o cast ::regprocedure) retorna NULL em vez
            # de lançar erro quando a função não existe — importante porque
            # este sinal PRECISA resolver limpo (False) no estado CLEAN, sem
            # logar um "falhou ao consultar" falso-positivo.
            "SELECT to_regprocedure('resolve_service_identity_by_credential_hash(text)') "
            "IS NOT NULL AS v",
        ),
        (
            "function_owner_is_not_app_or_worker",
            # Checa por MEMBERSHIP (pg_has_role), não só por nome do owner —
            # cobre tanto "owner se chama cognitive_app/worker" quanto
            # "app/worker de alguma forma ganharam membership no owner real"
            # (hoje nunca acontece, ver 000/001, mas o sinal deve detectar
            # se algum dia acontecer, não só comparar string).
            "SELECT COALESCE((SELECT NOT pg_has_role('cognitive_app', proowner, 'MEMBER') "
            "AND NOT pg_has_role('cognitive_worker', proowner, 'MEMBER') "
            "FROM pg_proc WHERE oid = to_regprocedure("
            "'resolve_service_identity_by_credential_hash(text)')), false) AS v",
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

# Fingerprint esperado ANTES de 002 rodar (só 001 aplicada) — note que os
# dois últimos sinais são True aqui (herdados de 001), não False.
EXPECTED_CLEAN: dict[str, dict[str, bool]] = {
    "002": {
        "function_exists": False,
        "function_owner_is_not_app_or_worker": False,
        "public_has_execute_on_function": False,
        "cognitive_app_has_direct_select_on_table": True,
        "old_tenant_isolation_policy_exists": True,
    },
}

# Fingerprint esperado depois que 002 termina com sucesso (mesmo que a
# transação ainda não tenha sido commitada como tracking — ver
# "applied_but_untracked" abaixo).
EXPECTED_APPLIED: dict[str, dict[str, bool]] = {
    "002": {
        "function_exists": True,
        "function_owner_is_not_app_or_worker": True,
        "public_has_execute_on_function": False,
        "cognitive_app_has_direct_select_on_table": False,
        "old_tenant_isolation_policy_exists": False,
    },
}


def resolve_migration_version(query: str) -> str:
    """Resolves a short numeric prefix or full stem to the canonical full
    stem matching a file in MIGRATIONS. Exact match wins; otherwise unique
    prefix match; otherwise raises ValueError (fail-closed — never guess)."""
    query = query.strip()
    exact = [stem for stem, _ in MIGRATIONS if stem == query]
    if exact:
        return exact[0]
    prefix_matches = [stem for stem, _ in MIGRATIONS if stem.startswith(query)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    if not prefix_matches:
        raise ValueError(f"versão de migration desconhecida: {query!r}")
    raise ValueError(f"prefixo ambíguo {query!r}: bate com {prefix_matches}")


async def inspect_migration(conn: asyncpg.Connection, version: str) -> str:
    """
    Roda o fingerprint de `version` e imprime um diagnóstico legível.
    Não decide sozinho se é seguro reaplicar — dá ao operador humano/Gate
    a evidência pra decidir. Versões sem fingerprint cadastrado avisam e
    caem pra só reportar o status via `_migrations`.

    `version` aceita tanto o prefixo curto ("002") quanto o stem completo
    do arquivo ("002_service_identities_lookup_least_privilege") — ver
    `resolve_migration_version()`. `_migrations.version` sempre grava o
    stem completo (ver `apply_one_migration()`); comparar um prefixo curto
    cru contra essa coluna (bug histórico corrigido aqui) sempre dava
    tracked=False mesmo quando a migration estava de fato rastreada.

    Com o runner atômico (cada migration = uma transação), um estado
    "rodou até a metade e ficou assim" não deveria mais acontecer daqui pra
    frente — isso serve principalmente pra diagnosticar incidentes
    históricos (rodados sob uma versão anterior do runner, sem transação) e
    como cinto-de-segurança caso a suposição de atomicidade do Postgres
    falhe por algum motivo não previsto.
    """
    try:
        canonical = resolve_migration_version(version)
    except ValueError as exc:
        print(f"\n=== Inspect: migration {version!r} ===")
        print(f"  ERROR: {exc}")
        print("  VERDICT: INVALID_VERSION")
        print()
        return "INVALID_VERSION"

    await ensure_migrations_table(conn)
    applied = await get_applied(conn)
    tracked = canonical in applied

    print(f"\n=== Inspect: migration {canonical} ===")
    print(f"  tracked in _migrations: {tracked}")

    # INSPECTION_QUERIES/EXPECTED_CLEAN/EXPECTED_APPLIED continuam
    # indexados pelo prefixo curto (ex: "002") por legibilidade — deriva
    # do stem canônico já resolvido acima.
    short_key = canonical.split("_", 1)[0]
    queries = INSPECTION_QUERIES.get(short_key)
    if not queries:
        print(f"  (sem fingerprint cadastrado para {short_key} — só o tracking acima é verificado)")
        print()
        return "APPLIED" if tracked else "UNKNOWN"

    signals: dict[str, bool | None] = {}
    for name, query in queries:
        try:
            value = await conn.fetchval(query)
        except Exception as exc:
            logger.warning("inspect(%s): sinal '%s' falhou ao consultar: %s", canonical, name, exc)
            signals[name] = None
            print(f"  {name}: None (query falhou — ver log)")
            continue
        # Nunca coagir a bool() incondicionalmente: bool(None) == False
        # coincidiria silenciosamente com o valor "seguro" esperado por
        # sinais sensíveis (ex.: PUBLIC sem EXECUTE), mascarando uma
        # falha de consulta como "confirmado seguro". None nunca bate
        # igualdade com um EXPECTED_CLEAN/EXPECTED_APPLIED (só têm
        # True/False) — cai em PARTIAL corretamente (fail-closed).
        signals[name] = value if value is None else bool(value)
        print(f"  {name}: {value}")

    expected_clean = EXPECTED_CLEAN.get(short_key)
    expected_applied = EXPECTED_APPLIED.get(short_key)

    if tracked:
        verdict = "APPLIED"
    elif expected_clean is not None and signals == expected_clean:
        verdict = "CLEAN"
    elif expected_applied is not None and signals == expected_applied:
        # Sinais batem 100% com "terminou com sucesso", mas sem tracking —
        # só é possível sob o runner antigo (não-atômico) ou se alguém
        # rodou o SQL manualmente. Distinto de um resíduo confuso/parcial:
        # aqui dá pra confiar que basta rodar --up de novo (todo statement
        # de 002 é idempotente) pra fechar o tracking, sem reconciliação.
        verdict = "APPLIED_BUT_UNTRACKED"
    else:
        verdict = "PARTIAL"

    print(f"  VERDICT: {verdict}")
    if verdict == "APPLIED_BUT_UNTRACKED":
        print(
            "  Sinais batem exatamente com 'aplicada com sucesso', mas falta o tracking "
            "row — provável artefato do runner anterior (não-atômico). Todo statement "
            "desta migration é idempotente; rodar --up de novo deve só fechar o "
            "tracking, sem side-effect adicional. Revise mesmo assim antes de prosseguir."
        )
    elif verdict == "PARTIAL":
        print(
            "  ATENÇÃO: sinais não batem com nenhum fingerprint conhecido (nem limpo, nem "
            "aplicado). NÃO rode --up direto — revise os sinais acima e decida uma "
            "migration de reconciliação versionada antes de reaplicar."
        )
    print()
    return verdict


# ─── Diagnose / Recover-tracking: raio-x READ-ONLY do banco + reconstrução ──
# do tracking (hotfix pós-incidente Homolog: um teste destrutivo derrubou
# `_migrations` depois de 000/001/002 terem sido aplicadas com sucesso).
#
# `--diagnose` NUNCA escreve — só SELECT (mesmo estilo de INSPECTION_QUERIES
# acima, reaproveitado verbatim para 002). `--recover-tracking` é o ÚNICO
# comando com um write path neste hotfix, e só age quando o diagnóstico
# provar TRACKING_MISSING_ONLY (schema/roles/RLS de 000/001/002
# comprovadamente intactos, só falta a linha de tracking) — nunca "perto o
# suficiente".

DIAGNOSE_TABLES_000 = [
    "tenants", "tenant_members", "tenant_resources",
    "credential_refs", "tenant_integrations", "capability_grants",
]

DIAGNOSE_QUERIES_000: list[tuple[str, str]] = (
    [
        (f"table_{t}_exists", f"SELECT to_regclass('public.{t}') IS NOT NULL AS v")
        for t in DIAGNOSE_TABLES_000
    ]
    + [
        (
            "role_cognitive_admin_bypassrls",
            "SELECT COALESCE((SELECT rolbypassrls FROM pg_roles "
            "WHERE rolname = 'cognitive_admin'), false) AS v",
        ),
        (
            "role_cognitive_app_exists",
            "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cognitive_app') AS v",
        ),
        (
            "role_cognitive_worker_exists",
            "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cognitive_worker') AS v",
        ),
    ]
    + [
        (
            f"rls_{t}_enabled",
            "SELECT COALESCE((SELECT relrowsecurity FROM pg_class "
            f"WHERE oid = to_regclass('public.{t}')), false) AS v",
        )
        for t in DIAGNOSE_TABLES_000
    ]
)

EXPECTED_PRESENT_000: dict[str, bool] = {name: True for name, _ in DIAGNOSE_QUERIES_000}

DIAGNOSE_TABLES_001 = [
    "service_identities", "audit_events", "execution_traces", "cost_telemetry",
]

DIAGNOSE_QUERIES_001: list[tuple[str, str]] = (
    [
        (f"table_{t}_exists", f"SELECT to_regclass('public.{t}') IS NOT NULL AS v")
        for t in DIAGNOSE_TABLES_001
    ]
    + [
        (
            f"rls_{t}_enabled",
            "SELECT COALESCE((SELECT relrowsecurity FROM pg_class "
            f"WHERE oid = to_regclass('public.{t}')), false) AS v",
        )
        for t in DIAGNOSE_TABLES_001
    ]
)

EXPECTED_PRESENT_001: dict[str, bool] = {name: True for name, _ in DIAGNOSE_QUERIES_001}


async def migrations_table_exists(conn: asyncpg.Connection) -> bool:
    """Checagem READ-ONLY de existência de `_migrations` — nunca chamar
    `ensure_migrations_table()` (CREATE TABLE IF NOT EXISTS, um write) a
    partir de `--diagnose`."""
    return bool(await conn.fetchval("SELECT to_regclass('public._migrations') IS NOT NULL AS v"))


async def collect_signals(
    conn: asyncpg.Connection, queries: list[tuple[str, str]]
) -> dict[str, bool | None]:
    """
    Retorna True/False para sucesso, None para falha de consulta —
    NUNCA coage None para False. `bool(None) == False` colidiria
    silenciosamente com o valor esperado de sinais sensíveis (ex.: 002
    "PUBLIC sem EXECUTE" espera False no estado saudável), mascarando um
    erro de query como "confirmado seguro". Um None em qualquer sinal
    garante que nenhum EXPECTED_* (só contém True/False) bate por
    igualdade, então `classify_diagnosis`/`inspect_migration` caem em
    UNKNOWN_UNSAFE_STATE/PARTIAL — fail-closed, nunca fail-open.
    """
    signals: dict[str, bool | None] = {}
    for name, query in queries:
        try:
            value = await conn.fetchval(query)
        except Exception as exc:
            logger.warning("diagnose: sinal '%s' falhou ao consultar: %s", name, exc)
            signals[name] = None
            continue
        signals[name] = value if value is None else bool(value)
    return signals


@dataclass(frozen=True)
class DiagnosisResult:
    verdict: str
    # bool = sinal coletado com sucesso; None = a query falhou (ver
    # collect_signals) — nunca coagido a False, pra não mascarar erro de
    # consulta como "confirmado seguro".
    signals_000: dict[str, bool | None]
    signals_001: dict[str, bool | None]
    signals_002: dict[str, bool | None]
    # "000"/"001"/"002" -> True (tracked, checksum bate) / False (tracked,
    # checksum não bate) / None (nenhuma linha de tracking pra essa versão)
    tracked: dict[str, bool | None]


def classify_diagnosis(
    signals_000: dict[str, bool | None],
    signals_001: dict[str, bool | None],
    signals_002: dict[str, bool | None],
    tracked: dict[str, bool | None],
) -> str:
    """
    Lógica pura de classificação — sem I/O, testável sem Postgres real
    (mesmo padrão de `inspect_migration`: separa "consulta o banco" de
    "decide o veredito" a partir de sinais já coletados).
    """
    present_000 = signals_000 == EXPECTED_PRESENT_000
    present_001 = signals_001 == EXPECTED_PRESENT_001
    present_002 = signals_002 == EXPECTED_APPLIED["002"]
    clean_002 = signals_002 == EXPECTED_CLEAN["002"]
    absent_001 = bool(signals_001) and all(v is False for v in signals_001.values())

    if present_000 and present_001 and present_002:
        if all(tracked.get(k) is True for k in ("000", "001", "002")):
            return "HEALTHY"
        if all(tracked.get(k) is None for k in ("000", "001", "002")):
            return "TRACKING_MISSING_ONLY"
        # Schema 100% intacto mas tracking num estado misto (algumas linhas
        # batem, outras faltam ou têm checksum divergente) — não é nem
        # "tudo rastreado certo" nem "tracking totalmente ausente".
        # Fail-closed: não é seguro pro --recover-tracking agir sozinho.
        return "UNKNOWN_UNSAFE_STATE"

    if present_000 and present_001 and clean_002:
        # 002 nunca rodou — estado normal, esperado, seguro (não é
        # corrupção). Independe do estado de tracking: se 002 nunca rodou,
        # não deveria mesmo estar rastreada.
        return "MIGRATION_002_MISSING"

    if present_000 and not present_001 and not absent_001:
        # 000 completo, mas 001 nem totalmente ausente nem totalmente
        # presente — estado genuinamente ambíguo dentro do foundation
        # schema.
        return "SCHEMA_PARTIAL"

    return "UNKNOWN_UNSAFE_STATE"


async def diagnose_database(conn: asyncpg.Connection) -> DiagnosisResult:
    """
    Raio-x READ-ONLY do estado real do banco — usado quando `_migrations`
    não é confiável (ex: dropada por engano). Só SELECT: nenhum
    CREATE/ALTER/DROP/INSERT/UPDATE/DELETE roda aqui, nem sequer
    `ensure_migrations_table()` (que faz CREATE TABLE IF NOT EXISTS).
    """
    signals_000 = await collect_signals(conn, DIAGNOSE_QUERIES_000)
    signals_001 = await collect_signals(conn, DIAGNOSE_QUERIES_001)
    signals_002 = await collect_signals(conn, INSPECTION_QUERIES["002"])

    if await migrations_table_exists(conn):
        applied = await get_applied(conn)
    else:
        applied = {}

    tracked: dict[str, bool | None] = {}
    for short in ("000", "001", "002"):
        canonical = resolve_migration_version(short)
        path = dict(MIGRATIONS)[canonical]
        expected_checksum = file_checksum(path)
        if canonical not in applied:
            tracked[short] = None
        elif applied[canonical] == expected_checksum:
            tracked[short] = True
        else:
            tracked[short] = False

    verdict = classify_diagnosis(signals_000, signals_001, signals_002, tracked)
    return DiagnosisResult(
        verdict=verdict,
        signals_000=signals_000,
        signals_001=signals_001,
        signals_002=signals_002,
        tracked=tracked,
    )


def print_diagnosis_report(result: DiagnosisResult) -> None:
    print("\n=== Diagnose: estado real do banco (independente de _migrations) ===")

    print("\n--- 000_foundation_tenancy ---")
    for name, value in result.signals_000.items():
        print(f"  {name}: {value}")

    print("\n--- 001_capability_registry_audit ---")
    for name, value in result.signals_001.items():
        print(f"  {name}: {value}")

    print("\n--- 002_service_identities_lookup_least_privilege ---")
    for name, value in result.signals_002.items():
        print(f"  {name}: {value}")

    print("\n--- _migrations tracking ---")
    status_label = {True: "MATCH", False: "CHECKSUM MISMATCH", None: "ABSENT"}
    for short, status in result.tracked.items():
        print(f"  {short}: {status_label[status]}")

    print(f"\nVERDICT: {result.verdict}")
    print()


async def run_diagnose(conn: asyncpg.Connection) -> DiagnosisResult:
    result = await diagnose_database(conn)
    print_diagnosis_report(result)
    return result


async def run_recover_tracking(conn: asyncpg.Connection, db_url: str) -> None:
    """
    ÚNICO comando deste hotfix com um write path — e mesmo assim escreve
    exclusivamente em `_migrations`. Nunca toca tabela, role, policy ou
    função de negócio.

    1. Guarda de alvo: recusa qualquer DSN que não verifique como o project
       ref Homolog (mesmo helper usado por conftest.py/verify_target.py —
       nunca reimplementado aqui).
    2. Roda `diagnose_database()` (read-only) internamente.
    3. Só escreve se o veredito for EXATAMENTE TRACKING_MISSING_ONLY —
       "perto o suficiente" não conta; qualquer outro veredito recusa e sai
       com exit 1 sem tentar nenhum write.
    4. Escreve dentro de UMA transação explícita, mesmo contrato de
       atomicidade do resto deste arquivo: CREATE TABLE IF NOT EXISTS
       (reaproveita `ensure_migrations_table`, idempotente) + 3 INSERTs
       (ON CONFLICT DO NOTHING, idempotente) com checksum sempre derivado
       do arquivo em disco agora — nunca aceito como input do operador.
    """
    ok, reason = verify_homolog_admin_dsn(db_url)
    if not ok:
        print(f"RECOVERY REFUSED — DSN não verifica como Homolog: {reason}")
        sys.exit(1)

    result = await diagnose_database(conn)
    print_diagnosis_report(result)

    if result.verdict == "HEALTHY":
        print("RECOVERY SKIPPED — banco já está HEALTHY, nenhuma ação necessária.")
        return

    if result.verdict != "TRACKING_MISSING_ONLY":
        print(
            "RECOVERY REFUSED — verdict não é TRACKING_MISSING_ONLY, revisão humana necessária"
        )
        sys.exit(1)

    inserted: list[tuple[str, str]] = []
    async with conn.transaction():
        await ensure_migrations_table(conn)
        for short in ("000", "001", "002"):
            canonical = resolve_migration_version(short)
            path = dict(MIGRATIONS)[canonical]
            checksum = file_checksum(path)
            await conn.execute(
                "INSERT INTO _migrations(version, checksum) VALUES($1, $2) "
                "ON CONFLICT (version) DO NOTHING",
                canonical, checksum,
            )
            inserted.append((canonical, checksum))

    for canonical, checksum in inserted:
        print(f"  inserted: {canonical} (checksum={checksum})")
    print("RECOVERY COMPLETE")


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
                       help="Diagnosticar estado residual de uma migration antes de reaplicar "
                            "(aceita prefixo curto ou stem completo)")
    group.add_argument("--diagnose", action="store_true",
                       help="Raio-x READ-ONLY do banco inteiro (000/001/002 + _migrations) — "
                            "usar quando _migrations não é confiável")
    group.add_argument("--recover-tracking", action="store_true",
                       help="ÚNICO comando que escreve — reconstrói a linha de tracking em "
                            "_migrations, só quando o diagnóstico provar TRACKING_MISSING_ONLY")

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
            if verdict in ("PARTIAL", "INVALID_VERSION"):
                sys.exit(1)
        elif args.diagnose:
            result = await run_diagnose(conn)
            if result.verdict not in ("HEALTHY", "TRACKING_MISSING_ONLY", "MIGRATION_002_MISSING"):
                sys.exit(1)
        elif args.recover_tracking:
            await run_recover_tracking(conn, db_url)
        elif args.up is not None:
            target = args.up or None
            await run_up(conn, target)
        elif args.down is not None:
            await run_down(conn, args.down)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
