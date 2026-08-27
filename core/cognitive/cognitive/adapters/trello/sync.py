"""
adapters/trello/sync.py — Sincronização bidirecional DB <-> Trello (Track P1).

Três mecanismos, todos operando em cima de work_trello_bindings (única
tabela ciente de IDs Trello) e work_sync_outbox (fila DB->Trello):

1. `drain_outbox_once(tenant_id)` — DB -> Trello. Lê work_sync_outbox
   pendente, cria/atualiza o card correspondente, grava o binding
   (card_id/list_id/sync_state/last_synced_hash) e marca a linha done.
   Falha marca failed/dead_letter com backoff — NUNCA perde a mutation
   original (ela já está commitada em work_ideas/work_projects/work_tasks
   antes de qualquer chamada Trello).

2. `process_webhook_event(tenant_id, payload)` — Trello -> DB. Recebe o
   payload do webhook, resolve o binding pelo card_id, aplica o campo
   permitido (status via idList, título, descrição, due) no DB e emite
   WorkEvent. Anti-echo: compara o hash do estado recebido com
   binding.last_synced_hash (gravado pela última escrita NOSSA) — se
   igual, é eco da própria mutation e é ignorado sem tocar o DB.
   Dedupe de redelivery: correlation_id determinístico
   `trello_webhook:<action_id>` + WorkEventRepository.already_processed.

3. `reconcile_poll(tenant_id)` — fallback quando webhook não está
   disponível (TRELLO_WEBHOOK=BLOCKED). Varre os cards das listas
   vinculadas e aplica o mesmo caminho de `process_webhook_event` para
   qualquer card cujo hash mudou desde o último sync — sem depender de
   push do Trello.

Nenhuma função aqui decide tenant_id a partir do payload do Trello (spec
P1 §8: "nunca confiar em IDs de tenant enviados pelo cliente") — quem
chama (webhook route / poller) já resolveu o tenant_id de forma confiável
(V1: single-tenant — ver gateway/routes/trello_webhook.py).
"""

from __future__ import annotations

import hashlib
import hmac
import base64
import logging
import os
from typing import Any

from ...contracts.work import OutboxStatus, SyncState, TaskStatus, WorkEntityType, WorkEvent
from ...db.repositories.work_repo import IdeaRepository, ProjectRepository, TaskRepository, WorkEventRepository
from ...db.repositories.work_trello_repo import SyncOutboxRepository, TrelloBindingRepository
from .client import TrelloClient, TrelloNotConfiguredError

logger = logging.getLogger(__name__)

ENV_WEBHOOK_SECRET = "TRELLO_WEBHOOK_SECRET"

# Ordem = mesma do P1 spec §5.1. 'inbox'/'ideias'/'projetos' não têm status
# de Task associado (usadas por Idea/Project/captura livre).
TASK_STATUS_TO_LIST_KEY = {
    TaskStatus.TODO.value: "todo",
    TaskStatus.IN_PROGRESS.value: "in_progress",
    TaskStatus.BLOCKED.value: "blocked",
    TaskStatus.WAITING.value: "waiting",
    TaskStatus.DONE.value: "done",
}
LIST_KEY_TO_TASK_STATUS = {v: k for k, v in TASK_STATUS_TO_LIST_KEY.items()}

_BACKOFF_SECONDS_BY_ATTEMPT = (30, 120, 600, 1800, 3600)  # 30s,2m,10m,30m,1h


def _backoff_for(attempts_after: int) -> int:
    idx = min(max(attempts_after - 1, 0), len(_BACKOFF_SECONDS_BY_ATTEMPT) - 1)
    return _BACKOFF_SECONDS_BY_ATTEMPT[idx]


