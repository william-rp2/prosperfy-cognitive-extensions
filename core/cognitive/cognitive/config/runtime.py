"""
config/runtime.py — Modo de execução do Cognitive Core.

COGNITIVE_MODE=in_memory  → Sprint 0.1 retrocompat; DB opcional
COGNITIVE_MODE=database   → DB obrigatório; fail-closed se indisponível

Se COGNITIVE_MODE ausente:
  - COGNITIVE_DB_URL presente → database
  - caso contrário → in_memory
"""

from __future__ import annotations

import os


def cognitive_mode() -> str:
    explicit = os.getenv("COGNITIVE_MODE", "").strip().lower()
    if explicit in ("in_memory", "in-memory", "memory"):
        return "in_memory"
    if explicit in ("database", "db"):
        return "database"
    if os.getenv("COGNITIVE_DB_URL"):
        return "database"
    return "in_memory"


def is_in_memory_mode() -> bool:
    return cognitive_mode() == "in_memory"


def is_database_mode() -> bool:
    return cognitive_mode() == "database"


def require_database_config() -> None:
    """
    Levanta RuntimeError se modo database sem DSNs mínimos.

    COGNITIVE_DB_URL (cognitive_app) é obrigatório: é o pool usado para
    servir tráfego, incluindo resolução de identidade (SEC-001, Sprint 0.3).

    COGNITIVE_DB_ADMIN_URL (cognitive_admin, BYPASSRLS) NÃO é mais
    obrigatório para o processo web público — só é necessário para
    migrations e bootstrap/CLI de credenciais (scripts separados). Se
    ausente, o Gateway inicia e serve autenticação/identity resolution
    normalmente; apenas register()/deactivate() de service identity
    (chamados fora do processo web) exigiriam essa variável.
    """
    if not is_database_mode():
        return
    missing = [
        name
        for name in ("COGNITIVE_DB_URL",)
        if not os.getenv(name)
    ]
    if missing:
        raise RuntimeError(
            "COGNITIVE_MODE=database exige variáveis configuradas: "
            + ", ".join(missing)
        )
