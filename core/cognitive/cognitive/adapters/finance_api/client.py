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
import re
from typing import Any
from urllib.parse import quote

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
    # --- F2B ---------------------------------------------------------
    # Segmentos {entre chaves} são path params: preenchidos a partir de
    # arguments e REMOVIDOS do corpo/query (ver _render_path).
    "finance.clarification.list": ("GET", "/api/finance/clarifications"),
    "finance.clarification.deliver": (
        "POST",
        "/api/finance/clarifications/{clarificationId}/delivery",
    ),
    "finance.clarification.resolve": (
        "POST",
        "/api/finance/clarifications/{clarificationId}/resolve",
    ),
    "finance.rule.upsert": ("POST", "/api/finance/rules"),
    "finance.statement.import": ("POST", "/api/finance/statements/import"),
    "finance.statement.reconcile": (
        "POST",
        "/api/finance/statements/{statementId}/reconcile",
    ),
    "finance.cycle.read": ("GET", "/api/finance/cycles"),
}

# Duas capabilities de F2B cobrem mais de uma rota da Finance API. A rota é
# escolhida por um argumento de MODO explícito (enum interno em inglês,
# declarado no input_schema do YAML) — nunca por heurística sobre o texto do
# usuário e nunca por decisão de LLM. `mode` é consumido aqui e não é
# repassado adiante no corpo/query.
_MODE_ROUTES: dict[str, tuple[str, str, dict[str, tuple[str, str]]]] = {
    # capability -> (nome do argumento, modo default, {modo: (método, path)})
    "finance.correction.apply": (
        "mode",
        "apply",
        {
            "apply": ("POST", "/api/finance/corrections"),
            "history": ("GET", "/api/finance/corrections/{transactionId}"),
        },
    ),
    "finance.onboarding.batch": (
        "mode",
        "",  # sem default: `mode` é required no YAML
        {
            "export": ("POST", "/api/finance/onboarding/export"),
            "import": ("POST", "/api/finance/onboarding/import"),
        },
    ),
}

_PATH_PARAM_RE = re.compile(r"\{([A-Za-z0-9_]+)\}")

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

        # Rota + payload: `mode` (quando existe) escolhe a rota e é
        # CONSUMIDO; segmentos {param} do path são preenchidos e removidos do
        # payload. O que sobra é o corpo/query enviado à Finance API.
        method, path, payload = _resolve_route(tool_name, arguments)

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
                    response = await client.get(path, params=_stringify_query(payload), headers=headers)
                else:
                    response = await client.request(method, path, json=payload, headers=headers)
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


def _render_path(path: str, arguments: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Preenche os segmentos {param} do path a partir de `arguments`.

    Devolve (path renderizado, argumentos restantes). Cada param consumido é
    REMOVIDO do dicionário devolvido: um path param nunca é repetido no corpo
    nem na querystring — o valor vive num lugar só.

    O valor é percent-encoded com safe="" (portanto "/" vira %2F): um id
    hostil como "../../admin" não consegue escapar do segmento da rota.
    `arguments` não é mutado.
    """
    names = _PATH_PARAM_RE.findall(path)
    if not names:
        return path, dict(arguments)

    remaining = dict(arguments)
    rendered = path
    for name in names:
        value = remaining.pop(name, None)
        if value is None or not str(value).strip():
            # Fail-closed: sem o id não existe rota válida. A mensagem não
            # ecoa o valor recebido (pode ser texto do usuário).
            raise RuntimeError(
                f"FinanceApiAdapter: parâmetro de rota '{name}' ausente ou vazio."
            )
        rendered = rendered.replace("{" + name + "}", quote(str(value).strip(), safe=""))
    return rendered, remaining


def _resolve_route(tool_name: str, arguments: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """capability + arguments -> (método HTTP, path final, payload).

    Duas responsabilidades, ambas determinísticas:

    1. Seleção por `mode` para as capabilities multi-rota (_MODE_ROUTES).
       `mode` é um enum interno declarado no input_schema do YAML — a escolha
       da rota nunca depende de heurística sobre o texto do usuário. O valor
       é consumido aqui e NÃO é repassado à Finance API.
    2. Renderização dos path params (_render_path), que também os remove do
       payload.
    """
    mode_spec = _MODE_ROUTES.get(tool_name)
    if mode_spec is not None:
        arg_name, default_mode, mode_routes = mode_spec
        payload = dict(arguments)
        raw_mode = payload.pop(arg_name, None)
        mode = str(raw_mode).strip() if raw_mode is not None else default_mode
        route = mode_routes.get(mode)
        if route is None:
            # Não ecoa o valor recebido no erro (pode carregar texto do
            # usuário); só o conjunto de modos válidos, que é constante.
            raise RuntimeError(
                f"FinanceApiAdapter: '{tool_name}' exige '{arg_name}' em "
                f"{sorted(mode_routes)}."
            )
    else:
        route = _ROUTES.get(tool_name)
        if route is None:
            raise RuntimeError(f"FinanceApiAdapter: capability/tool '{tool_name}' não mapeada para nenhuma rota.")
        payload = dict(arguments)

    method, path = route
    path, payload = _render_path(path, payload)
    return method, path, payload


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
