"""
adapters/composio/client.py — ComposioMcpAdapter real (MCP via fastmcp.Client).

Segundo boundary externo do Cognitive, ao lado de
adapters/prosperfy_skills/client.py — mesmo contrato (SkillsAdapterPort),
mesmo transporte (fastmcp.Client, protocolo MCP real via Streamable HTTP),
mesma disciplina de erro (isError de protocolo vs envelope de erro de
aplicação vs payload não reconhecido — todos viram exceção, nunca sucesso
fabricado) e mesma disciplina de segredo (nunca loga API key ou corpo cru).
Usado exclusivamente pelas capabilities supabase.* (P0).

Diferença de forma em relação ao ProsperfySkillsAdapter: cada conta Supabase
conectada no Composio é identificada por um alias operacional não-secreto
(`account`, ex. "Supabase - Hermes" — mesmo alias usado na coluna
supabase_projects.composio_account). Esse alias É metadado de roteamento,
não um argumento da tool em si — este adapter o remove de `arguments` antes
do guard/chamada e o repassa como campo extra do payload MCP (`account`)
para o servidor Composio resolver a conexão. NOTA HONESTA (ver relatório
final da track): o contrato exato de qual campo o servidor MCP hospedado do
Composio espera para essa seleção de conta (mesmo nome `account`? um
`connected_account_id` já resolvido?) foi provado apenas através do
meta-tool Composio usado interativamente nesta sessão (COMPOSIO_*), não
através de uma chamada MCP crua e independente de agente — a keepalive
E2E ao vivo desta track rodou por aquele caminho, não por este adapter.
Este client.py fica pronto para o mesmo contrato assim que
COMPOSIO_MCP_URL/COMPOSIO_MCP_API_KEY apontarem para o servidor MCP real do
workspace; se o campo de roteamento divergir, a falha aqui é explícita
(RuntimeError com o tool_name e o tipo do erro, nunca um sucesso fabricado).

Ativado apenas quando COGNITIVE_LIVE_COMPOSIO_MCP=1.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import fastmcp

from ...gate.redaction import (
    install_secret_scrubbing_filter,
    sanitize_exception,
    validate_credential_no_control,
)
from .guard import guard_arguments

logger = logging.getLogger(__name__)

# Meta-tool do Composio que executa as tools de toolkit. O endpoint MCP so
# expoe meta-tools; ver comentario em invoke_tool.
_COMPOSIO_EXECUTOR = "COMPOSIO_MULTI_EXECUTE_TOOL"

# Nomes internos (validados pelo guard) -> nomes que o toolkit Composio espera.
# O guard continua sendo a fronteira de seguranca e valida 'ref'; a traducao
# acontece so no transporte.
_COMPOSIO_ARG_ALIASES: dict[str, dict[str, str]] = {
    "SUPABASE_RUN_READ_ONLY_QUERY": {"ref": "project_ref"},
}

_DEFAULT_TIMEOUT = 30.0
_HEALTH_TIMEOUT = 5.0


class ComposioMcpAdapter:
    """
    Adapter real para o Compose MCP (Composio) via fastmcp.Client (Streamable HTTP).

    Implementa SkillsAdapterPort. Único boundary externo do Cognitive para o
    Composio — usado pelas capabilities supabase.*.
    """

    def __init__(
        self,
        api_key: str | None = None,
        mcp_url: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key or os.getenv("COMPOSIO_MCP_API_KEY", "")
        self._mcp_url = mcp_url or os.getenv("COMPOSIO_MCP_URL", "")
        self._timeout = timeout
        validate_credential_no_control(self._api_key, "COMPOSIO_MCP_API_KEY")
        install_secret_scrubbing_filter()

    def _build_client(self, timeout: float | None = None) -> fastmcp.Client:
        validate_credential_no_control(self._api_key, "COMPOSIO_MCP_API_KEY")
        return fastmcp.Client(
            self._mcp_url,
            auth=self._api_key,
            timeout=timeout if timeout is not None else self._timeout,
        )

    async def invoke_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        tenant_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Invoca uma tool Supabase no Compose MCP via MCP real (Streamable HTTP).

        `arguments['account']`, se presente, é retirado ANTES do guard (não é
        um argumento de tool Composio — é o alias de roteamento de conta) e
        recolocado apenas no payload final enviado ao servidor MCP. O guard
        (guard.py) valida os argumentos restantes contra a allowlist estrita
        por tool — nunca repassa tool_name/arguments arbitrários.

        Levanta RuntimeError (nunca retorna dict que pareça sucesso) nos
        mesmos três casos do ProsperfySkillsAdapter: falha de transporte,
        isError=True de protocolo MCP, ou payload de aplicação
        {"status":"error",...}. Nunca loga a api_key nem argumentos crus.
        """
        account = arguments.get("account")
        composio_args = {k: v for k, v in arguments.items() if k != "account"}
        guard_arguments(tool_name, composio_args)

        if not self._api_key or not self._mcp_url:
            raise RuntimeError(
                "COMPOSIO_MCP_API_KEY/COMPOSIO_MCP_URL não configuradas — "
                "ComposioMcpAdapter requer as duas para COGNITIVE_LIVE_COMPOSIO_MCP=1."
            )

        logger.debug(
            "ComposioMcpAdapter.invoke_tool tool=%s tenant=%s correlation=%s",
            tool_name, tenant_id, correlation_id,
        )

        # O endpoint MCP do Composio NAO expoe as tools de toolkit
        # (SUPABASE_*) como tools MCP de primeira classe. Ele expoe 7
        # meta-tools, e a execucao real passa por COMPOSIO_MULTI_EXECUTE_TOOL.
        # Chamar SUPABASE_RUN_READ_ONLY_QUERY direto devolve
        # "-32602 Tool not found" — foi exatamente o que quebrou a primeira
        # rodada headless. Verificado ao vivo com list_tools() no endpoint.
        tool_args = dict(composio_args)
        for interno, externo in _COMPOSIO_ARG_ALIASES.get(tool_name, {}).items():
            if interno in tool_args:
                tool_args[externo] = tool_args.pop(interno)

        item: dict[str, Any] = {"tool_slug": tool_name, "arguments": tool_args}
        if account:
            # Com varias contas do mesmo toolkit conectadas, o Composio exige
            # `account` para desambiguar; sem ele responde "Multiple <toolkit>
            # accounts connected".
            item["account"] = account
        payload = {"tools": [item], "sync_response_to_workbench": False}

        try:
            async with self._build_client() as client:
                result = await client.call_tool(
                    _COMPOSIO_EXECUTOR, payload, raise_on_error=False
                )
        except Exception as exc:
            logger.error(
                "ComposioMcpAdapter transport error tool=%s type=%s tenant=%s correlation=%s",
                tool_name, type(exc).__name__, tenant_id, correlation_id,
            )
            logger.debug(
                "ComposioMcpAdapter transport detail (sanitized) tool=%s detail=%s",
                tool_name, sanitize_exception(exc),
            )
            raise RuntimeError(
                f"Compose MCP tool '{tool_name}' inacessível (erro de transporte)"
            ) from None

        if result.is_error:
            logger.error(
                "ComposioMcpAdapter protocol-level tool error tool=%s tenant=%s correlation=%s",
                tool_name, tenant_id, correlation_id,
            )
            raise RuntimeError(
                f"Compose MCP tool '{tool_name}' falhou (erro de protocolo MCP)"
            )

        result_payload = result.structured_content
        if result_payload is None and isinstance(result.data, dict):
            result_payload = result.data

        if result_payload is None or not isinstance(result_payload, dict):
            logger.error(
                "ComposioMcpAdapter unrecognized payload shape tool=%s type=%s "
                "tenant=%s correlation=%s",
                tool_name, type(result_payload).__name__, tenant_id, correlation_id,
            )
            raise RuntimeError(
                f"Compose MCP tool '{tool_name}' retornou payload em formato não "
                "reconhecido (nem sucesso, nem envelope de erro esperado)"
            )

        # Desembrulha o envelope do COMPOSIO_MULTI_EXECUTE_TOOL:
        #   {"data": {"results": [{"response": {"successful": .., "data": ..},
        #                          "error": ..}]}, "successful": ..}
        # Um erro do toolkit chega DENTRO de results[0], com o envelope externo
        # ainda podendo parecer bem-sucedido — por isso a inspecao e explicita,
        # nunca "assumir sucesso se nao levantou".
        inner = result_payload.get("data")
        if isinstance(inner, dict) and isinstance(inner.get("results"), list):
            results = inner["results"]
            if not results:
                raise RuntimeError(
                    f"Compose MCP tool '{tool_name}': COMPOSIO_MULTI_EXECUTE_TOOL "
                    "retornou results vazio"
                )
            first = results[0] or {}
            item_error = first.get("error")
            response = first.get("response") or {}
            if item_error or response.get("successful") is False:
                detalhe = str(item_error or response.get("error") or "tool call failed")
                logger.error(
                    "ComposioMcpAdapter toolkit-level error tool=%s tenant=%s correlation=%s",
                    tool_name, tenant_id, correlation_id,
                )
                raise RuntimeError(
                    f"Compose MCP tool '{tool_name}' negado/falhou: {detalhe[:200]}"
                )
            return {"success": True, "data": response.get("data", response)}

        if result_payload.get("status") == "error" or result_payload.get("successful") is False:
            error_info = result_payload.get("error")
            message = str(error_info) if error_info else "tool call failed"
            logger.error(
                "ComposioMcpAdapter application-level error tool=%s tenant=%s correlation=%s",
                tool_name, tenant_id, correlation_id,
            )
            raise RuntimeError(
                f"Compose MCP tool '{tool_name}' negado/falhou: {message[:200]}"
            )

        return {"success": True, "data": result_payload}

    async def health(self) -> bool:
        """Ping MCP leve. Nunca levanta exceção; qualquer falha vira False."""
        if not self._api_key or not self._mcp_url:
            return False
        try:
            async with self._build_client(timeout=_HEALTH_TIMEOUT) as client:
                return await client.ping()
        except Exception:
            return False
