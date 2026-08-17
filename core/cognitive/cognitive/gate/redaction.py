"""Sanitize error messages and logs — never leak DSNs or passwords."""

from __future__ import annotations

import re
from urllib.parse import urlparse

_DSN_RE = re.compile(
    r"postgresql(?:\+[\w]+)?://[^\s\"']+",
    re.IGNORECASE,
)


def redact_dsn(text: str) -> str:
    if not text:
        return text
    return _DSN_RE.sub("postgresql://***:***@***", text)


def safe_connection_target(dsn: str) -> str:
    """Host/port/database only — safe for logs."""
    if not dsn:
        return "unknown"
    parsed = urlparse(dsn)
    host = parsed.hostname or "unknown"
    port = parsed.port or 5432
    db = (parsed.path or "/postgres").lstrip("/") or "postgres"
    return f"{host}:{port}/{db}"


def sanitize_exception(exc: BaseException) -> str:
    return redact_dsn(str(exc))
