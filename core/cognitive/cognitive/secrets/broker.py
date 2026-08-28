"""
secrets/broker.py -- SecretBroker (Track BH, doc 00 Sec.6.1).

Hard rule: the LLM/Cognitive side receives metadata and a reference
(SecretRef), never the plaintext value. There is deliberately NO method on
this class that returns a secret value -- the value is read exactly once,
by the Browser Worker process itself, directly from its local 0600 file, at
the instant a form field is filled (ops/browser-worker/worker.py,
resolve_fields()). This module only creates/references that file remotely
via the existing ProsperfySkillsAdapter transport (prosperfy_vps_escrever_
arquivo / prosperfy_vps_executar) -- it never reads the file back.

Approved pattern (Arquiteto/PO addendum, verified live on the Prosperfy
host): EnvironmentFile-style secret, 0600, outside git, outside logs --
/home/will/.hermes/.env, ~/.hermes/secrets/*.env, referenced by
EnvironmentFile= in systemd --user units. No general-purpose vault exists
in this environment; this broker implements the SAME convention rather
than silently promoting it to something it is not (doc 00 Sec.6.1). If a
real secret manager is later adopted, swap the provider behind
SecretBrokerPort -- callers (BrowserAdapter, capabilities) never see the
difference. HUMAN_BLOCKER=SECRET_STORE_ADAPTER stays open until then (see
Track BH report REMAINING_GAPS) -- this is a file-convention adapter, not a
real vault (no rotation, no access audit trail beyond Cognitive's own).
"""

from __future__ import annotations

import logging
import re
import secrets as _csprng
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from ..contracts.capability import SkillsAdapterPort
from ..gate.redaction import sanitize_exception

logger = logging.getLogger(__name__)

_WRITE_TOOL = "prosperfy_vps_escrever_arquivo"
_EXEC_TOOL = "prosperfy_vps_executar"
_ALIAS_RE = re.compile(r"^[a-z0-9][a-z0-9\-_]{1,63}$")
_DEFAULT_SECRETS_DIR = "~/.hermes/secrets/browser"


class SecretAliasError(ValueError):
    """Raised when an alias is not a safe filesystem-slug identifier."""


@dataclass(frozen=True)
class SecretRef:
    """Metadata-only handle returned to callers. Never carries the value."""
    alias: str
    path: str
    created_at: str


class SecretBrokerPort(Protocol):
    async def generate(
        self, alias: str, *, tenant_id: str, correlation_id: str
    ) -> SecretRef: ...

    async def reference(
        self, alias: str, *, tenant_id: str, correlation_id: str
    ) -> SecretRef | None: ...


def _validate_alias(alias: str) -> None:
    if not _ALIAS_RE.match(alias):
        raise SecretAliasError(
            f"alias invalido para SecretBroker: deve ser slug ascii minusculo "
            f"(a-z0-9-_, 2-64 chars), recebido={alias!r}"
        )


class EnvironmentFileSecretBroker:
    """
    SecretBroker sobre o padrao EnvironmentFile 0600 ja aprovado no ambiente
    (doc 00 Sec.6.1). Implementa SecretBrokerPort.

    Gera segredo via CSPRNG (`secrets.token_urlsafe`), escreve em
    '<secrets_dir>/<alias>.env' no host do Browser Worker usando o MESMO
    adapter/transporte ja auditado do prosperfy_skills
    (prosperfy_vps_escrever_arquivo + prosperfy_vps_executar p/ chmod 600),
    e devolve somente METADATA (SecretRef) -- nunca o valor. O worker
    remoto (ops/browser-worker/worker.py) e o UNICO lugar que le o valor de
    volta, no proprio host, no instante do preenchimento.
    """

    def __init__(
        self,
        adapter: SkillsAdapterPort,
        host: str,
        secrets_dir: str = _DEFAULT_SECRETS_DIR,
    ) -> None:
        self._adapter = adapter
        self._host = host
        self._secrets_dir = secrets_dir.rstrip("/")

    def _path_for(self, alias: str) -> str:
        return f"{self._secrets_dir}/{alias}.env"

    async def generate(
        self,
        alias: str,
        *,
        tenant_id: str,
        correlation_id: str,
        token_bytes: int = 24,
    ) -> SecretRef:
        """Gera + persiste um segredo CSPRNG por referencia. Nunca retorna o valor."""
        _validate_alias(alias)
        value: str | None = _csprng.token_urlsafe(token_bytes)
        path = self._path_for(alias)
        content = f"SECRET_VALUE={value}\n"
        try:
            await self._adapter.invoke_tool(
                tool_name=_WRITE_TOOL,
                arguments={
                    "host": self._host,
                    "caminho": path,
                    "conteudo": content,
                    "confirmar": True,
                },
                tenant_id=tenant_id,
                correlation_id=correlation_id,
            )
            await self._adapter.invoke_tool(
                tool_name=_EXEC_TOOL,
                arguments={
                    "host": self._host,
                    "comando": f"chmod 600 {path}",
                    "confirmar": True,
                },
                tenant_id=tenant_id,
                correlation_id=correlation_id,
            )
        except Exception as exc:
            # `from None`: nunca encadeia a excecao crua -- uma excecao de
            # transporte mal formada poderia embutir `content` num repr.
            raise RuntimeError(
                f"SecretBroker.generate falhou para alias={alias}: {sanitize_exception(exc)}"
            ) from None
        finally:
            content = "<redacted>"
            value = None  # nunca retido no processo alem do escopo de escrita

        logger.info(
            "SecretBroker.generate alias=%s host=%s tenant=%s (valor NUNCA logado)",
            alias, self._host, tenant_id,
        )
        return SecretRef(
            alias=alias,
            path=path,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    async def reference(
        self,
        alias: str,
        *,
        tenant_id: str,
        correlation_id: str,
    ) -> SecretRef | None:
        """Confere existencia por metadata (nunca le o valor)."""
        _validate_alias(alias)
        path = self._path_for(alias)
        try:
            result: Any = await self._adapter.invoke_tool(
                tool_name=_EXEC_TOOL,
                arguments={
                    "host": self._host,
                    "comando": f"test -f {path} && echo SECRET_EXISTS || echo SECRET_MISSING",
                    "confirmar": True,
                },
                tenant_id=tenant_id,
                correlation_id=correlation_id,
            )
        except Exception as exc:
            logger.warning(
                "SecretBroker.reference falhou alias=%s: %s", alias, sanitize_exception(exc)
            )
            return None
        stdout = ""
        if isinstance(result, dict):
            stdout = str(result.get("stdout") or result.get("data", {}).get("stdout", ""))
        if "SECRET_EXISTS" not in stdout:
            return None
        return SecretRef(alias=alias, path=path, created_at="")
