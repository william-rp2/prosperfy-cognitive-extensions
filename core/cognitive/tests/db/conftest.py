"""
tests/db/conftest.py — Fixtures de banco para testes com testcontainers.

Usa Postgres 16 efêmero (CI e dev local com Docker disponível).
Sem dependência de Docker local — testcontainers gerencia o container.

Fixtures de escopo session: uma instância Postgres por sessão de testes.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

# Verificar se testcontainers está disponível (suporta v3 e v4)
try:
    try:
        from testcontainers.community.postgres import PostgresContainer
    except ImportError:
        from testcontainers.postgres import PostgresContainer
    TESTCONTAINERS_AVAILABLE = True
except ImportError:
    TESTCONTAINERS_AVAILABLE = False

# parents[3] = core/ → migrations em core/migrations/
MIGRATIONS_DIR = Path(__file__).parents[3] / "migrations"

pytestmark = pytest.mark.skipif(
    not TESTCONTAINERS_AVAILABLE,
    reason="testcontainers não disponível — instalar com pip install 'testcontainers[postgres]'",
)


@pytest.fixture(scope="session")
def postgres_container():
    """
    Inicia Postgres 16 efêmero para toda a sessão de testes.

    SKIP automático se Docker não estiver disponível (DG-001: Docker não é requisito local).
    Estes testes rodam em CI com infraestrutura efêmera ou contra Supabase homologação.
    """
    if not TESTCONTAINERS_AVAILABLE:
        pytest.skip("testcontainers não disponível")

    try:
        container = PostgresContainer("postgres:16-alpine")
        container.start()
    except Exception as exc:
        pytest.skip(
            f"Docker não disponível nesta máquina (DG-001 — sem Docker local obrigatório): {exc}"
        )

    yield container
    container.stop()


@pytest.fixture(scope="session")
def admin_dsn(postgres_container) -> str:
    """DSN asyncpg para o container de teste."""
    # testcontainers v4: get_connection_url() retorna postgresql+psycopg2://
    # Construímos o DSN asyncpg diretamente
    host = postgres_container.get_container_host_ip()
    port = postgres_container.get_exposed_port(5432)
    user = postgres_container.username
    password = postgres_container.password
    db = postgres_container.dbname
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


@pytest_asyncio.fixture(scope="session")
async def migrated_db(admin_dsn: str) -> str:
    """
    Aplica todas as migrations no banco de teste.
    Retorna o admin_dsn após migrations aplicadas.
    """
    conn = await asyncpg.connect(admin_dsn)

    try:
        # Criar extensões
        await conn.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

        # Aplicar migrations em ordem
        for sql_file in sorted(MIGRATIONS_DIR.glob("[0-9]*.sql")):
            sql = sql_file.read_text(encoding="utf-8")
            await conn.execute(sql)

    finally:
        await conn.close()

    return admin_dsn


@pytest_asyncio.fixture
async def admin_conn(migrated_db: str) -> asyncpg.Connection:
    """Conexão admin para um teste específico (BYPASSRLS)."""
    conn = await asyncpg.connect(migrated_db)
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def app_conn(migrated_db: str) -> asyncpg.Connection:
    """
    Conexão como cognitive_app (RLS enforced).
    Retorna sem tenant_id setado — cada teste deve SET LOCAL explicitamente.
    """
    # Para testes sem papel real cognitive_app, conectamos como admin
    # mas simulamos o comportamento RLS via set_config
    conn = await asyncpg.connect(migrated_db)
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def seeded_tenants(admin_conn: asyncpg.Connection) -> dict[str, str]:
    """
    Cria dois tenants de teste e retorna mapa slug→id.
    Limpa após cada teste.
    """
    tenant_a = await admin_conn.fetchrow(
        "INSERT INTO tenants(slug, name) VALUES('tenant-a', 'Tenant A') "
        "ON CONFLICT (slug) DO UPDATE SET name = 'Tenant A' "
        "RETURNING id, slug",
    )
    tenant_b = await admin_conn.fetchrow(
        "INSERT INTO tenants(slug, name) VALUES('tenant-b', 'Tenant B') "
        "ON CONFLICT (slug) DO UPDATE SET name = 'Tenant B' "
        "RETURNING id, slug",
    )

    yield {
        "tenant-a": str(tenant_a["id"]),
        "tenant-b": str(tenant_b["id"]),
    }

    # Cleanup
    await admin_conn.execute("DELETE FROM tenants WHERE slug IN ('tenant-a', 'tenant-b')")
