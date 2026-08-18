"""
adapters/prosperfy_skills/client.py — ProsperfySkillsAdapter real (httpx async).

Corrige os bugs do MCPAdapter legado (hermes/.../transport/adapters/mcp_adapter.py):
1. Usa httpx (async) em vez de HTTPSConnection síncrona
2. Implementa SkillsAdapterPort corretamente (invoke_tool, health)
3. Não expõe secrets em logs

Ativado apenas quando COGNITIVE_LIVE_MCP=1.
Sprint 0.3: integração real com infra.inspect opt-in.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from .guard import guard_arguments

logger = logging.getLogger(__name__)

_DEFAULT_HOST = "skills.prosperfy.com.br"
_DEFAULT_TIMEOUT = 30.0


class ProsperfySkillsAdapter:
    """
    Adapter real para ProsperfySkill MCP via httpx async.

    Implementa SkillsAdapterPort.
    Único boundary externo do Cognitive para o ProsperfySkill.
    """

    def __init__(
        self,
        api_key: str | None = None,
        host: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key or os.getenv("MCP_PROSPERFYSKILLS_API_KEY", "")
        self._host = host or os.getenv("MCP_PROSPERFYSKILLS_HOST", _DEFAULT_HOST)
        self._timeout = timeout
        self._base_url = f"https://{self._host}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def invoke_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        tenant_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Invoca uma tool no ProsperfySkill via HTTP.

        Nunca loga o api_key ou valores de arguments sensíveis.
        Levanta ForbiddenArgumentError (ADR-V2-003 boundary guard) se
        `arguments` contiver chaves de comando/shell arbitrário ou um
        'resource' malformado (não resolvido para um slug lógico).
        Erros de rede/HTTP são sanitizados antes de propagar — nunca vazam
        corpo de resposta do upstream, headers ou stack interno.
        """
        guard_arguments(tool_name, arguments)

        if not self._api_key:
            raise RuntimeError("MCP_PROSPERFYSKILLS_API_KEY não configurada")

        payload = {
            "tool": tool_name,
            "arguments": arguments,
        }

        logger.debug(
            "ProsperfySkillsAdapter.invoke_tool tool=%s tenant=%s correlation=%s",
            tool_name, tenant_id, correlation_id,
        )

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._headers(),
                timeout=self._timeout,
            ) as client:
                response = await client.post("/mcp/tools/call", json=payload)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            # Loga detalhe completo apenas server-side; nunca propaga corpo/
            # headers da resposta upstream para o chamador (pode conter
            # detalhes internos do ProsperfySkill).
            logger.error(
                "ProsperfySkillsAdapter upstream error tool=%s status=%s "
                "tenant=%s correlation=%s",
                tool_name, exc.response.status_code, tenant_id, correlation_id,
            )
            raise RuntimeError(
                f"ProsperfySkill tool '{tool_name}' falhou (status "
                f"{exc.response.status_code})"
            ) from None
        except httpx.HTTPError as exc:
            logger.error(
                "ProsperfySkillsAdapter transport error tool=%s type=%s "
                "tenant=%s correlation=%s",
                tool_name, type(exc).__name__, tenant_id, correlation_id,
            )
            raise RuntimeError(
                f"ProsperfySkill tool '{tool_name}' inacessível (erro de transporte)"
            ) from None

    async def health(self) -> bool:
        """Verifica se o ProsperfySkill está acessível."""
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=5.0,
            ) as client:
                r = await client.get("/health")
                return r.status_code == 200
        except Exception:
            return False
