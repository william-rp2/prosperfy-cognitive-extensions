"""
audit/redaction.py — Redação de campos sensíveis em payloads de audit.

R14: credentials ficam em secret store e são referenciadas por IDs.
Nunca armazenadas como conhecimento ou entregues à LLM.
Campos configuráveis via COGNITIVE_LOG_REDACT_FIELDS e redaction_rules da capability.
"""

from __future__ import annotations

import os
from typing import Any

# Campos sempre redigidos (independente de configuração)
_ALWAYS_REDACT = frozenset({"password", "secret", "token", "api_key", "credential", "bearer"})

# Campos adicionais via variável de ambiente
_ENV_REDACT = frozenset(
    f.strip().lower()
    for f in os.getenv("COGNITIVE_LOG_REDACT_FIELDS", "").split(",")
    if f.strip()
)

_REDACTED_VALUE = "***REDACTED***"


def redact(
    data: dict[str, Any],
    extra_fields: list[str] | None = None,
) -> dict[str, Any]:
    """
    Percorre recursivamente o dict e substitui valores de campos sensíveis.

    Não modifica o dict original — retorna cópia redacted.
    """
    fields_to_redact = _ALWAYS_REDACT | _ENV_REDACT | frozenset(
        f.lower() for f in (extra_fields or [])
    )
    return _redact_recursive(data, fields_to_redact)


def _redact_recursive(obj: Any, fields: frozenset[str]) -> Any:
    if isinstance(obj, dict):
        return {
            k: _REDACTED_VALUE if k.lower() in fields else _redact_recursive(v, fields)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_recursive(item, fields) for item in obj]
    return obj
