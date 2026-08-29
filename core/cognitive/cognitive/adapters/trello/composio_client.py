"""
adapters/trello/composio_client.py — TrelloComposioAdapter (Track P1).

Transporte alternativo para o Trello: em vez de falar HTTP direto com
api.trello.com (TrelloClient), fala com o Compose MCP e deixa o Composio usar
a conexão Trello já autenticada da conta do owner.

Decisão do owner (29/08/2026): priorizar Composio para NÃO provisionar
TRELLO_API_KEY / TRELLO_TOKEN / TRELLO_WEBHOOK_SECRET.

O QUE NÃO MUDA — e é o ponto todo desta classe:
  sync.py, outbox, bindings, anti-echo e idempotência continuam exatamente
  como estão. Esta classe espelha método a método a interface pública de
  TrelloClient, então TrelloSyncEngine recebe outro objeto e não percebe
  diferença. Supabase segue Source of Truth; nenhuma regra de negócio
  migrou para o Composio.

    Supabase → outbox → TrelloSyncEngine → TrelloComposioAdapter
    → COMPOSIO_MULTI_EXECUTE_TOOL → toolkit TRELLO → Trello

Detalhes de contrato do Compose MCP aprendidos ao vivo (mesmos do
adapters/composio/client.py, ver comentários lá):
  - o endpoint expõe só meta-tools; a execução real passa por
    COMPOSIO_MULTI_EXECUTE_TOOL;
  - com várias contas do mesmo toolkit conectadas, `account` é obrigatório;
  - o envelope volta como JSON em content[0].text, com structured_content e
    data ambos None.

Webhook/inbound NÃO passa por aqui: ver TRELLO_COMPOSIO_INBOUND_GAP no
relatório da track — o Composio expõe TRELLO_CREATE_WEBHOOK (que aponta o
Trello direto para o nosso callback e é assinado com o application secret de
quem criou), não um trigger próprio assinado pelo Composio. O inbound
continua no reconcile_poll do sync.py, que não exige credencial nova.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

ENV_MCP_URL = "COMPOSIO_MCP_URL"
ENV_MCP_KEY = "COMPOSIO_MCP_API_KEY"
ENV_ACCOUNT = "TRELLO_COMPOSIO_ACCOUNT"
ENV_ORG = "TRELLO_COMPOSIO_ORG_ID"

DEFAULT_ACCOUNT = "Trello - prosperfybr@gmail.com"

_EXECUTOR = "COMPOSIO_MULTI_EXECUTE_TOOL"

_CARD_FIELDS = "name,desc,idList,due,closed,dateLastActivity"


class TrelloComposioError(RuntimeError):
    """Falha do toolkit Trello via Compose MCP. Nunca mascara sucesso."""


def is_configured() -> bool:
    return bool(os.getenv(ENV_MCP_URL, "").strip() and os.getenv(ENV_MCP_KEY, "").strip())


def _as_str(value: Any) -> str:
    """O schema do toolkit Trello no Composio tipa TUDO como string, inclusive
    booleanos ('true'/'false'). Converter aqui evita erro de validação que só
    apareceria em runtime."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class TrelloComposioAdapter:
    """Espelha a interface pública de TrelloClient, via Compose MCP.

    Qualquer método novo adicionado ao TrelloClient precisa ser adicionado
    aqui também — os dois são intercambiáveis para o TrelloSyncEngine.
    """

    def __init__(
        self,
        mcp_url: str | None = None,
        api_key: str | None = None,
        account: str | None = None,
        organization_id: str | None = None,
    ) -> None:
        self._mcp_url = mcp_url if mcp_url is not None else os.getenv(ENV_MCP_URL, "")
        self._api_key = api_key if api_key is not None else os.getenv(ENV_MCP_KEY, "")
        self._account = account or os.getenv(ENV_ACCOUNT, "") or DEFAULT_ACCOUNT
        self._organization_id = organization_id or os.getenv(ENV_ORG, "") or None

    # ─── Infra ──────────────────────────────────────────────────────────

    def is_configured(self) -> bool:
        return bool(self._mcp_url.strip() and self._api_key.strip())

    def _require_configured(self) -> None:
        if not self.is_configured():
            raise TrelloComposioError(
                f"{ENV_MCP_URL}/{ENV_MCP_KEY} não configuradas — Trello via Composio "
                "inativo (HUMAN_BLOCKER=COMPOSIO_AUTH)."
            )

    def _build_client(self):
        import fastmcp

        return fastmcp.Client(self._mcp_url, auth=self._api_key)

    async def _call(self, tool_slug: str, arguments: dict[str, Any]) -> Any:
        """Executa UMA tool do toolkit Trello e devolve `data` do envelope.

        Fail-closed em todas as camadas: transporte, protocolo MCP, e erro no
        nível do item dentro de results — um erro de toolkit chega DENTRO de
        results[0] com o envelope externo ainda parecendo bem-sucedido.
        """
        self._require_configured()
        args = {k: _as_str(v) for k, v in arguments.items() if v is not None}
        payload = {
            "tools": [
                {"tool_slug": tool_slug, "arguments": args, "account": self._account}
            ],
            "sync_response_to_workbench": False,
        }

        try:
            async with self._build_client() as client:
                result = await client.call_tool(_EXECUTOR, payload, raise_on_error=False)
        except Exception as exc:  # noqa: BLE001 — boundary externo
            logger.error(
                "TrelloComposioAdapter transport error tool=%s type=%s",
                tool_slug, type(exc).__name__,
            )
            raise TrelloComposioError(
                f"Trello tool '{tool_slug}' inacessível (erro de transporte)"
            ) from None

        if result.is_error:
            raise TrelloComposioError(
                f"Trello tool '{tool_slug}' falhou (erro de protocolo MCP)"
            )

        envelope = result.structured_content
        if envelope is None and isinstance(result.data, dict):
            envelope = result.data
        if envelope is None:
            bruto = getattr(result.content[0], "text", None) if result.content else None
            if bruto:
                try:
                    envelope = json.loads(bruto)
                except json.JSONDecodeError:
                    envelope = None
        if not isinstance(envelope, dict):
            raise TrelloComposioError(
                f"Trello tool '{tool_slug}' retornou payload em formato não reconhecido"
            )

        inner = envelope.get("data")
        if not isinstance(inner, dict) or not isinstance(inner.get("results"), list):
            raise TrelloComposioError(
                f"Trello tool '{tool_slug}': envelope sem results"
            )
        results = inner["results"]
        if not results:
            raise TrelloComposioError(f"Trello tool '{tool_slug}': results vazio")

        first = results[0] or {}
        item_error = first.get("error")
        response = first.get("response") or {}
        if item_error or response.get("successful") is False:
            detalhe = str(item_error or response.get("error") or "tool call failed")
            logger.error("TrelloComposioAdapter toolkit error tool=%s", tool_slug)
            raise TrelloComposioError(
                f"Trello tool '{tool_slug}' negado/falhou: {detalhe[:200]}"
            )
        return response.get("data", response)

    @staticmethod
    def _as_list(data: Any) -> list[dict]:
        """Extrai a lista do envelope do toolkit.

        Cada tool Trello do Composio embrulha com uma chave DIFERENTE:
        boards vem em {'details': [...]}, listas em {'lists': [...]}, cards em
        {'cards': [...]}. Verificado ao vivo — a versao anterior so conhecia
        'details' e devolvia [] silenciosamente para as listas de um board que
        tinha 8, o que faria o reconcile_poll varrer nada e nunca detectar
        drift.

        Em vez de manter uma lista de chaves conhecidas (que quebra de novo na
        proxima tool), pega a primeira chave cujo valor e uma lista.
        """
        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            return []
        for chave in ("details", "lists", "cards", "items", "result", "data"):
            valor = data.get(chave)
            if isinstance(valor, list):
                return valor
        for valor in data.values():
            if isinstance(valor, list) and all(isinstance(x, dict) for x in valor):
                return valor
        return []

    # ─── Boards / Lists ─────────────────────────────────────────────────

    async def get_member_boards(self, fields: str = "name,closed,url") -> list[dict]:
        data = await self._call(
            "TRELLO_GET_MEMBERS_BOARDS_BY_ID_MEMBER",
            {"idMember": "me", "fields": fields, "filter": "open"},
        )
        return self._as_list(data)

    async def create_board(self, name: str, desc: str = "") -> dict:
        args: dict[str, Any] = {"name": name, "desc": desc}
        if self._organization_id:
            args["idOrganization"] = self._organization_id
        data = await self._call("TRELLO_ADD_BOARDS", args)
        return data if isinstance(data, dict) else {}

    async def get_board_lists(self, board_id: str) -> list[dict]:
        data = await self._call(
            "TRELLO_GET_BOARDS_LISTS_BY_ID_BOARD",
            {"idBoard": board_id, "filter": "open", "fields": "name,closed,pos"},
        )
        return self._as_list(data)

    async def create_list(self, board_id: str, name: str, pos: str = "bottom") -> dict:
        data = await self._call(
            "TRELLO_ADD_LISTS", {"idBoard": board_id, "name": name, "pos": pos}
        )
        return data if isinstance(data, dict) else {}

    # ─── Cards ──────────────────────────────────────────────────────────

    async def create_card(
        self, list_id: str, name: str, desc: str = "", due: str | None = None
    ) -> dict:
        args: dict[str, Any] = {"idList": list_id, "name": name, "desc": desc}
        if due:
            args["due"] = due
        data = await self._call("TRELLO_ADD_CARDS", args)
        return data if isinstance(data, dict) else {}

    async def update_card(
        self,
        card_id: str,
        *,
        name: str | None = None,
        desc: str | None = None,
        idList: str | None = None,
        due: str | None = None,
        closed: bool | None = None,
    ) -> dict:
        args: dict[str, Any] = {"idCard": card_id}
        if name is not None:
            args["name"] = name
        if desc is not None:
            args["desc"] = desc
        if idList is not None:
            args["idList"] = idList
        if due is not None:
            args["due"] = due
        if closed is not None:
            args["closed"] = closed
        data = await self._call("TRELLO_UPDATE_CARDS_BY_ID_CARD", args)
        return data if isinstance(data, dict) else {}

    async def get_card(self, card_id: str, fields: str = _CARD_FIELDS) -> dict:
        data = await self._call(
            "TRELLO_GET_CARDS_BY_ID_CARD", {"idCard": card_id, "fields": fields}
        )
        return data if isinstance(data, dict) else {}

    async def get_list_cards(self, list_id: str, fields: str = _CARD_FIELDS) -> list[dict]:
        data = await self._call(
            "TRELLO_GET_LISTS_CARDS_BY_ID_LIST",
            {"idList": list_id, "fields": fields, "filter": "open"},
        )
        return self._as_list(data)

    # ─── Webhooks ───────────────────────────────────────────────────────

    async def create_webhook(
        self, callback_url: str, id_model: str, description: str = ""
    ) -> dict:
        """NÃO USAR no fluxo canônico.

        TRELLO_CREATE_WEBHOOK existe no toolkit, mas aponta o Trello
        diretamente para o nosso callback e a assinatura X-Trello-Webhook é
        feita com o application secret de QUEM criou o webhook — o Composio,
        não nós. Sem esse secret não há como validar a assinatura, e desabilitar
        a validação está fora de questão.

        Inbound canônico é reconcile_poll (sync.py), que não exige credencial
        nova. Mantido apenas para paridade de interface com TrelloClient.
        """
        raise TrelloComposioError(
            "create_webhook via Composio não é suportado: a assinatura "
            "X-Trello-Webhook usaria o application secret do Composio, que não "
            "temos para validar. Inbound usa reconcile_poll."
        )

    async def list_webhooks(self) -> list[dict]:
        """Paridade de interface. Listar webhooks exige o token do usuário, que
        justamente não provisionamos nesta configuração."""
        return []
