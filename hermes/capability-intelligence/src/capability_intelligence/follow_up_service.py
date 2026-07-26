"""
follow_up_service.py — Serviços de Follow-Up para o Sistema Cognitivo Prosperfy.

Gerencia ciclo de vida completo: criação, verificação, conclusão e auditoria.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .follow_up import (
    CompletionEvaluatorService,
    FollowUp,
    FollowUpMetrics,
    FollowUpStatus,
    PreflightResult,
)

logger = logging.getLogger(__name__)

metrics = FollowUpMetrics()


class FollowUpRepository:
    """Interface para acesso aos follow-ups no Supabase via MCP SQL."""

    def __init__(self, execute_sql_fn=None):
        self._execute_sql = execute_sql_fn

    def set_executor(self, fn):
        self._execute_sql = fn

    def _sql(self, query: str) -> list[dict]:
        """Executa SQL e retorna resultados."""
        if not self._execute_sql:
            logger.error("FollowUpRepository: no SQL executor configured")
            return []
        try:
            result = self._execute_sql(query)
            return result
        except Exception as e:
            logger.exception("FollowUpRepository SQL error: %s", e)
            return []

    def find_open_by_entity(self, entity_id: str) -> list[dict]:
        """Busca follow-ups abertos para uma entidade."""
        rows = self._sql(
            f"SELECT * FROM follow_ups "
            f"WHERE '{entity_id}' = ANY(subject_entity_ids) "
            f"AND status IN ('pending', 'scheduled') "
            f"ORDER BY created_at DESC"
        )
        return rows or []

    def find_open_by_dedup_key(self, dedup_key: str) -> list[dict]:
        """Busca follow-ups abertos por chave de deduplicação."""
        rows = self._sql(
            f"SELECT * FROM follow_ups "
            f"WHERE deduplication_key = '{dedup_key}' "
            f"AND status IN ('pending', 'scheduled')"
        )
        return rows or []

    def mark_completed(self, follow_up_id: str, evidence: dict) -> bool:
        """Marca follow-up como concluído."""
        now = datetime.now(timezone.utc).isoformat()
        self._sql(
            f"UPDATE follow_ups SET "
            f"status = 'completed', "
            f"completed_at = '{now}', "
            f"completion_evidence = '{json.dumps(evidence)}', "
            f"updated_at = '{now}' "
            f"WHERE id = '{follow_up_id}'"
        )
        return True

    def mark_suppressed(self, follow_up_id: str, reason: str) -> bool:
        """Marca follow-up como suprimido (preflight bloqueou envio)."""
        now = datetime.now(timezone.utc).isoformat()
        self._sql(
            f"UPDATE follow_ups SET "
            f"status = 'resolved', "
            f"suppressed_reason = '{reason}', "
            f"updated_at = '{now}' "
            f"WHERE id = '{follow_up_id}'"
        )
        return True

    def create(self, follow_up: FollowUp) -> Optional[str]:
        """Cria um novo follow-up e retorna o ID."""
        now = datetime.now(timezone.utc).isoformat()
        dedup_key = follow_up.deduplication_key or ""

        # Verifica duplicação antes de criar
        if dedup_key:
            existing = self.find_open_by_dedup_key(dedup_key)
            if existing:
                metrics.duplicate_followups_prevented += 1
                logger.info("FollowUp duplicado prevenido: dedup_key=%s", dedup_key)
                return existing[0]["id"]

        subject_ids = "{" + ",".join(f'"{e}"' for e in follow_up.subject_entity_ids) + "}"
        related_ids = "{" + ",".join(f'"{e}"' for e in follow_up.related_entity_ids) + "}"
        fields = "{" + ",".join(f'"{f}"' for f in follow_up.requested_fields) + "}"

        cond = json.dumps(follow_up.completion_condition)
        meta = json.dumps(follow_up.metadata)

        rows = self._sql(
            f"INSERT INTO follow_ups "
            f"(title, description, subject_entity_ids, related_entity_ids, "
            f"requested_fields, completion_condition, completion_evaluator, "
            f"deduplication_key, status, notification_channel, metadata, created_at, updated_at) "
            f"VALUES ("
            f"'{follow_up.title}', '{follow_up.description}', "
            f"'{subject_ids}', '{related_ids}', "
            f"'{fields}', '{cond}', "
            f"'{follow_up.completion_evaluator}', "
            f"'{dedup_key}', "
            f"'pending', '{follow_up.notification_channel}', "
            f"'{meta}', '{now}', '{now}'"
            f") RETURNING id"
        )
        if rows:
            metrics.reminders_scheduled += 1
            return rows[0]["id"]
        return None


class FollowUpService:
    """Serviço de orquestração de follow-ups."""

    def __init__(self, repository: FollowUpRepository, entity_lookup_fn=None):
        self.repo = repository
        self._entity_lookup = entity_lookup_fn

    def resolve_reactively(self, entity_id: str, updated_fields: dict) -> list[dict]:
        """Resolução reativa: quando dados são atualizados, verifica follow-ups.

        Fluxo:
        ENTITY UPDATED → IDENTIFY CHANGED FIELDS → FIND OPEN FOLLOW-UPS
        → EVALUATE COMPLETION CONDITIONS → MARK COMPLETED → AUDIT
        """
        resolved = []
        open_follow_ups = self.repo.find_open_by_entity(entity_id)

        for fu in open_follow_ups:
            evaluator = fu.get("completion_evaluator", "all_fields_exist")
            condition = fu.get("completion_condition", {})
            condition["fields"] = condition.get("fields", fu.get("requested_fields", []))

            completed, evidence = CompletionEvaluatorService.evaluate(
                evaluator, condition, updated_fields
            )

            if completed:
                self.repo.mark_completed(fu["id"], evidence)
                resolved.append({
                    "follow_up_id": fu["id"],
                    "title": fu.get("title", ""),
                    "evidence": evidence,
                })
                logger.info(
                    "FollowUp '%s' concluído reativamente para entidade %s",
                    fu["id"], entity_id,
                )

        if resolved:
            metrics.reminders_cancelled += len(resolved)

        return resolved

    def preflight(self, follow_up_id: str, current_data: dict) -> PreflightResult:
        """Verificação pré-envio.

        JOB TRIGGERED → LOAD FOLLOW-UP → LOAD SOURCE OF TRUTH
        → EVALUATE CONDITION → CHECK STATUS → CHECK DUPLICATION
        → RENDER OR SUPPRESS
        """
        rows = self.repo._sql(
            f"SELECT * FROM follow_ups WHERE id = '{follow_up_id}'"
        )
        if not rows:
            return PreflightResult(can_send=False, reason="follow_up_not_found")

        fu = rows[0]
        status = fu.get("status", "")

        # Se já foi concluído/cancelado/expirado, não enviar
        if status in ("completed", "cancelled", "expired", "resolved"):
            return PreflightResult(
                can_send=False,
                reason=f"follow_up_already_{status}",
            )

        # Verificar condição de conclusão
        evaluator = fu.get("completion_evaluator", "all_fields_exist")
        condition = fu.get("completion_condition", {})
        condition["fields"] = condition.get("fields", fu.get("requested_fields", []))

        completed, evidence = CompletionEvaluatorService.evaluate(
            evaluator, condition, current_data
        )

        if completed:
            # Condição já satisfeita — suprimir e concluir
            self.repo.mark_completed(follow_up_id, evidence)
            metrics.reminders_suppressed_resolved += 1
            return PreflightResult(
                can_send=False,
                reason="already_resolved",
                evidence=evidence,
            )

        return PreflightResult(can_send=True, reason="pending")

    def build_reminder_message(self, follow_up: dict) -> dict:
        """Constrói mensagem limpa para o usuário baseada no follow-up.

        Entrada: registro do follow-up (dict do banco)
        Saída: dict para o renderer (sem metadados internos)
        """
        subject_ids = follow_up.get("subject_entity_ids", [])
        fields = follow_up.get("requested_fields", [])
        title = follow_up.get("title", "Lembrete")

        field_names = {"phone": "telefone", "email": "e-mail", "whatsapp": "WhatsApp"}

        missing = [field_names.get(f, f) for f in fields]

        return {
            "type": "follow_up_reminder",
            "subject_name": subject_ids[0] if subject_ids else "",
            "subject_entity_ids": subject_ids,
            "missing_fields": missing,
            "raw_missing": fields,
            "title": title,
            "follow_up_id": follow_up.get("id", ""),
        }