"""
db/repositories/work_trello_repo.py — TrelloBinding e SyncOutbox (Track P1).

work_trello_bindings é a ÚNICA estrutura do domínio Work Management ciente de
IDs Trello (board_id/list_id/card_id) — nenhum outro repo/contract conhece
Trello. Isso é o que torna "SAAS_ADAPTER_SWAP_READY": trocar Trello por outro
SaaS de Kanban exige só um novo adapter escrevendo nesta mesma tabela.

work_sync_outbox garante DB canonical primeiro + retry confiável: toda
mutation relevante enfileira uma linha aqui ANTES/junto da resposta ao
usuário; o TrelloAdapter drena a fila de forma assíncrona (best-effort,
nunca bloqueia o caminho principal).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from ..connection import tenant_transaction
from ..jsonb_codec import deserialize_jsonb_object, serialize_jsonb
from ...contracts.work import OutboxStatus, SyncOutboxItem, SyncState, TrelloBinding

logger = logging.getLogger(__name__)

UNSET: Any = object()


def _uid(value: str) -> uuid.UUID:
    return uuid.UUID(value)


def _row_to_binding(row) -> TrelloBinding:
    return TrelloBinding(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        entity_type=row["entity_type"],
        entity_id=str(row["entity_id"]) if row["entity_id"] else None,
        list_key=row["list_key"],
        board_id=row["board_id"],
        list_id=row["list_id"],
        card_id=row["card_id"],
        sync_state=SyncState(row["sync_state"]),
        last_synced_at=row["last_synced_at"],
        last_synced_hash=row["last_synced_hash"],
        last_error=row["last_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_outbox(row) -> SyncOutboxItem:
    return SyncOutboxItem(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        entity_type=row["entity_type"],
        entity_id=str(row["entity_id"]),
        operation=row["operation"],
        payload=deserialize_jsonb_object(row["payload"]),
        status=OutboxStatus(row["status"]),
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
        last_error=row["last_error"],
        correlation_id=row["correlation_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        next_attempt_at=row["next_attempt_at"],
        processed_at=row["processed_at"],
    )


class TrelloBindingRepository:
    """CRUD de work_trello_bindings — board/list (topologia) + entidade→card."""

    async def upsert_board(self, tenant_id: str, board_id: str) -> TrelloBinding:
        async with tenant_transaction(tenant_id) as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO work_trello_bindings(tenant_id, entity_type, board_id, sync_state)
                VALUES($1, 'board', $2, 'synced')
                ON CONFLICT (tenant_id) WHERE entity_type = 'board'
                DO UPDATE SET board_id = EXCLUDED.board_id, updated_at = NOW()
                RETURNING *
                """,
                _uid(tenant_id), board_id,
            )
        return _row_to_binding(row)

    async def upsert_list(
        self, tenant_id: str, board_id: str, list_key: str, list_id: str,
    ) -> TrelloBinding:
        async with tenant_transaction(tenant_id) as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO work_trello_bindings(tenant_id, entity_type, board_id, list_key, list_id, sync_state)
                VALUES($1, 'list', $2, $3, $4, 'synced')
                ON CONFLICT (tenant_id, list_key) WHERE entity_type = 'list'
                DO UPDATE SET list_id = EXCLUDED.list_id, board_id = EXCLUDED.board_id, updated_at = NOW()
                RETURNING *
                """,
                _uid(tenant_id), board_id, list_key, list_id,
            )
        return _row_to_binding(row)

    async def get_board(self, tenant_id: str) -> TrelloBinding | None:
        async with tenant_transaction(tenant_id) as conn:
            row = await conn.fetchrow(
                "SELECT * FROM work_trello_bindings WHERE entity_type = 'board'",
            )
        return _row_to_binding(row) if row else None

    async def list_lists(self, tenant_id: str) -> dict[str, TrelloBinding]:
        async with tenant_transaction(tenant_id) as conn:
            rows = await conn.fetch(
                "SELECT * FROM work_trello_bindings WHERE entity_type = 'list'",
            )
        return {r["list_key"]: _row_to_binding(r) for r in rows}

    async def upsert_entity_binding(
        self,
        tenant_id: str,
        entity_type: str,
        entity_id: str,
        board_id: str,
        *,
        list_id: str | None = None,
        card_id: str | None = None,
        sync_state: SyncState | str = SyncState.PENDING,
        last_synced_hash: str | None = None,
        last_error: str | None = None,
    ) -> TrelloBinding:
        state = sync_state.value if isinstance(sync_state, SyncState) else sync_state
        async with tenant_transaction(tenant_id) as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO work_trello_bindings(
                    tenant_id, entity_type, entity_id, board_id, list_id, card_id,
                    sync_state, last_synced_at, last_synced_hash, last_error
                ) VALUES($1,$2,$3,$4,$5,$6,$7,
                    CASE WHEN $7 = 'synced' THEN NOW() ELSE NULL END, $8, $9)
                ON CONFLICT (tenant_id, entity_type, entity_id) WHERE entity_id IS NOT NULL
                DO UPDATE SET
                    list_id = EXCLUDED.list_id,
                    card_id = COALESCE(EXCLUDED.card_id, work_trello_bindings.card_id),
                    sync_state = EXCLUDED.sync_state,
                    last_synced_at = CASE WHEN EXCLUDED.sync_state = 'synced' THEN NOW()
                                          ELSE work_trello_bindings.last_synced_at END,
                    last_synced_hash = COALESCE(EXCLUDED.last_synced_hash, work_trello_bindings.last_synced_hash),
                    last_error = EXCLUDED.last_error,
                    updated_at = NOW()
                RETURNING *
                """,
                _uid(tenant_id), entity_type, _uid(entity_id), board_id, list_id, card_id,
                state, last_synced_hash, last_error,
            )
        return _row_to_binding(row)

    async def get_by_entity(
        self, tenant_id: str, entity_type: str, entity_id: str,
    ) -> TrelloBinding | None:
        async with tenant_transaction(tenant_id) as conn:
            row = await conn.fetchrow(
                "SELECT * FROM work_trello_bindings WHERE entity_type = $1 AND entity_id = $2",
                entity_type, _uid(entity_id),
            )
        return _row_to_binding(row) if row else None

    async def get_by_card_id(self, tenant_id: str, card_id: str) -> TrelloBinding | None:
        """Lookup reverso: webhook chega com card_id, precisamos da entidade."""
        async with tenant_transaction(tenant_id) as conn:
            row = await conn.fetchrow(
                "SELECT * FROM work_trello_bindings WHERE card_id = $1", card_id,
            )
        return _row_to_binding(row) if row else None


