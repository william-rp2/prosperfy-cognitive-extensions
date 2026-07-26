"""
follow_up.py — Modelo e serviços de Follow-Up para o Sistema Cognitivo Prosperfy.

Gerencia lembretes condicionais com verificação de conclusão antes da notificação.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ─── Enums ────────────────────────────────────────────────────────────────

class FollowUpStatus(str, Enum):
    PENDING = "pending"
    SCHEDULED = "scheduled"
    RESOLVED = "resolved"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    BLOCKED = "blocked"
    FAILED = "failed"


class CompletionEvaluator(str, Enum):
    ALL_FIELDS_EXIST = "all_fields_exist"
    ANY_FIELD_EXISTS = "any_field_exists"
    FIELD_EXISTS = "field_exists"
    STATUS_EQUALS = "status_equals"
    RECORD_EXISTS = "record_exists"


# ─── Modelos ──────────────────────────────────────────────────────────────

@dataclass
class FollowUp:
    id: str = ""
    title: str = ""
    description: str = ""
    subject_entity_ids: list[str] = field(default_factory=list)
    related_entity_ids: list[str] = field(default_factory=list)
    requested_fields: list[str] = field(default_factory=list)
    source_conversation_id: str = ""
    source_message_id: str = ""
    source_turn_id: str = ""
    completion_condition: dict = field(default_factory=dict)
    completion_evaluator: str = "all_fields_exist"
    deduplication_key: str = ""
    scheduled_at: Optional[str] = None
    timezone: str = "America/Sao_Paulo"
    recurrence: str = ""
    status: str = "pending"
    job_reference: str = ""
    job_name: str = ""
    notification_channel: str = "whatsapp"
    notification_recipient: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_checked_at: Optional[str] = None
    completed_at: Optional[str] = None
    cancelled_at: Optional[str] = None
    completion_evidence: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    suppressed_reason: str = ""
    parent_follow_up_id: str = ""

    @staticmethod
    def build_deduplication_key(entity_name: str, field: str) -> str:
        """Gera chave de deduplicação: entidade:campo"""
        raw = f"{entity_name.lower().strip()}:{field.lower().strip()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ─── Completion Evaluator ────────────────────────────────────────────────

class CompletionEvaluatorService:
    """Avalia se um follow-up pode ser concluído com base nos dados atuais."""

    @staticmethod
    def evaluate(evaluator: str, condition: dict, current_data: dict) -> tuple[bool, dict]:
        """
        Avalia condição de conclusão.

        Args:
            evaluator: Nome do evaluator (all_fields_exist, field_exists, etc.)
            condition: Parâmetros da condição (ex: {"fields": ["phone", "email"]})
            current_data: Dados atuais da entidade (ex: {"phone": "+55...", "email": "..."})

        Returns:
            (concluido, evidence) — se concluído, evidence contém os dados encontrados
        """
        if evaluator == CompletionEvaluator.ALL_FIELDS_EXIST:
            fields = condition.get("fields", [])
            found = {}
            missing = []
            for f in fields:
                val = current_data.get(f)
                if val and str(val).strip():
                    found[f] = val
                else:
                    missing.append(f)
            if not missing:
                return True, {"found_fields": found, "evaluator": "all_fields_exist"}
            return False, {"missing_fields": missing}

        elif evaluator == CompletionEvaluator.ANY_FIELD_EXISTS:
            fields = condition.get("fields", [])
            found = {}
            for f in fields:
                val = current_data.get(f)
                if val and str(val).strip():
                    found[f] = val
            if found:
                return True, {"found_fields": found, "evaluator": "any_field_exists"}
            return False, {"evaluator": "any_field_exists", "message": "nenhum campo encontrado"}

        elif evaluator == CompletionEvaluator.FIELD_EXISTS:
            field = condition.get("field", "")
            val = current_data.get(field)
            if val and str(val).strip():
                return True, {"found": {field: val}, "evaluator": "field_exists"}
            return False, {"missing": [field]}

        elif evaluator == CompletionEvaluator.STATUS_EQUALS:
            expected = condition.get("status", "active")
            actual = current_data.get("status", "")
            if actual == expected:
                return True, {"status_match": actual, "evaluator": "status_equals"}
            return False, {"expected": expected, "actual": actual}

        elif evaluator == CompletionEvaluator.RECORD_EXISTS:
            record_id = current_data.get("id")
            if record_id:
                return True, {"record_id": record_id, "evaluator": "record_exists"}
            return False, {"evaluator": "record_exists", "message": "registro não encontrado"}

        return False, {"evaluator": evaluator, "error": "evaluator desconhecido"}


# ─── Preflight ───────────────────────────────────────────────────────────

class PreflightResult:
    """Resultado da verificação pré-envio de um lembrete."""

    def __init__(self, can_send: bool = False, reason: str = "", evidence: dict = None):
        self.can_send = can_send
        self.reason = reason
        self.evidence = evidence or {}

    def __bool__(self):
        return self.can_send

    def to_dict(self) -> dict:
        return {
            "can_send": self.can_send,
            "reason": self.reason,
            "evidence": self.evidence,
        }


# ─── Message Sanitizer ──────────────────────────────────────────────────

class MessageSanitizer:
    """Remove metadados internos e técnicos de mensagens destinadas ao usuário."""

    INTERNAL_PATTERNS = [
        r"(?i)Cronjob\s*Response",
        r"(?i)job_id:?\s*['\"]?[\w_-]+",
        r"\(job_id:.*?\)",
        r"\(correlation_id:.*?\)",
        r"\(trace_id:.*?\)",
        r"\[IMPORTANT:.*?\]",
        r"\[SILENT\]",
        r"DELIVERY:.*?deliver",
        r"SILENT:.*",
        r"To stop or manage this job.*",
        r"Cronjob\s*Response:.*",
        r"---*\n\n",
    ]

    RAW_TOOL_PATTERNS = [
        r"```\s*json\s*\{.*\"tool_calls\".*\}```",
        r"```\s*terminal.*?```",
        r"`[a-z_]+\s+[a-z_]+\s+--[a-z]",
    ]

    ALLOWED_CONTENT_TYPES = {
        "assistant_message",
        "reminder_message",
        "confirmation_message",
        "error_message_sanitized",
        "approval_request",
        "concise_status_update",
    }

    BLOCKED_CONTENT_TYPES = {
        "tool_call",
        "tool_result_raw",
        "scheduler_result_raw",
        "internal_event",
        "debug_message",
        "terminal_command",
        "trace",
        "system_prompt",
        "agent_scratchpad",
    }

    @classmethod
    def sanitize(cls, content: str, channel: str = "whatsapp") -> str:
        """Remove metadados internos e padrões técnicos do conteúdo."""
        import re
        result = content
        for pattern in cls.INTERNAL_PATTERNS:
            result = re.sub(pattern, "", result)
        # Remove terminal/code blocks
        result = re.sub(r'```terminal\n.*?```', '', result, flags=re.DOTALL)
        result = re.sub(r'```\w*\n.*?```', '', result, flags=re.DOTALL)
        # Clean up blank lines
        result = re.sub(r"\n{3,}", "\n\n", result)
        result = result.strip()
        return result

    @classmethod
    def contains_blocked_content(cls, content: str) -> bool:
        """Verifica se o conteúdo contém padrões bloqueados."""
        import re
        for pattern in cls.RAW_TOOL_PATTERNS:
            if re.search(pattern, content, re.DOTALL):
                return True
        for keyword in ["tool_call", "tool_result", "terminal_command", "Cronjob Response"]:
            if keyword in content:
                return True
        return False


# ─── Métricas ────────────────────────────────────────────────────────────

class FollowUpMetrics:
    """Métricas de observabilidade para follow-ups."""

    def __init__(self):
        self.reminders_scheduled = 0
        self.reminders_sent = 0
        self.reminders_suppressed_resolved = 0
        self.reminders_cancelled = 0
        self.duplicate_followups_prevented = 0
        self.stale_jobs_detected = 0
        self.context_mismatch_blocked = 0
        self.irrelevant_tools_blocked = 0
        self.orphan_tool_results_discarded = 0
        self.response_coherence_failures = 0
        self.raw_internal_messages_blocked = 0
        self.duplicate_messages_prevented = 0
        self.webhook_echo_blocked = 0
        self.reminders_failed = 0

    def snapshot(self) -> dict:
        return {k: getattr(self, k) for k in dir(self) if not k.startswith("_") and isinstance(getattr(self, k), int)}


# ─── Instância global de métricas ────────────────────────────────────────

metrics = FollowUpMetrics()