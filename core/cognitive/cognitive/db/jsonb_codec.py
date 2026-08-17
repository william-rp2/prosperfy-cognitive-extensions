"""
jsonb_codec.py — Fronteira consistente Python ↔ PostgreSQL JSONB.

Write: dict/list → JSON string (ou SQL NULL quando value is None).
Read: str/dict/list → dict/list Python; SQL NULL → None (ou default object).
"""

from __future__ import annotations

import json
from typing import Any


class JsonbCodecError(TypeError):
    """Valor incompatível com contrato JSONB."""


def serialize_jsonb(value: dict[str, Any] | list[Any] | None) -> str | None:
    """
    Serializa valor para parâmetro JSONB do asyncpg.

    None → SQL NULL (não confundir com JSON null literal).
    """
    if value is None:
        return None
    if not isinstance(value, (dict, list)):
        raise JsonbCodecError(
            f"serialize_jsonb espera dict, list ou None; recebeu {type(value).__name__}"
        )
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def deserialize_jsonb(value: Any) -> dict[str, Any] | list[Any] | None:
    """
    Desserializa coluna JSONB para Python.

    None → SQL NULL.
    str → json.loads.
    dict/list → retorno direto (codec/driver já decodificou).
    """
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        return json.loads(value)
    if isinstance(value, (bytes, bytearray)):
        return json.loads(value.decode("utf-8"))
    raise JsonbCodecError(
        f"deserialize_jsonb não suporta {type(value).__name__}"
    )


def deserialize_jsonb_object(
    value: Any,
    *,
    default: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Colunas JSONB NOT NULL object — SQL NULL retorna default ({})."""
    decoded = deserialize_jsonb(value)
    if decoded is None:
        return {} if default is None else default
    if not isinstance(decoded, dict):
        raise JsonbCodecError(
            f"esperado object JSONB; recebeu {type(decoded).__name__}"
        )
    return decoded