def content_hash(name: str, desc: str, list_id: str | None, due: str | None, closed: bool = False) -> str:
    """Hash determinístico do conteúdo do card — base do anti-echo.

    Inclui só os campos que o outbox realmente escreve (P1 spec §5.3 —
    ownership bidirecional de título/descrição/status/due); qualquer outro
    campo do card (labels, membros, anexos) não participa e não dispara
    anti-echo/loop."""
    raw = f"{name}␟{desc}␟{list_id or ''}␟{due or ''}␟{closed}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_webhook_signature(raw_body: bytes, callback_url: str, header_signature: str) -> bool:
    """Valida X-Trello-Webhook-Signature (HMAC-SHA1 base64 de body+callbackURL).

    Fail-closed: sem TRELLO_WEBHOOK_SECRET configurado, SEMPRE False — nunca
    aceita webhook não assinado (P1 spec §8: "deve validar origem/token/model").
    """
    secret = os.getenv(ENV_WEBHOOK_SECRET, "")
    if not secret or not header_signature:
        return False
    digest = hmac.new(
        secret.encode("utf-8"), raw_body + callback_url.encode("utf-8"), hashlib.sha1,
    ).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, header_signature)


def _entity_desc(entity_type: str, entity: dict[str, Any]) -> str:
    lines = [entity.get("description") or ""]
    lines.append("")
    lines.append("---")
    lines.append(f"cognitive_id: {entity['id']}")
    lines.append(f"cognitive_type: {entity_type}")
    if entity.get("status"):
        lines.append(f"status: {entity['status']}")
    if entity.get("priority"):
        lines.append(f"priority: {entity['priority']}")
    if entity.get("assignee"):
        lines.append(f"assignee: {entity['assignee']}")
    if entity.get("owner"):
        lines.append(f"owner: {entity['owner']}")
    return "\n".join(lines).strip()