class SyncOutboxRepository:
    """Fila de retry DB → Trello. cognitive_worker drena via poll periódico."""

    async def enqueue(
        self,
        tenant_id: str,
        entity_type: str,
        entity_id: str,
        operation: str,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> SyncOutboxItem:
        async with tenant_transaction(tenant_id) as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO work_sync_outbox(
                    tenant_id, entity_type, entity_id, operation, payload, correlation_id
                ) VALUES($1,$2,$3,$4,$5::jsonb,$6)
                RETURNING *
                """,
                _uid(tenant_id), entity_type, _uid(entity_id), operation,
                serialize_jsonb(payload), correlation_id,
            )
        logger.info(
            "OUTBOX enqueue tenant=%s entity=%s/%s op=%s correlation=%s",
            tenant_id, entity_type, entity_id, operation, correlation_id,
        )
        return _row_to_outbox(row)

    async def list_pending(self, tenant_id: str, limit: int = 25) -> list[SyncOutboxItem]:
        async with tenant_transaction(tenant_id) as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM work_sync_outbox
                WHERE status IN ('pending','failed') AND next_attempt_at <= NOW()
                ORDER BY created_at ASC LIMIT $1
                """,
                limit,
            )
        return [_row_to_outbox(r) for r in rows]

    async def mark_processing(self, tenant_id: str, outbox_id: str) -> None:
        async with tenant_transaction(tenant_id) as conn:
            await conn.execute(
                "UPDATE work_sync_outbox SET status = 'processing', updated_at = NOW() WHERE id = $1",
                _uid(outbox_id),
            )

    async def mark_done(self, tenant_id: str, outbox_id: str) -> None:
        async with tenant_transaction(tenant_id) as conn:
            await conn.execute(
                """
                UPDATE work_sync_outbox
                SET status = 'done', processed_at = NOW(), updated_at = NOW()
                WHERE id = $1
                """,
                _uid(outbox_id),
            )

    async def mark_failed(
        self, tenant_id: str, outbox_id: str, error: str, backoff_seconds: int,
    ) -> None:
        """Incrementa attempts; vira dead_letter se estourar max_attempts."""
        async with tenant_transaction(tenant_id) as conn:
            await conn.execute(
                """
                UPDATE work_sync_outbox SET
                    attempts = attempts + 1,
                    last_error = $2,
                    status = CASE WHEN attempts + 1 >= max_attempts THEN 'dead_letter' ELSE 'failed' END,
                    next_attempt_at = NOW() + ($3 || ' seconds')::interval,
                    updated_at = NOW()
                WHERE id = $1
                """,
                _uid(outbox_id), error[:2000], str(backoff_seconds),
            )

    async def status_summary(self, tenant_id: str) -> dict[str, int]:
        async with tenant_transaction(tenant_id) as conn:
            rows = await conn.fetch(
                "SELECT status, count(*) AS n FROM work_sync_outbox GROUP BY status",
            )
        return {r["status"]: r["n"] for r in rows}
