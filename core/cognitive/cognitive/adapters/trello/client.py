"""
adapters/trello/client.py — TrelloClient real (REST API direta, sem Composio).

Por que REST direto e não Composio MCP: o Cognitive Gateway (processo
deployado, uvicorn) roda fora de qualquer sessão de agente — não tem acesso
ao Composio MCP (isso existe só dentro de uma conversa Claude Code/agente).
A API REST do Trello é pública e simples (key+token via query string ou
header), então é o único caminho que o RUNTIME consegue usar de forma
autônoma e contínua — e é também o mais fácil de trocar depois (spec P1
§1: "a troca Trello -> SaaS futuro deve exigir um novo adapter").

Credenciais: TRELLO_API_KEY + TRELLO_TOKEN via env (mesmo padrão de
MCP_PROSPERFYSKILLS_API_KEY — nunca hardcoded, nunca logado, nunca no DB).
Fail-closed: sem as duas, o client recusa construir (ver `is_configured`/
`require_configured`) — quem chama decide se isso vira HUMAN_BLOCKER ou
outbox pendente.

Trello REST API: https://developer.atlassian.com/cloud/trello/rest/
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ENV_API_KEY = "TRELLO_API_KEY"
ENV_TOKEN = "TRELLO_TOKEN"

_BASE_URL = "https://api.trello.com/1"
_DEFAULT_TIMEOUT = 20.0


class TrelloNotConfiguredError(RuntimeError):
    """TRELLO_API_KEY/TRELLO_TOKEN ausentes — caller deve tratar como
    HUMAN_BLOCKER=TRELLO_AUTH, nunca inventar sucesso."""


def is_configured() -> bool:
    return bool(os.getenv(ENV_API_KEY, "").strip() and os.getenv(ENV_TOKEN, "").strip())


class TrelloClient:
    """Client fino e direto para a REST API pública do Trello."""

    def __init__(
        self,
        api_key: str | None = None,
        token: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.getenv(ENV_API_KEY, "")
        self._token = token if token is not None else os.getenv(ENV_TOKEN, "")
        self._timeout = timeout

    def is_configured(self) -> bool:
        return bool(self._api_key.strip() and self._token.strip())

    def _require_configured(self) -> None:
        if not self.is_configured():
            raise TrelloNotConfiguredError(
                f"{ENV_API_KEY}/{ENV_TOKEN} não configuradas — Trello adapter inativo "
                "(HUMAN_BLOCKER=TRELLO_AUTH)."
            )

    def _auth_params(self) -> dict[str, str]:
        return {"key": self._api_key, "token": self._token}

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        self._require_configured()
        params = dict(kwargs.pop("params", None) or {})
        params.update(self._auth_params())
        url = f"{_BASE_URL}{path}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(method, url, params=params, **kwargs)
        except httpx.HTTPError as exc:
            logger.error("TrelloClient transport error path=%s type=%s", path, type(exc).__name__)
            raise RuntimeError(f"Trello inacessível ({type(exc).__name__}) — {path}") from None

        if response.status_code >= 400:
            # Nunca ecoa o corpo cru (pode conter dados de outros boards) —
            # só status + path, suficiente para diagnosticar.
            logger.error("TrelloClient http error path=%s status=%d", path, response.status_code)
            raise RuntimeError(f"Trello retornou HTTP {response.status_code} — {path}")
        if not response.content:
            return {}
        return response.json()

    # ─── Boards / Lists ─────────────────────────────────────────────────

    async def get_member_boards(self, fields: str = "name,closed,url") -> list[dict]:
        return await self._request("GET", "/members/me/boards", params={"fields": fields, "filter": "open"})

    async def create_board(self, name: str, desc: str = "") -> dict:
        return await self._request("POST", "/boards", params={"name": name, "desc": desc})

    async def get_board_lists(self, board_id: str) -> list[dict]:
        return await self._request("GET", f"/boards/{board_id}/lists", params={"filter": "open"})

    async def create_list(self, board_id: str, name: str, pos: str = "bottom") -> dict:
        return await self._request(
            "POST", "/lists", params={"idBoard": board_id, "name": name, "pos": pos},
        )

    # ─── Cards ──────────────────────────────────────────────────────────

    async def create_card(
        self, list_id: str, name: str, desc: str = "", due: str | None = None,
    ) -> dict:
        params: dict[str, Any] = {"idList": list_id, "name": name, "desc": desc}
        if due:
            params["due"] = due
        return await self._request("POST", "/cards", params=params)

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
        params: dict[str, Any] = {}
        if name is not None:
            params["name"] = name
        if desc is not None:
            params["desc"] = desc
        if idList is not None:
            params["idList"] = idList
        if due is not None:
            params["due"] = due
        if closed is not None:
            params["closed"] = "true" if closed else "false"
        return await self._request("PUT", f"/cards/{card_id}", params=params)

    async def get_card(self, card_id: str, fields: str = "name,desc,idList,due,closed,dateLastActivity") -> dict:
        return await self._request("GET", f"/cards/{card_id}", params={"fields": fields})

    async def get_list_cards(self, list_id: str, fields: str = "name,desc,idList,due,closed,dateLastActivity") -> list[dict]:
        return await self._request("GET", f"/lists/{list_id}/cards", params={"fields": fields})

    # ─── Webhooks ───────────────────────────────────────────────────────

    async def create_webhook(self, callback_url: str, id_model: str, description: str = "") -> dict:
        """Registra webhook Trello no board (idModel). Trello faz HEAD/GET no
        callbackURL antes de aceitar — a rota precisa responder 200 sem auth
        prévia (ver gateway/routes/trello_webhook.py)."""
        return await self._request(
            "POST", "/webhooks",
            params={"callbackURL": callback_url, "idModel": id_model, "description": description},
        )

    async def list_webhooks(self) -> list[dict]:
        return await self._request("GET", "/tokens/" + self._token + "/webhooks")
