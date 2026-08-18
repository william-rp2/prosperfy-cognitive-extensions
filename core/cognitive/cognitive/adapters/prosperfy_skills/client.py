"""
adapters/prosperfy_skills/client.py — ProsperfySkillsAdapter real (MCP via fastmcp.Client).

Corrige os bugs do MCPAdapter legado (hermes/.../transport/adapters/mcp_adapter.py)
e do primeiro client.py hand-rolled (Sprint 0.3 inicial), que chamava um endpoint
REST inventado (`POST /mcp/tools/call`) que nunca existiu no servidor real:
1. Fala o protocolo MCP real (Streamable HTTP) contra o único endpoint que o
   servidor ProsperfySkill (FastMCP) expõe: `{base_url}/mcp`.
2. Usa fastmcp.Client (async context manager) em vez de HTTPSConnection síncrona
   ou POST REST inventado.
3. Implementa SkillsAdapterPort corretamente (invoke_tool, health).
4. Não expõe secrets em logs.
5. Trata separadamente os dois níveis de falha do protocolo MCP:
   - Nível de protocolo: `CallToolResult.is_error` (MCP isError flag).
   - Nível de aplicação: o servidor retorna um resultado de tool bem-sucedido
     (isError=False) cujo payload estruturado é um envelope de erro da própria
     aplicação — `{"status": "error", "data": None, "error": {"code": ...}}`
     (formato de `CapabilityResult.fail(...).to_dict()` no servidor). Isso
     acontece, por exemplo, quando o token está autenticado mas não autorizado
     para a tool (PERMISSION_DENIED). Ambos os níveis são convertidos em
     exceção — nunca retornados como sucesso.
6. Fail-closed em payload desconhecido: se isError=False mas nem
   structured_content nem .data forem um dict reconhecível (achado de
   revisão adversarial — versão anterior mascarava isso como sucesso vazio
   `{"success": True, "data": {}}`), levanta exceção em vez de fabricar
   sucesso silenciosamente.

Ativado apenas quando COGNITIVE_LIVE_MCP=1.
Sprint 0.3: integração real com infra.inspect opt-in.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import fastmcp

from .guard import guard_arguments

logger = logging.getLogger(__name__)

_DEFAULT_HOST = "skills.prosperfy.com.br"
_DEFAULT_TIMEOUT = 30.0
_HEALTH_TIMEOUT = 5.0


class ProsperfySkillsAdapter:
    """
    Adapter real para ProsperfySkill MCP via fastmcp.Client (Streamable HTTP).

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
        # Real MCP endpoint do servidor (FastMCP, Streamable HTTP): sempre
        # /mcp — construído uma vez, nunca recalculado por chamada.
        self._mcp_url = f"{self._base_url}/mcp"

    def _build_client(self, timeout: float | None = None) -> fastmcp.Client:
        """
        Constrói um fastmcp.Client novo para uma sessão MCP.

        Não abre conexão nenhuma até `async with` — apenas monta o transporte.
        `auth=<str>` é resolvido pelo fastmcp como Bearer token
        (Authorization: Bearer <token>); o token nunca é logado.
        """
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
        Invoca uma tool no ProsperfySkill via MCP real (Streamable HTTP).

        Nunca loga o api_key ou valores de arguments sensíveis.
        Levanta ForbiddenArgumentError (ADR-V2-003 boundary guard) se
        `arguments` contiver chaves de comando/shell arbitrário ou um
        'resource' malformado (não resolvido para um slug lógico).

        Levanta RuntimeError (nunca retorna um dict que pareça sucesso) se:
          - a chamada falhar a nível de transporte/conexão MCP;
          - o resultado da tool tiver `isError=True` (falha a nível de
            protocolo MCP);
          - o payload estruturado da tool for o envelope de erro da própria
            aplicação, `{"status": "error", "error": {...}}` (ex.:
            PERMISSION_DENIED — token autenticado mas não autorizado para a
            tool). A mensagem da exceção inclui apenas `code`/`message` do
            erro, nunca `error.details` (pode conter dados internos).
        """
        guard_arguments(tool_name, arguments)

        if not self._api_key:
            raise RuntimeError("MCP_PROSPERFYSKILLS_API_KEY não configurada")

        logger.debug(
            "ProsperfySkillsAdapter.invoke_tool tool=%s tenant=%s correlation=%s",
            tool_name, tenant_id, correlation_id,
        )

        try:
            async with self._build_client() as client:
                result = await client.call_tool(
                    tool_name, arguments, raise_on_error=False
                )
        except Exception as exc:
            # Cobre falhas de conexão/DNS/TLS, timeout, respostas MCP
            # malformadas e erros JSON-RPC de protocolo (ex.: McpError para
            # tool desconhecida). Loga apenas o tipo/detalhe internamente;
            # nunca propaga corpo de resposta, headers ou o Bearer token
            # para o chamador.
            logger.error(
                "ProsperfySkillsAdapter transport error tool=%s type=%s "
                "tenant=%s correlation=%s",
                tool_name, type(exc).__name__, tenant_id, correlation_id,
            )
            raise RuntimeError(
                f"ProsperfySkill tool '{tool_name}' inacessível (erro de transporte)"
            ) from None

        if result.is_error:
            # Falha a nível de protocolo MCP (isError=True) — ex.: tool
            # desconhecida ou erro não capturado pelo servidor. Nunca
            # retorna isso como sucesso.
            logger.error(
                "ProsperfySkillsAdapter protocol-level tool error tool=%s "
                "tenant=%s correlation=%s",
                tool_name, tenant_id, correlation_id,
            )
            raise RuntimeError(
                f"ProsperfySkill tool '{tool_name}' falhou (erro de protocolo MCP)"
            )

        payload = result.structured_content
        if payload is None and isinstance(result.data, dict):
            payload = result.data

        if payload is None or not isinstance(payload, dict):
            # Achado da revisão adversarial (Sprint 0.3 MCP auth+transport
            # hotfix): isError=False mas nem structured_content nem .data
            # eram um dict reconhecível (ex.: None, string, lista) — versão
            # anterior tratava isso como sucesso vazio silencioso
            # (`{"success": True, "data": {}}`), mascarando uma resposta
            # genuinamente malformada/inesperada do servidor como se tivesse
            # funcionado. Nunca fail-open aqui: se o payload não bate com
            # nenhum formato reconhecido (nem envelope de erro, nem dict de
            # sucesso), é um estado desconhecido — trata como falha.
            logger.error(
                "ProsperfySkillsAdapter unrecognized payload shape tool=%s "
                "type=%s tenant=%s correlation=%s",
                tool_name, type(payload).__name__, tenant_id, correlation_id,
            )
            raise RuntimeError(
                f"ProsperfySkill tool '{tool_name}' retornou payload em formato "
                "não reconhecido (nem sucesso, nem envelope de erro esperado)"
            )

        if payload.get("status") == "error":
            # Falha a nível de aplicação: resultado MCP bem-sucedido
            # (isError=False) cujo corpo é o envelope de erro do servidor
            # (CapabilityResult.fail(...).to_dict()) — ex.: PERMISSION_DENIED
            # quando o token é autenticado mas não autorizado para a tool.
            error_info = payload.get("error")
            code = "ERROR"
            message = "tool call failed"
            if isinstance(error_info, dict):
                code = str(error_info.get("code") or code)
                message = str(error_info.get("message") or message)
            logger.error(
                "ProsperfySkillsAdapter application-level error tool=%s "
                "code=%s tenant=%s correlation=%s",
                tool_name, code, tenant_id, correlation_id,
            )
            # Nunca inclui error.details na mensagem propagada — pode
            # conter dados internos do ProsperfySkill.
            raise RuntimeError(
                f"ProsperfySkill tool '{tool_name}' negado/falhou: "
                f"[{code}] {message}"
            )

        return {"success": True, "data": payload}

    async def health(self) -> bool:
        """
        Verifica se o ProsperfySkill está acessível via protocolo MCP.

        Não existe rota HTTP simples `/health` fora do protocolo MCP
        confirmada para o servidor real — usa um ping MCP (abre sessão,
        handshake `initialize`, `ping`, fecha) como health-check leve.
        Nunca levanta exceção; qualquer falha vira `False`.
        """
        if not self._api_key:
            return False
        try:
            async with self._build_client(timeout=_HEALTH_TIMEOUT) as client:
                return await client.ping()
        except Exception:
            return False
