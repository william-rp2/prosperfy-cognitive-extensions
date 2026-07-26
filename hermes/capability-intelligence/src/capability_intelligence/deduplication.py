"""
deduplication.py — Idempotência, concorrência e proteção contra eco.

Garante que mensagens, tool results e respostas não sejam processados
mais de uma vez, mesmo sob concorrência ou retry.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class MessageDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    SYSTEM = "system"
    TOOL_RESULT = "tool_result"
    SCHEDULED_EVENT = "scheduled_event"


class ProcessingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


@dataclass
class MessageLock:
    """Lock por mensagem para evitar processamento duplicado."""
    message_id: str
    channel: str
    provider_message_id: str
    direction: MessageDirection
    acquired_at: float = 0.0
    ttl_seconds: int = 30
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def acquire(self) -> bool:
        self.acquired_at = time.time()
        return self._lock.acquire(blocking=False)

    def release(self):
        self._lock.release()

    def is_expired(self) -> bool:
        return time.time() > self.acquired_at + self.ttl_seconds


class DeduplicationStore:
    """Armazena IDs de mensagens processadas para deduplicação.

    Em produção: Redis ou tabela dedup no Supabase.
    Implementação atual: em memória com TTL.
    """

    def __init__(self, ttl_seconds: int = 3600):
        self._store: dict[str, float] = {}
        self._ttl = ttl_seconds
        self._lock = threading.Lock()

    def _make_key(self, channel: str, provider_msg_id: str, direction: str) -> str:
        raw = f"{channel}:{provider_msg_id}:{direction}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def is_duplicate(self, channel: str, provider_msg_id: str, direction: str) -> bool:
        """Verifica se mensagem já foi processada."""
        key = self._make_key(channel, provider_msg_id, direction)
        with self._lock:
            self._evict_expired()
            return key in self._store

    def mark_processed(self, channel: str, provider_msg_id: str, direction: str) -> bool:
        """Marca mensagem como processada. Retorna False se já existia."""
        key = self._make_key(channel, provider_msg_id, direction)
        with self._lock:
            self._evict_expired()
            if key in self._store:
                return False  # já processada
            self._store[key] = time.time()
            return True

    def _evict_expired(self):
        now = time.time()
        expired = [k for k, ts in self._store.items() if now > ts + self._ttl]
        for k in expired:
            del self._store[k]

    def clear(self):
        with self._lock:
            self._store.clear()


class ContentHashDeduplicator:
    """Deduplicação por hash de conteúdo + janela temporal."""

    def __init__(self, window_seconds: int = 5):
        self._recent: dict[str, float] = {}
        self._window = window_seconds
        self._lock = threading.Lock()

    def _hash(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def is_recent_duplicate(self, content: str) -> bool:
        """Verifica se conteúdo idêntico foi visto na janela."""
        h = self._hash(content)
        now = time.time()
        with self._lock:
            if h in self._recent and now - self._recent[h] < self._window:
                return True
            self._recent[h] = now
            return False

    def clear(self):
        with self._lock:
            self._recent.clear()


class TurnLockManager:
    """Gerencia locks por turno de conversa para evitar concorrência."""

    def __init__(self):
        self._locks: dict[str, MessageLock] = {}
        self._lock = threading.Lock()

    def acquire_turn(self, conversation_id: str, turn_id: str) -> bool:
        """Tenta adquirir lock para um turno. False se já ocupado."""
        key = f"{conversation_id}:{turn_id}"
        with self._lock:
            if key in self._locks:
                existing = self._locks[key]
                if existing.is_expired():
                    del self._locks[key]
                else:
                    # Já está sendo processado por outro worker
                    from .follow_up import metrics
                    metrics.duplicate_messages_prevented += 1
                    logger.warning("Turn %s já está sendo processado — duplicata prevenida", key)
                    return False
            lock = MessageLock(
                message_id=turn_id,
                channel=conversation_id,
                provider_message_id=turn_id,
                direction=MessageDirection.INBOUND,
            )
            if lock.acquire():
                self._locks[key] = lock
                return True
            return False

    def release_turn(self, conversation_id: str, turn_id: str):
        key = f"{conversation_id}:{turn_id}"
        with self._lock:
            if key in self._locks:
                self._locks[key].release()
                del self._locks[key]


# ─── Instância global ──────────────────────────────────────────────────

dedup_store = DeduplicationStore()
content_dedup = ContentHashDeduplicator()
turn_locks = TurnLockManager()


class DeduplicationService:
    """Serviço de deduplicação completo."""

    @staticmethod
    def check_inbound_message(
        channel: str,
        provider_message_id: str,
        content: str,
        conversation_id: str,
        turn_id: str,
    ) -> tuple[bool, str]:
        """Verifica se mensagem inbound deve ser processada.

        Returns:
            (deve_processar, motivo)
        """
        # 1. Verificar lock de turno
        if not turn_locks.acquire_turn(conversation_id, turn_id):
            return False, "turn_already_processing"

        try:
            # 2. Verificar duplicação por provider_message_id
            if dedup_store.is_duplicate(channel, provider_message_id, "inbound"):
                return False, "provider_message_id_duplicate"

            # 3. Verificar eco de mensagem outbound
            if dedup_store.is_duplicate(channel, content[:64], "outbound"):
                from .follow_up import metrics
                metrics.webhook_echo_blocked += 1
                return False, "webhook_echo_blocked"

            # 4. Verificar hash de conteúdo na janela curta
            if content_dedup.is_recent_duplicate(content):
                return False, "content_hash_duplicate_in_window"

            # Marcar como processada
            dedup_store.mark_processed(channel, provider_message_id, "inbound")
            return True, "ok"

        finally:
            turn_locks.release_turn(conversation_id, turn_id)

    @staticmethod
    def check_outbound_message(content: str, channel: str) -> str:
        """Registra mensagem outbound para prevenir eco."""
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:64]
        dedup_store.mark_processed(channel, content_hash, "outbound")
        return content_hash