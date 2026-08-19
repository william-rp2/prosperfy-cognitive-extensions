"""Sanitize error messages and logs — never leak DSNs, bearer tokens or passwords."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

_DSN_RE = re.compile(
    r"postgresql(?:\+[\w]+)?://[^\s\"']+",
    re.IGNORECASE,
)

# Sprint 0.3 RETURN_TO_DEV (Item B): sanitização de strings que podem embutir
# o valor de um secret depois de passar por transporte/biblioteca. O caso real
# encontrado no gate-diagnóstico: o header HTTP do MCP foi recusado porque o
# secret carregava um CR (quebra de linha) e a mensagem da exceção do
# transporte embutia prefixos do Bearer (ex.: `Illegal header value
# b'Bearer 55a0ccf2...\r'`).
# Estas regras trocam o valor do token/header por `***` em qualquer string
# (exception, log, audit, telemetry, stdout de scripts). Redação é
# defense-in-depth; a FONTE do problema (CRLF na credencial) é rejeitada por
# validate_credential_no_control() antes de qualquer header ser montado.

_AUTHORIZATION_HEADER_RE = re.compile(
    r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[A-Za-z0-9._~+/=-]+"
)
_BEARER_TOKEN_RE = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]+")
_HEADER_VALUE_RE = re.compile(r"(?i)(illegal\s+header\s+value\b)([^\n]*)")


def redact_dsn(text: str) -> str:
    if not text:
        return text
    return _DSN_RE.sub("postgresql://***:***@***", text)


def sanitize_secrets(text: str) -> str:
    """Scruba segredos embutidos numa string qualquer (exception/log/audit).

    Pipeline (ordem importa): primeiro o caso mais específico de erro de
    header (remove o payload inteiro entre aspas), depois Authorization header
    e, por fim, qualquer valor que siga um Bearer literal.
    """
    if not text:
        return text
    text = redact_dsn(text)
    text = _HEADER_VALUE_RE.sub(r"\1 <redacted>", text)
    text = _AUTHORIZATION_HEADER_RE.sub(r"\1***", text)
    text = _BEARER_TOKEN_RE.sub(r"\1***", text)
    return text


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
    return sanitize_secrets(str(exc))


def validate_credential_no_control(credential: str, name: str = "credential") -> str:
    """Rejeita CR/LF e caracteres de controle na credencial (fail-closed).

    Sprint 0.3 RETURN_TO_DEV (Item B): um secret com `\r`/`\n` produzia o erro
    netlayered `Illegal header value b'Bearer 55a0ccf2...\r'` — a mensagem da
    exceção expunha prefixos do token real. Recusar a credencial ANTES de
    qualquer header/transporte elimina a origem. A mensagem de erro é estática
    (nunca ecoa o valor, nem parcial).
    """
    if not credential:
        return credential
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in credential):
        raise RuntimeError(
            f"{name} contém caractere de controle ou quebra de linha (CR/LF) — "
            "recusa fail-closed; limpe ou rotacione o secret antes de usar"
        )
    return credential


class SecretScrubbingFilter(logging.Filter):
    """Scruba segredos de records de logantes de TERCEIROS.

    Sprint 0.3 revisão adversarial (Item B): o controle primário
    (validate_credential_no_control) está correto, mas os logger do SDK
    (mcp/fastmcp/httpcore/httpx) emitem exceção de transporte com o valor
    embutido via `logger.exception`/`logger.debug` — fora do nosso código —
    quando detectam header inválido. Este filtro é defense-in-depth: neutraliza
    a mensagem (msg % args pré-interpolada) e a traceback (exc_text) antes de
    qualquer handler formatar o record.

    Uso: install_secret_scrubbing_filter() nos entrypoints (adapter do MCP,
    gate script, gateway).
    """

    def __init__(self) -> None:
        super().__init__()
        self._traceback_formatter = logging.Formatter()

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if record.args:
                record.msg = sanitize_secrets(record.msg % record.args)
                record.args = ()
            else:
                record.msg = sanitize_secrets(record.msg)
            if record.exc_info:
                raw = self._traceback_formatter.formatException(record.exc_info)
                record.exc_text = sanitize_secrets(raw)
                record.exc_info = None
        except Exception:  # nunca deixa o filtro quebrar o logging
            pass
        return True


_INSTALLED_LOGGERS: set[str] = set()


def install_secret_scrubbing_filter(loggers: tuple[str, ...] = (
    "mcp", "fastmcp", "httpcore", "httpx",
)) -> None:
    """Anexa SecretScrubbingFilter aos loggers de transporte de terceiros.

    Idempotente: cada nome de logger só recebe o filtro uma vez por processo.
    """
    for name in loggers:
        logger = logging.getLogger(name)
        if name in _INSTALLED_LOGGERS:
            continue
        _INSTALLED_LOGGERS.add(name)
        logger.addFilter(SecretScrubbingFilter())
