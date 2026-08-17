"""Safe PostgreSQL DSN construction with sslmode=require."""

from __future__ import annotations

from urllib.parse import quote_plus, urlencode

DEFAULT_SSLMODE = "require"
DEFAULT_PORT = 5432
DEFAULT_DATABASE = "postgres"


def build_postgres_dsn(
    *,
    user: str,
    password: str,
    host: str,
    port: int = DEFAULT_PORT,
    database: str = DEFAULT_DATABASE,
    sslmode: str = DEFAULT_SSLMODE,
) -> str:
    """
    Build asyncpg-compatible PostgreSQL URI with proper escaping.

    Passwords with special characters (@, :, /, etc.) are URL-encoded.
    """
    user_enc = quote_plus(user)
    password_enc = quote_plus(password)
    query = urlencode({"sslmode": sslmode})
    return f"postgresql://{user_enc}:{password_enc}@{host}:{port}/{database}?{query}"


def build_supabase_role_dsn(
    *,
    project_ref: str,
    role: str,
    password: str,
    port: int = DEFAULT_PORT,
    database: str = DEFAULT_DATABASE,
    sslmode: str = DEFAULT_SSLMODE,
) -> str:
    host = f"db.{project_ref}.supabase.co"
    return build_postgres_dsn(
        user=role,
        password=password,
        host=host,
        port=port,
        database=database,
        sslmode=sslmode,
    )


def host_from_admin_dsn(admin_dsn: str) -> tuple[str, int, str]:
    """Extract host, port, database from admin DSN for non-Supabase test DBs."""
    from urllib.parse import urlparse

    parsed = urlparse(admin_dsn)
    host = parsed.hostname or "localhost"
    port = parsed.port or DEFAULT_PORT
    database = (parsed.path or f"/{DEFAULT_DATABASE}").lstrip("/") or DEFAULT_DATABASE
    return host, port, database
