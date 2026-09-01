"""
canonical_finance_actor.py — resolve actor canônico a partir do principal de transporte.

Reusa FinanceActorDirectory (Cognitive) — o binding oficial FINANCE_ACTOR_BINDINGS.
NÃO inventa identidade. NÃO usa display name. NÃO usa JID como actor_id.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def ensure_finance_actor_bindings_env() -> None:
    """Carrega FINANCE_ACTOR_BINDINGS de HERMES_HOME/.env se ainda ausente."""
    if os.environ.get("FINANCE_ACTOR_BINDINGS", "").strip():
        return
    home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
    env_path = home / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        if key.strip() != "FINANCE_ACTOR_BINDINGS":
            continue
        os.environ["FINANCE_ACTOR_BINDINGS"] = val.strip().strip('"').strip("'")
        return


def resolve_canonical_finance_actor(transport_principal: str) -> str | None:
    """transport_principal (envelope.user_id) → actor canônico, ou None.

    Fonte: FINANCE_ACTOR_BINDINGS via FinanceActorDirectory (mesmo mecanismo
    da FinanceAcl no Cognitive). Fail-closed quando o principal não está mapeado.
    """
    principal = (transport_principal or "").strip()
    if not principal:
        return None
    ensure_finance_actor_bindings_env()
    try:
        from cognitive.policy.finance_acl import FinanceActorDirectory
    except ImportError:
        logger.warning("FinanceActorDirectory indisponível — canonical actor unresolved")
        return None
    actor_id = FinanceActorDirectory.from_env().resolve(principal)
    if not actor_id:
        logger.info(
            "canonical finance actor unresolved for transport principal (bindings miss)"
        )
    return actor_id or None


__all__ = [
    "ensure_finance_actor_bindings_env",
    "resolve_canonical_finance_actor",
]
