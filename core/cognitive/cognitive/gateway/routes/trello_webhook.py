"""
gateway/routes/trello_webhook.py — Endpoint público de webhook do Trello.

GET/HEAD /v1/integrations/trello/webhook — Trello faz HEAD (e às vezes GET)
no callbackURL ANTES de aceitar `TRELLO_ADD_WEBHOOKS`/`POST /webhooks` —
tem que responder 200 sem qualquer autenticação prévia (é o próprio Trello
provando que o endpoint existe, não um cliente autenticado).

POST /v1/integrations/trello/webhook — payload de mudança real. Validação
em profundidade (P1 spec §8, "nunca confiar em IDs de tenant enviados pelo
cliente"):
  1. Assinatura X-Trello-Webhook-Signature (HMAC-SHA1) — sem
     TRELLO_WEBHOOK_SECRET configurado, rejeita tudo (fail-closed).
  2. model.id (board_id) precisa bater com o board vinculado do tenant
     resolvido — nunca aceita idModel arbitrário.
  3. tenant_id NUNCA vem do payload — V1 é single-tenant (ver
     _resolve_tenant_id); multi-tenant real exigiria lookup admin
     board_id -> tenant (TODO, ver REMAINING_GAPS do relatório da track).

Esta rota é a ÚNICA exposta sem ActorContextDep — webhook não tem
Authorization/X-Tenant-Id/X-Actor-Id do Trello. Autenticação é a própria
assinatura HMAC.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Request, Response

logger = logging.getLogger(__name__)

router = APIRouter()

_ENV_DEV_TENANT = "COGNITIVE_DEV_TENANT_ID"


def _resolve_tenant_id() -> str:
    """V1 single-tenant: mesmo default usado em todo o resto do gateway
    (app.py dev_tenant). Multi-tenant real precisaria resolver o tenant a
    partir de model.id (board_id) via lookup admin (BYPASSRLS) — não
    implementado nesta V1 porque hoje só existe um tenant Trello-bound."""
    return os.getenv(_ENV_DEV_TENANT, "prosperfy")


@router.api_route("/v1/integrations/trello/webhook", methods=["GET", "HEAD"], include_in_schema=False)
async def trello_webhook_probe() -> Response:
    """Handshake de criação do webhook (Trello HEAD/GET) — sempre 200."""
    return Response(status_code=200)


@router.post("/v1/integrations/trello/webhook", include_in_schema=False)
async def trello_webhook_receive(request: Request) -> Response:
    raw_body = await request.body()
    signature = request.headers.get("X-Trello-Webhook-Signature", "")

    sync_engine = getattr(request.app.state, "trello_sync_engine", None)
    if sync_engine is None:
        # Trello adapter não configurado neste deploy (HUMAN_BLOCKER=TRELLO_AUTH)
        # — responde 200 pra não deixar o Trello martelando retries por algo
        # que só um operador humano resolve provisionando os secrets.
        logger.warning("trello_webhook_receive: sync_engine ausente (Trello não configurado)")
        return Response(status_code=200)

    from ...adapters.trello.sync import verify_webhook_signature

    callback_url = str(request.url)
    if not verify_webhook_signature(raw_body, callback_url, signature):
        logger.warning("trello_webhook_receive: assinatura inválida/ausente — rejeitado")
        return Response(status_code=403)

    import json

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return Response(status_code=400)

    tenant_id = _resolve_tenant_id()
    board = getattr(request.app.state, "trello_board_binding", None)
    model_id = str((payload.get("model") or {}).get("id") or "")
    if board is not None and model_id and model_id != board.board_id:
        logger.warning(
            "trello_webhook_receive: model.id=%s não bate com board vinculado do tenant — ignorado",
            model_id,
        )
        return Response(status_code=200)

    action = payload.get("action") or {}
    try:
        result = await sync_engine.process_webhook_event(tenant_id, action)
        logger.info("trello_webhook_receive tenant=%s result=%s", tenant_id, result)
    except Exception:
        logger.exception("trello_webhook_receive: process_webhook_event falhou")
        # Ainda assim 200 — um erro nosso não deve fazer o Trello desabilitar
        # o webhook por excesso de falhas; a reconciliation por polling cobre
        # o gap se esta entrega específica não convergir.

    return Response(status_code=200)
