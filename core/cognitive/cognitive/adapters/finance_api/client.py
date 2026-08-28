"""
adapters/finance_api/client.py — FinanceApiAdapter real (HTTP contra a Finance API).

P2 (Financeiro pelo WhatsApp). A arquitetura vigente (doc 00) lista o adapter
como um dos três transportes válidos do Cognitive: "adapter (prosperfy_skills
MCP / Composio MCP / HTTP)". Este módulo é o terceiro: fala HTTP puro contra
apps/financeiro-pessoal-api (Fastify), que é o dono do SQLite financeiro —
o Cognitive nunca toca o banco diretamente, nunca replica transações.

Implementa SkillsAdapterPort (mesmo Protocol que ProsperfySkillsAdapter),
para que ExecutionOrchestrator possa invocá-lo sem qualquer mudança —
ver adapters/routing.py para como os dois adapters coexistem.

Contrato de retorno (diferente do client MCP em um ponto deliberado):
  - Sucesso HTTP (2xx)                      -> {"success": True,  "data": <json>}
  - Falha de negócio ESPERADA pelo contrato
    da capability (400/404/409 — validação,
    "not found", ambiguidade)               -> {"success": False, "error": {...}}
    Retornado normalmente (nunca levantado) porque o specialist Hermes
    precisa do corpo estruturado (ex.: a lista de candidatos ambíguos) para
    decidir a próxima pergunta ao usuário — doc 00 §7.1: "nunca escolher uma
    transação aleatória", a lista tem que chegar ao chamador.
  - Falha de transporte/config (conexão recusada, timeout, DNS, 401/403,
    5xx, ou qualquer 4xx fora do conjunto acima)
                                             -> RuntimeError (nunca retorna
    como se fosse sucesso — mesmo fail-closed do client MCP real).
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ...gate.redaction import sanitize_exception
from ..prosperfy_skills.guard import guard_arguments

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://127.0.0.1:8787"
_DEFAULT_TIMEOUT = 15.0
_HEALTH_TIMEOUT = 5.0

# capability_id (== tool_name, já que as capabilities finance.* não declaram
# `tools:` no YAML — ver execution/orchestrator.py::_run_capability_tools,
# ramo "capability simples") -> (método HTTP, path na Finance API).
_ROUTES: dict[str, tuple[str, str]] = {
    "finance.summary.read": ("GET", "/api/finance/summary"),
    "finance.transactions.read": ("GET", "/api/finance/transactions"),
    "finance.accounts.read": ("GET", "/api/finance/accounts"),
    "finance.bills.read": ("GET", "/api/finance/bills"),
    "finance.manual.create": ("POST", "/api/finance/transactions/manual"),
    "finance.category.update": ("PATCH", "/api/finance/transactions/category"),
    "finance.budget.read": ("GET", "/api/finance/budgets"),
    "finance.budget.write": ("POST", "/api/finance/budgets"),
    "finance.sync.run": ("POST", "/api/finance/sync"),
    "finance.sync.status": ("GET", "/api/finance/sync/status"),
}

# 4xx que fazem parte do contrato de negócio de pelo menos uma capability
# finance.* (validação de input, "não encontrado", ambiguidade) — devolvidos
# como {"success": False, "error": {...}}, nunca levantados como RuntimeError.
_EXPECTED_BUSINESS_STATUS = frozenset({400, 404, 409})


class FinanceApiAdapter:
    """
    Adapter real para a Finance API (Fastify) via HTTP.

    Implementa SkillsAdapterPort. Único boundary externo do Cognitive para
    apps/financeiro-pessoal-api.
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = (base_url or os.getenv("FINANCE_API_BASE_URL", _DEFAULT_BASE_URL)).rstrip("/")
        self._token = token if token is not None else os.getenv("FINANCE_API_TOKEN", "")
        self._timeout = timeout
        # Test-only seam: httpx.MockTransport lets unit tests exercise real
        # request/response handling (headers, query/body encoding, status
        # branching) without a live Finance API or the network. None in
        # production — httpx picks its normal transport.
        self._transport = transport

    async def invoke_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        tenant_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        guard_arguments(tool_name, arguments)

        route = _ROUTES.get(tool_name)
        if route is None:
            raise RuntimeError(f"FinanceApiAdapter: capability/tool '{tool_name}' não mapeada para nenhuma rota.")
        method, path = route

        if not self._token:
            raise RuntimeError("FINANCE_API_TOKEN não configurado")

        logger.debug(
            "FinanceApiAdapter.invoke_tool tool=%s method=%s tenant=%s correlation=%s",
            tool_name, method, tenant_id, correlation_id,
        )

        headers = {
            "Authorization": f"Bearer {self._token}",
            "X-Correlation-Id": correlation_id,
        }

        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout, transport=self._transport) as client:
                if method == "GET":
                    response = await client.get(path, params=_stringify_query(arguments), headers=headers)
                else:
                    response = await client.request(method, path, json=arguments, headers=headers)
        except Exception as exc:
            # Cobre connection refused/DNS/TLS/timeout. Nunca propaga a
            # exceção crua (pode conter host/porta internos) — só o tipo,
            # sanitizado.
            logger.error(
                "FinanceApiAdapter transport error tool=%s type=%s tenant=%s correlation=%s",
                tool_name, type(exc).__name__, tenant_id, correlation_id,
            )
            logger.debug("FinanceApiAdapter transport detail (sanitized) tool=%s detail=%s", tool_name, sanitize_exception(exc))
            raise RuntimeError(f"Finance API '{tool_name}' inacessível (erro de transporte)") from None

        if response.status_code in (401, 403):
            logger.error(
                "FinanceApiAdapter auth rejected tool=%s status=%s tenant=%s correlation=%s",
                tool_name, response.status_code, tenant_id, correlation_id,
            )
            raise RuntimeError(f"Finance API rejeitou a credencial de serviço (status {response.status_code}) — verifique FINANCE_API_TOKEN")

        try:
            body = response.json()
        except Exception:
            body = None

        if response.is_success:
            return {"success": True, "data": body}

        if response.status_code in _EXPECTED_BUSINESS_STATUS and isinstance(body, dict):
            # Resposta de negócio esperada (validação, not_found, ambiguidade)
            # — repassa o corpo estruturado para o specialist decidir, nunca
            # levanta. body já vem no formato {"error": "...", ...} da
            # Finance API (routes/finance.ts) — repassado como está em
            # "details" para não perder nenhum campo (ex.: "matches").
            logger.info(
                "FinanceApiAdapter business-level response tool=%s status=%s tenant=%s correlation=%s",
                tool_name, response.status_code, tenant_id, correlation_id,
            )
            return {
                "success": False,
                "error": {
                    "code": body.get("error", "business_error"),
                    "message": body.get("message", ""),
                    "http_status": response.status_code,
                    "details": body,
                },
            }

        # Qualquer outro status (5xx, ou 4xx fora do conjunto esperado) é
        # tratado como falha real — nunca retornado como se fosse sucesso.
        logger.error(
            "FinanceApiAdapter unexpected status tool=%s status=%s tenant=%s correlation=%s",
            tool_name, response.status_code, tenant_id, correlation_id,
        )
        raise RuntimeError(f"Finance API '{tool_name}' falhou com status {response.status_code}")

    async def health(self) -> bool:
        """Nunca levanta exceção; qualquer falha vira False."""
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=_HEALTH_TIMEOUT, transport=self._transport) as client:
                response = await client.get("/health")
                return response.status_code == 200
        except Exception:
            return False


def _stringify_query(arguments: dict[str, Any]) -> dict[str, str]:
    """httpx aceita valores não-string em params, mas number/bool viram '1'/'True' em vez
    do formato que a Finance API espera (querystring sempre string) — normaliza explicitamente."""
    query: dict[str, str] = {}
    for key, value in arguments.items():
        if value is None:
            continue
        if isinstance(value, bool):
            query[key] = "true" if value else "false"
        else:
            query[key] = str(value)
    return query