class TrelloSyncEngine:
    def __init__(
        self,
        client: TrelloClient,
        idea_repo: IdeaRepository,
        project_repo: ProjectRepository,
        task_repo: TaskRepository,
        binding_repo: TrelloBindingRepository,
        outbox_repo: SyncOutboxRepository,
        event_repo: WorkEventRepository,
    ) -> None:
        self._trello = client
        self._ideas = idea_repo
        self._projects = project_repo
        self._tasks = task_repo
        self._bindings = binding_repo
        self._outbox = outbox_repo
        self._events = event_repo

    async def get_board_binding(self, tenant_id: str):
        """Exposto para o lifespan do gateway cachear o board vinculado
        (defense-in-depth na validação de model.id do webhook) sem acessar
        o repository "privado" diretamente."""
        return await self._bindings.get_board(tenant_id)

    # ─── DB -> Trello ───────────────────────────────────────────────────

    async def drain_outbox_once(self, tenant_id: str, limit: int = 25) -> dict[str, int]:
        """Processa até `limit` itens pendentes. Retorna contadores
        {"processed", "done", "failed", "skipped_not_configured"}."""
        counters = {"processed": 0, "done": 0, "failed": 0, "skipped_not_configured": 0}
        if not self._trello.is_configured():
            counters["skipped_not_configured"] = 1
            return counters

        items = await self._outbox.list_pending(tenant_id, limit=limit)
        board = await self._bindings.get_board(tenant_id)
        lists = await self._bindings.list_lists(tenant_id)
        if board is None or not lists:
            logger.warning("drain_outbox_once: board/lists não vinculados tenant=%s", tenant_id)
            return counters

        for item in items:
            counters["processed"] += 1
            await self._outbox.mark_processing(tenant_id, item.id)
            try:
                await self._sync_one_entity(tenant_id, item.entity_type, item.entity_id, board.board_id, lists)
                await self._outbox.mark_done(tenant_id, item.id)
                counters["done"] += 1
            except Exception as exc:  # noqa: BLE001 — outbox nunca deixa a exceção subir
                counters["failed"] += 1
                backoff = _backoff_for(item.attempts + 1)
                logger.warning(
                    "drain_outbox_once falhou item=%s entity=%s/%s err=%s backoff=%ss",
                    item.id, item.entity_type, item.entity_id, str(exc)[:200], backoff,
                )
                await self._outbox.mark_failed(tenant_id, item.id, str(exc)[:1900], backoff)
        return counters

    async def _sync_one_entity(
        self, tenant_id: str, entity_type: str, entity_id: str, board_id: str, lists: dict[str, Any],
    ) -> None:
        if entity_type == "idea":
            await self._sync_idea(tenant_id, entity_id, board_id, lists)
        elif entity_type == "project":
            await self._sync_project(tenant_id, entity_id, board_id, lists)
        elif entity_type == "task":
            await self._sync_task(tenant_id, entity_id, board_id, lists)
        else:
            logger.debug("_sync_one_entity: entity_type '%s' sem projeção Trello (V1 DB-only)", entity_type)

    async def _upsert_card(
        self, tenant_id: str, entity_type: str, entity_id: str, board_id: str,
        list_id: str, name: str, desc: str, due: str | None, closed: bool,
    ) -> None:
        existing = await self._bindings.get_by_entity(tenant_id, entity_type, entity_id)
        try:
            if existing and existing.card_id:
                card = await self._trello.update_card(
                    existing.card_id, name=name, desc=desc, idList=list_id, due=due, closed=closed,
                )
            else:
                card = await self._trello.create_card(list_id, name=name, desc=desc, due=due)
                if closed:
                    card = await self._trello.update_card(card["id"], closed=True)
        except TrelloNotConfiguredError:
            raise
        card_hash = content_hash(name, desc, list_id, due, closed)
        await self._bindings.upsert_entity_binding(
            tenant_id, entity_type, entity_id, board_id,
            list_id=list_id, card_id=card.get("id") or (existing.card_id if existing else None),
            sync_state=SyncState.SYNCED, last_synced_hash=card_hash,
        )

    async def _sync_idea(self, tenant_id: str, idea_id: str, board_id: str, lists: dict[str, Any]) -> None:
        idea = await self._ideas.get(tenant_id, idea_id)
        if idea is None:
            return
        list_binding = lists.get("ideias")
        if list_binding is None:
            return
        closed = idea.status.value in ("archived", "rejected", "converted")
        entity = {
            "id": idea.id, "description": idea.description, "status": idea.status.value,
        }
        await self._upsert_card(
            tenant_id, "idea", idea.id, board_id, list_binding.list_id,
            name=idea.title, desc=_entity_desc("idea", entity), due=None, closed=closed,
        )

    async def _sync_project(self, tenant_id: str, project_id: str, board_id: str, lists: dict[str, Any]) -> None:
        project = await self._projects.get(tenant_id, project_id)
        if project is None:
            return
        list_binding = lists.get("projetos")
        if list_binding is None:
            return
        closed = project.status.value in ("archived", "cancelled")
        entity = {
            "id": project.id, "description": project.description, "status": project.status.value,
            "priority": project.priority.value, "owner": project.owner,
        }
        due = project.due_date.isoformat() if project.due_date else None
        await self._upsert_card(
            tenant_id, "project", project.id, board_id, list_binding.list_id,
            name=project.title, desc=_entity_desc("project", entity), due=due, closed=closed,
        )

    async def _sync_task(self, tenant_id: str, task_id: str, board_id: str, lists: dict[str, Any]) -> None:
        task = await self._tasks.get(tenant_id, task_id)
        if task is None:
            return
        list_key = TASK_STATUS_TO_LIST_KEY.get(task.status.value)
        closed = list_key is None  # cancelled/archived -> sem lista dedicada, fecha o card
        list_binding = lists.get(list_key) if list_key else None
        if list_binding is None:
            # Sem lista mapeada (cancelled/archived) — mantém na última lista
            # conhecida (existing binding) só fechando o card.
            existing = await self._bindings.get_by_entity(tenant_id, "task", task.id)
            if existing is None or existing.list_id is None:
                return
            target_list_id = existing.list_id
        else:
            target_list_id = list_binding.list_id
        entity = {
            "id": task.id, "description": task.description, "status": task.status.value,
            "priority": task.priority.value, "assignee": task.assignee,
        }
        due = task.due_at.isoformat() if task.due_at else None
        await self._upsert_card(
            tenant_id, "task", task.id, board_id, target_list_id,
            name=task.title, desc=_entity_desc("task", entity), due=due, closed=closed,
        )

    # ─── Trello -> DB ───────────────────────────────────────────────────

    async def process_webhook_event(self, tenant_id: str, action: dict[str, Any]) -> dict[str, Any]:
        """Aplica UM `action` do payload de webhook do Trello. Retorna
        {"applied": bool, "reason": str} — nunca levanta para erros de
        negócio esperados (card sem binding, anti-echo, dedupe)."""
        action_id = str(action.get("id") or "")
        action_type = str(action.get("type") or "")
        card_data = ((action.get("data") or {}).get("card")) or {}
        card_id = str(card_data.get("id") or "")
        if not action_id or not card_id:
            return {"applied": False, "reason": "payload sem action.id/card.id"}

        correlation_id = f"trello_webhook:{action_id}"
        if await self._events.already_processed(tenant_id, correlation_id):
            return {"applied": False, "reason": "redelivery (correlation_id já processado)"}

        binding = await self._bindings.get_by_card_id(tenant_id, card_id)
        if binding is None or binding.entity_id is None:
            return {"applied": False, "reason": "card sem binding conhecido (fora do domínio Work Management)"}

        try:
            card = await self._trello.get_card(card_id)
        except Exception as exc:  # noqa: BLE001
            return {"applied": False, "reason": f"get_card falhou: {str(exc)[:200]}"}

        name = str(card.get("name") or "")
        desc = str(card.get("desc") or "")
        id_list = str(card.get("idList") or "")
        due = card.get("due")
        closed = bool(card.get("closed") or False)
        new_hash = content_hash(name, desc, id_list, due, closed)

        if binding.last_synced_hash and new_hash == binding.last_synced_hash:
            # ANTI_ECHO: este webhook reporta exatamente o estado que NÓS
            # escrevemos por último — não é uma edição humana, é o eco da
            # nossa própria escrita. Ignora sem tocar o DB.
            return {"applied": False, "reason": "anti-echo (hash idêntico à última escrita nossa)"}

        applied = await self._apply_inbound_change(
            tenant_id, binding.entity_type, binding.entity_id, id_list, name, desc, due, closed,
            actor_id="trello-webhook", correlation_id=correlation_id,
        )
        if applied:
            await self._bindings.upsert_entity_binding(
                tenant_id, binding.entity_type, binding.entity_id, binding.board_id,
                list_id=id_list, sync_state=SyncState.SYNCED, last_synced_hash=new_hash,
            )
        return {"applied": applied, "reason": "sincronizado" if applied else "sem mudança aplicável"}

    async def _apply_inbound_change(
        self, tenant_id: str, entity_type: str, entity_id: str, id_list: str,
        name: str, desc: str, due: Any, closed: bool, actor_id: str, correlation_id: str,
    ) -> bool:
        lists_by_id = {v.list_id: k for k, v in (await self._bindings.list_lists(tenant_id)).items()}
        list_key = lists_by_id.get(id_list)

        if entity_type == "task":
            task = await self._tasks.get(tenant_id, entity_id)
            if task is None:
                return False
            before = {"status": task.status.value, "title": task.title}
            new_status = LIST_KEY_TO_TASK_STATUS.get(list_key) if list_key else None
            kwargs: dict[str, Any] = {}
            if new_status and new_status != task.status.value:
                kwargs["status"] = TaskStatus(new_status)
                if new_status == "done":
                    from datetime import datetime, timezone
                    kwargs["completed_at"] = datetime.now(timezone.utc)
            title = name.strip()
            if title and title != task.title:
                kwargs["title"] = title
            if not kwargs:
                return False
            updated = await self._tasks.update(tenant_id, entity_id, **kwargs)
            if updated is None:
                return False
            await self._events.record(WorkEvent(
                tenant_id=tenant_id, entity_type=WorkEntityType.TASK, entity_id=entity_id,
                event_type="status_changed" if "status" in kwargs else "updated",
                actor_id=actor_id, correlation_id=correlation_id,
                before_state=before, after_state={"status": updated.status.value, "title": updated.title},
            ))
            return True

        if entity_type == "idea":
            idea = await self._ideas.get(tenant_id, entity_id)
            if idea is None:
                return False
            title = name.strip()
            if not title or title == idea.title:
                return False
            updated = await self._ideas.update(tenant_id, entity_id, title=title)
            if updated is None:
                return False
            await self._events.record(WorkEvent(
                tenant_id=tenant_id, entity_type=WorkEntityType.IDEA, entity_id=entity_id,
                event_type="updated", actor_id=actor_id, correlation_id=correlation_id,
                before_state={"title": idea.title}, after_state={"title": updated.title},
            ))
            return True

        if entity_type == "project":
            project = await self._projects.get(tenant_id, entity_id)
            if project is None:
                return False
            title = name.strip()
            if not title or title == project.title:
                return False
            updated = await self._projects.update(tenant_id, entity_id, title=title)
            if updated is None:
                return False
            await self._events.record(WorkEvent(
                tenant_id=tenant_id, entity_type=WorkEntityType.PROJECT, entity_id=entity_id,
                event_type="updated", actor_id=actor_id, correlation_id=correlation_id,
                before_state={"title": project.title}, after_state={"title": updated.title},
            ))
            return True

        return False

    # ─── Reconciliation por polling (fallback sem webhook) ─────────────

    async def reconcile_poll(self, tenant_id: str) -> dict[str, int]:
        """Varre todas as listas vinculadas, compara hash atual dos cards
        com o último hash conhecido e aplica drift via o mesmo caminho do
        webhook (correlation_id determinístico por poll, dedupado do mesmo
        jeito) — usado quando TRELLO_WEBHOOK=BLOCKED."""
        counters = {"scanned": 0, "applied": 0, "errors": 0}
        if not self._trello.is_configured():
            return counters
        lists = await self._bindings.list_lists(tenant_id)
        for list_key, binding in lists.items():
            if binding.list_id is None:
                continue
            try:
                cards = await self._trello.get_list_cards(binding.list_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("reconcile_poll: get_list_cards falhou list=%s err=%s", list_key, str(exc)[:200])
                counters["errors"] += 1
                continue
            for card in cards:
                counters["scanned"] += 1
                card_id = str(card.get("id") or "")
                card_binding = await self._bindings.get_by_card_id(tenant_id, card_id)
                if card_binding is None or card_binding.entity_id is None:
                    continue
                name = str(card.get("name") or "")
                desc = str(card.get("desc") or "")
                due = card.get("due")
                closed = bool(card.get("closed") or False)
                new_hash = content_hash(name, desc, binding.list_id, due, closed)
                if card_binding.last_synced_hash == new_hash:
                    continue
                pseudo_action_id = f"poll:{card_id}:{new_hash[:16]}"
                correlation_id = f"trello_webhook:{pseudo_action_id}"
                if await self._events.already_processed(tenant_id, correlation_id):
                    continue
                try:
                    applied = await self._apply_inbound_change(
                        tenant_id, card_binding.entity_type, card_binding.entity_id,
                        binding.list_id, name, desc, due, closed,
                        actor_id="trello-reconciliation", correlation_id=correlation_id,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("reconcile_poll: apply falhou card=%s err=%s", card_id, str(exc)[:200])
                    counters["errors"] += 1
                    continue
                if applied:
                    counters["applied"] += 1
                    await self._bindings.upsert_entity_binding(
                        tenant_id, card_binding.entity_type, card_binding.entity_id, card_binding.board_id,
                        list_id=binding.list_id, sync_state=SyncState.SYNCED, last_synced_hash=new_hash,
                    )
        return counters
