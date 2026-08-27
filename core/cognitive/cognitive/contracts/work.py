"""
contracts/work.py — Contratos de domínio Work Management (Track P1).

Supabase é Source of Truth (work_projects/work_ideas/work_tasks/relações).
Trello é adapter/view descartável — work_trello_bindings é a ÚNICA estrutura
ciente de IDs Trello; nenhum outro dataclass aqui referencia Trello.

Toda mutation de domínio gera um WorkEvent (actor/timestamp/correlation_id) —
mesmo espírito de AuditEvent (contracts/audit.py), mas granular por entidade
(entity_type/entity_id) em vez de por capability execution.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Protocol


# ─── Enums de estado (espelham os CHECK constraints da migration 005) ──────

class IdeaStatus(str, Enum):
    INBOX = "inbox"
    EVALUATING = "evaluating"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONVERTED = "converted"
    ARCHIVED = "archived"


class ProjectStatus(str, Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class TaskStatus(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    WAITING = "waiting"
    DONE = "done"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class SyncState(str, Enum):
    PENDING = "pending"
    SYNCED = "synced"
    CONFLICT = "conflict"
    ERROR = "error"


class OutboxStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class OutboxOperation(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    MOVE = "move"
    ARCHIVE = "archive"
    LINK = "link"
    UNLINK = "unlink"


class WorkEntityType(str, Enum):
    IDEA = "idea"
    PROJECT = "project"
    TASK = "task"
    IDEA_PROJECT = "idea_project"
    TASK_PROJECT = "task_project"
    TASK_IDEA = "task_idea"
    TASK_DEPENDENCY = "task_dependency"
    TRELLO_BINDING = "trello_binding"


def _new_id() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─── Entidades principais ──────────────────────────────────────────────────

@dataclass
class Idea:
    tenant_id: str
    title: str
    created_by: str
    id: str = field(default_factory=_new_id)
    description: str | None = None
    status: IdeaStatus = IdeaStatus.INBOX
    source: str | None = None
    impact: str | None = None                 # "low" | "medium" | "high" | None
    value_notes: str | None = None
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    archived_at: datetime | None = None


@dataclass
class Project:
    tenant_id: str
    title: str
    created_by: str
    id: str = field(default_factory=_new_id)
    description: str | None = None
    status: ProjectStatus = ProjectStatus.PLANNED
    priority: Priority = Priority.MEDIUM
    owner: str | None = None
    start_date: date | None = None
    due_date: date | None = None
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    archived_at: datetime | None = None


@dataclass
class Task:
    tenant_id: str
    title: str
    created_by: str
    id: str = field(default_factory=_new_id)
    description: str | None = None
    status: TaskStatus = TaskStatus.TODO
    priority: Priority = Priority.MEDIUM
    assignee: str | None = None
    due_at: datetime | None = None
    source: str | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    completed_at: datetime | None = None
    archived_at: datetime | None = None


@dataclass
class IdeaProjectLink:
    tenant_id: str
    idea_id: str
    project_id: str
    created_by: str
    id: str = field(default_factory=_new_id)
    relation: str = "contributes_to"
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class TaskProjectLink:
    tenant_id: str
    task_id: str
    project_id: str
    created_by: str
    id: str = field(default_factory=_new_id)
    is_primary: bool = False
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class TaskIdeaLink:
    tenant_id: str
    task_id: str
    idea_id: str
    created_by: str
    id: str = field(default_factory=_new_id)
    relation: str = "implements"
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class TaskDependency:
    tenant_id: str
    task_id: str                # tarefa bloqueada
    depends_on_task_id: str     # tarefa bloqueadora
    created_by: str
    id: str = field(default_factory=_new_id)
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class WorkEvent:
    """Histórico append-only por entidade (WorkEntityType + entity_id)."""
    tenant_id: str
    entity_type: WorkEntityType | str
    entity_id: str
    event_type: str            # 'created' | 'updated' | 'status_changed' | 'linked' | ...
    actor_id: str
    correlation_id: str
    id: str = field(default_factory=_new_id)
    before_state: dict[str, Any] = field(default_factory=dict)
    after_state: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class TrelloBinding:
    """Linha de work_trello_bindings — única estrutura ciente de IDs Trello.

    entity_type in ('board', 'list'): registro de topologia (entity_id None).
    entity_type in ('idea', 'project', 'task'): binding 1:1 entidade -> card.
    """
    tenant_id: str
    entity_type: str           # 'board' | 'list' | 'idea' | 'project' | 'task'
    board_id: str
    id: str = field(default_factory=_new_id)
    entity_id: str | None = None
    list_key: str | None = None
    list_id: str | None = None
    card_id: str | None = None
    sync_state: SyncState = SyncState.PENDING
    last_synced_at: datetime | None = None
    last_synced_hash: str | None = None
    last_error: str | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)


@dataclass
class SyncOutboxItem:
    tenant_id: str
    entity_type: str            # 'idea' | 'project' | 'task' | 'task_dependency'
    entity_id: str
    operation: OutboxOperation | str
    correlation_id: str
    id: str = field(default_factory=_new_id)
    payload: dict[str, Any] = field(default_factory=dict)
    status: OutboxStatus = OutboxStatus.PENDING
    attempts: int = 0
    max_attempts: int = 5
    last_error: str | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    next_attempt_at: datetime = field(default_factory=_utcnow)
    processed_at: datetime | None = None


# ─── Ports ──────────────────────────────────────────────────────────────────

class WorkEventWriterPort(Protocol):
    async def record(self, event: WorkEvent) -> str:
        """Persiste o WorkEvent (append-only) e retorna o id."""
        ...

    async def already_processed(self, correlation_id: str) -> bool:
        """True se já existe WorkEvent com este correlation_id (dedupe/anti-echo)."""
        ...
