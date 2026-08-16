"""
audit/writer.py — AuditPort in-memory (Sprint 0.1).

Sprint 0.1: persistência em RAM (dict indexado por audit_id).
Sprint 0.2+: substituir por implementação Postgres (tabela audit_events).

Isolamento: get() filtra por tenant_id — garantia de não cross-tenant.
"""

from __future__ import annotations

import logging

from ..contracts.audit import AuditEvent, AuditPort

logger = logging.getLogger(__name__)


class InMemoryAuditWriter:
    """
    Implementa AuditPort com persistência in-memory.

    Thread-safety: adequado para uso single-process dev/test (Sprint 0.1).
    """

    def __init__(self) -> None:
        self._store: dict[str, AuditEvent] = {}

    async def record(self, event: AuditEvent) -> str:
        """Persiste o AuditEvent e retorna o audit_id."""
        self._store[event.audit_id] = event
        logger.info(
            "AUDIT tenant=%s actor=%s cap=%s decision=%s outcome=%s audit_id=%s",
            event.tenant_id,
            event.actor_id,
            event.capability_id,
            event.policy_decision,
            event.outcome.value,
            event.audit_id,
        )
        return event.audit_id

    async def get(self, audit_id: str, tenant_id: str) -> AuditEvent | None:
        """
        Recupera um AuditEvent filtrando por tenant_id.

        Retorna None se não encontrar OU se o audit_id pertencer a outro tenant
        (cross-tenant isolation em nível de aplicação — Sprint 0.1).
        """
        event = self._store.get(audit_id)
        if event is None:
            return None
        # Isolamento cross-tenant: só retorna se pertencer ao tenant solicitante
        if event.tenant_id != tenant_id:
            logger.warning(
                "Cross-tenant audit access blocked: audit_id=%s requested_by=%s owner=%s",
                audit_id, tenant_id, event.tenant_id,
            )
            return None
        return event

    def get_all_for_tenant(self, tenant_id: str) -> list[AuditEvent]:
        """Helper de teste: retorna todos os eventos de um tenant."""
        return [e for e in self._store.values() if e.tenant_id == tenant_id]

    def clear(self) -> None:
        """Limpa o store (uso em testes)."""
        self._store.clear()
