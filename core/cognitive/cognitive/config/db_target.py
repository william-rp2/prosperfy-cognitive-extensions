"""
db_target.py — Verificação segura de project ref Supabase (sem expor secrets).
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

HOMOLOG_PROJECT_REF = "esvjfkknrzzziafovwrv"
FORBIDDEN_PROJECT_REF = "wioorhtdwnfujkrynxij"

_REF_RE = re.compile(r"db\.([a-z0-9]+)\.supabase")


def project_ref_from_dsn(dsn: str) -> str | None:
    if not dsn:
        return None
    host = urlparse(dsn).hostname or ""
    match = _REF_RE.search(host)
    return match.group(1) if match else None


def verify_homolog_admin_dsn(dsn: str) -> tuple[bool, str]:
    """
    Retorna (ok, reason).
    Nunca inclui secrets na reason.
    """
    if not dsn:
        return False, "COGNITIVE_DB_ADMIN_URL not configured"
    ref = project_ref_from_dsn(dsn)
    if ref is None:
        return False, "host is not a recognized Supabase project ref"
    if ref == FORBIDDEN_PROJECT_REF:
        return False, "forbidden production project ref"
    if ref != HOMOLOG_PROJECT_REF:
        return False, f"expected homolog ref {HOMOLOG_PROJECT_REF}, got {ref}"
    return True, "verified"
