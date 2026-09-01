"""
finance_quoted_boot.py — eager wiring do FinanceReplyBinding (F2B).

O async quoted gate depende de get_active_finance_reply_binding().
Isso NÃO pode esperar a rota FINANCE carregar tools: a primeira
mensagem após restart pode ser só "Mercado" com reply_to.

Contrato:
  ensure_finance_quoted_binding_ready()  → idempotente, sem exigir
  Cognitive env no momento do boot (caller lazy monta no 1º I/O).

Readiness marker (journal):
  FINANCE_QUOTED_BINDING_READY=YES
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any

from .finance_reply_binding import (
    CapabilityCaller,
    FinanceReplyBinding,
    get_active_finance_reply_binding,
    install_router_hook,
)

logger = logging.getLogger(__name__)

READY_MARKER = "FINANCE_QUOTED_BINDING_READY=YES"

_ready_emitted = False


def f2b_fingerprint(value: str | None) -> str:
    """Fingerprint estável sem PII/JID/delivery id cru."""
    raw = (value or "").strip()
    if not raw:
        return "none"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _ensure_cognitive_env_from_dotenv() -> None:
    """Garante COGNITIVE_* no os.environ a partir de HERMES_HOME/.env se ausente."""
    if os.environ.get("COGNITIVE_GATEWAY_CREDENTIAL"):
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
        key = key.strip()
        if not key.startswith("COGNITIVE_"):
            continue
        if key not in os.environ or not os.environ.get(key):
            os.environ[key] = val.strip().strip('"').strip("'")


class LazyFinanceServiceCaller:
    """Caller que monta FinanceService só no primeiro uso (env já disponível)."""

    def __init__(self) -> None:
        self._svc: Any = None

    async def call(
        self,
        capability_id: str,
        params: dict[str, Any],
        *,
        channel: Any = None,
    ) -> dict[str, Any]:
        if self._svc is None:
            _ensure_cognitive_env_from_dotenv()
            from .finance_service import FinanceService

            self._svc = FinanceService.from_env()
        return await self._svc.call(capability_id, params, channel=channel)


def ensure_finance_quoted_binding_ready(
    *,
    caller: CapabilityCaller | None = None,
    force: bool = False,
) -> FinanceReplyBinding | None:
    """Instala FinanceReplyBinding de forma eager/idempotente.

    Preferir este entrypoint no boot do gateway e no import de finance_tools.
    NÃO depende de ter havido rota FINANCE ou tool call prévia.
    """
    global _ready_emitted

    existing = get_active_finance_reply_binding()
    if existing is not None and not force:
        if not _ready_emitted:
            logger.info(READY_MARKER)
            _ready_emitted = True
        return existing

    try:
        resolved_caller: CapabilityCaller = caller if caller is not None else LazyFinanceServiceCaller()
        binding = FinanceReplyBinding(resolved_caller)
        install_router_hook(binding)
        logger.info(READY_MARKER)
        _ready_emitted = True
        return binding
    except Exception as exc:  # noqa: BLE001 — fail-closed; NORMAL continua
        logger.warning(
            "F2B_GATE_EXCEPTION type=%s stage=boot F2B_FALLTHROUGH_REASON=BINDING_BOOT_FAILED",
            type(exc).__name__,
        )
        return None


def reset_finance_quoted_binding_ready_for_tests() -> None:
    """Só testes: limpa flag de emissão do marker (uninstall separado)."""
    global _ready_emitted
    _ready_emitted = False


__all__ = [
    "READY_MARKER",
    "LazyFinanceServiceCaller",
    "ensure_finance_quoted_binding_ready",
    "f2b_fingerprint",
    "reset_finance_quoted_binding_ready_for_tests",
]
