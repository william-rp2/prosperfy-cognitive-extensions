"""
db/repositories/work_repo.py — Repositórios de Idea, Project, Task, relações
many-to-many, dependências e WorkEvent (Track P1 — Work Management).

RLS enforced via tenant_transaction em toda operação (ADR-V2-002) — mesmo
padrão de audit_repo.py/tenancy_repo.py. Nenhum método aqui conhece Trello;
ver work_trello_repo.py para bindings/outbox (única camada ciente de IDs
Trello, ADR local do Track P1).

Hard delete NÃO existe aqui de propósito — arquivar preserva histórico
(archive_* seta status='archived' + archived_at). Delete físico é fora de
escopo V1 (capability administrativa separada, não implementada).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from ..connection import tenant_transaction
from ..jsonb_codec import deserialize_jsonb_object, serialize_jsonb
from ...contracts.work import (
    Idea,
    IdeaProjectLink,
    IdeaStatus,
    Priority,
    Project,
    ProjectStatus,
    Task,
    TaskDependency,
    TaskIdeaLink,
    TaskProjectLink,
    TaskStatus,
    WorkEvent,
)

logger = logging.getLogger(__name__)

# Sentinel: distingue "campo não informado" (não mexe na coluna) de
# "campo explicitamente setado para None" (SET col = NULL) nos updates
# parciais abaixo. Nenhum valor real de aplicação é `UNSET`.
UNSET: Any = object()

_ACTIVE_TASK_STATUSES = ("todo", "in_progress", "blocked", "waiting")


def _uid(value: str) -> uuid.UUID:
    return uuid.UUID(value)


# ─── row → dataclass ────────────────────────────────────────────────────────

def _row_to_idea(row) -> Idea:
    return Idea(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        title=row["title"],
        description=row["description"],
        status=IdeaStatus(row["status"]),
        source=row["source"],
        impact=row["impact"],
        value_notes=row["value_notes"],
        tags=list(row["tags"] or []),
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        archived_at=row["archived_at"],
    )


def _row_to_project(row) -> Project:
    return Project(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        title=row["title"],
        description=row["description"],
        status=ProjectStatus(row["status"]),
        priority=Priority(row["priority"]),
        owner=row["owner"],
        start_date=row["start_date"],
        due_date=row["due_date"],
        tags=list(row["tags"] or []),
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        archived_at=row["archived_at"],
    )


def _row_to_task(row) -> Task:
    return Task(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        title=row["title"],
        description=row["description"],
        status=TaskStatus(row["status"]),
        priority=Priority(row["priority"]),
        assignee=row["assignee"],
        due_at=row["due_at"],
        source=row["source"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
        archived_at=row["archived_at"],
    )


def _row_to_work_event(row) -> WorkEvent:
    return WorkEvent(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        entity_type=row["entity_type"],
        entity_id=str(row["entity_id"]),
        event_type=row["event_type"],
        before_state=deserialize_jsonb_object(row["before_state"]),
        after_state=deserialize_jsonb_object(row["after_state"]),
        actor_id=row["actor_id"],
        correlation_id=row["correlation_id"],
        created_at=row["created_at"],
    )


def _build_set_clause(fields: dict[str, Any], start_index: int) -> tuple[str, list[Any]]:
    """Monta 'col1 = $N, col2 = $N+1, ...' só para campos != UNSET.

    Nomes de coluna vêm sempre de um dict literal montado pelo repo (nunca de
    input externo) — seguro contra SQL injection por construção.
    """
    set_parts: list[str] = []
    args: list[Any] = []
    idx = start_index
    for col, value in fields.items():
        if value is UNSET:
            continue
        set_parts.append(f"{col} = ${idx}")
        args.append(value)
        idx += 1
    return ", ".join(set_parts), args


# ─── IdeaRepository ─────────────────────────────────────────────────────────

class IdeaRepository:
    async def create(self, idea: Idea) -> Idea:
        async with tenant_transaction(idea.tenant_id) as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO work_ideas(
                    id, tenant_id, title, description, status, source, impact,
                    value_notes, tags, created_by, created_at, updated_at
                ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                RETURNING *
                """,
                _uid(idea.id), _uid(idea.tenant_id), idea.title, idea.description,
                idea.status.value, idea.source, idea.impact, idea.value_notes,
                idea.tags, idea.created_by, idea.created_at, idea.updated_at,
            )
        return _row_to_idea(row)

    async def get(self, tenant_id: str, idea_id: str) -> Idea | None:
        async with tenant_transaction(tenant_id) as conn:
            row = await conn.fetchrow(
                "SELECT * FROM work_ideas WHERE id = $1", _uid(idea_id),
            )
        return _row_to_idea(row) if row else None

    async def list(
        self,
        tenant_id: str,
        *,
        status: str | None = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Idea]:
        clauses = ["1=1"]
        args: list[Any] = []
        if status:
            args.append(status)
            clauses.append(f"status = ${len(args)}")
        elif not include_archived:
            clauses.append("status <> 'archived'")
        args.append(limit)
        limit_idx = len(args)
        args.append(offset)
        offset_idx = len(args)
        query = (
            f"SELECT * FROM work_ideas WHERE {' AND '.join(clauses)} "
            f"ORDER BY updated_at DESC LIMIT ${limit_idx} OFFSET ${offset_idx}"
        )
        async with tenant_transaction(tenant_id) as conn:
            rows = await conn.fetch(query, *args)
        return [_row_to_idea(r) for r in rows]

    async def update(
        self,
        tenant_id: str,
        idea_id: str,
        *,
        title: Any = UNSET,
        description: Any = UNSET,
        status: Any = UNSET,
        source: Any = UNSET,
        impact: Any = UNSET,
        value_notes: Any = UNSET,
        tags: Any = UNSET,
        archived_at: Any = UNSET,
    ) -> Idea | None:
        fields: dict[str, Any] = {
            "title": title, "description": description,
            "status": status.value if isinstance(status, IdeaStatus) else status,
            "source": source, "impact": impact, "value_notes": value_notes,
            "tags": tags, "archived_at": archived_at,
        }
        set_clause, args = _build_set_clause(fields, start_index=1)
        if not set_clause:
            return await self.get(tenant_id, idea_id)
        set_clause += ", updated_at = NOW()"
        args.append(_uid(idea_id))
        query = f"UPDATE work_ideas SET {set_clause} WHERE id = ${len(args)} RETURNING *"
        async with tenant_transaction(tenant_id) as conn:
            row = await conn.fetchrow(query, *args)
        return _row_to_idea(row) if row else None

    async def archive(self, tenant_id: str, idea_id: str) -> Idea | None:
        return await self.update(
            tenant_id, idea_id, status=IdeaStatus.ARCHIVED,
            archived_at=datetime.now(timezone.utc),
        )


# ─── ProjectRepository ──────────────────────────────────────────────────────

class ProjectRepository:
    async def create(self, project: Project) -> Project:
        async with tenant_transaction(project.tenant_id) as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO work_projects(
                    id, tenant_id, title, description, status, priority, owner,
                    start_date, due_date, tags, created_by, created_at, updated_at
                ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                RETURNING *
                """,
                _uid(project.id), _uid(project.tenant_id), project.title,
                project.description, project.status.value, project.priority.value,
                project.owner, project.start_date, project.due_date, project.tags,
                project.created_by, project.created_at, project.updated_at,
            )
        return _row_to_project(row)

    async def get(self, tenant_id: str, project_id: str) -> Project | None:
        async with tenant_transaction(tenant_id) as conn:
            row = await conn.fetchrow(
                "SELECT * FROM work_projects WHERE id = $1", _uid(project_id),
            )
        return _row_to_project(row) if row else None

    async def list(
        self,
        tenant_id: str,
        *,
        status: str | None = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Project]:
        clauses = ["1=1"]
        args: list[Any] = []
        if status:
            args.append(status)
            clauses.append(f"status = ${len(args)}")
        elif not include_archived:
            clauses.append("status <> 'archived'")
        args.append(limit)
        limit_idx = len(args)
        args.append(offset)
        offset_idx = len(args)
        query = (
            f"SELECT * FROM work_projects WHERE {' AND '.join(clauses)} "
            f"ORDER BY updated_at DESC LIMIT ${limit_idx} OFFSET ${offset_idx}"
        )
        async with tenant_transaction(tenant_id) as conn:
            rows = await conn.fetch(query, *args)
        return [_row_to_project(r) for r in rows]

    async def update(
        self,
        tenant_id: str,
        project_id: str,
        *,
        title: Any = UNSET,
        description: Any = UNSET,
        status: Any = UNSET,
        priority: Any = UNSET,
        owner: Any = UNSET,
        start_date: Any = UNSET,
        due_date: Any = UNSET,
        tags: Any = UNSET,
        archived_at: Any = UNSET,
    ) -> Project | None:
        fields: dict[str, Any] = {
            "title": title, "description": description,
            "status": status.value if isinstance(status, ProjectStatus) else status,
            "priority": priority.value if isinstance(priority, Priority) else priority,
            "owner": owner, "start_date": start_date, "due_date": due_date,
            "tags": tags, "archived_at": archived_at,
        }
        set_clause, args = _build_set_clause(fields, start_index=1)
        if not set_clause:
            return await self.get(tenant_id, project_id)
        set_clause += ", updated_at = NOW()"
        args.append(_uid(project_id))
        query = f"UPDATE work_projects SET {set_clause} WHERE id = ${len(args)} RETURNING *"
        async with tenant_transaction(tenant_id) as conn:
            row = await conn.fetchrow(query, *args)
        return _row_to_project(row) if row else None

    async def archive(self, tenant_id: str, project_id: str) -> Project | None:
        return await self.update(
            tenant_id, project_id, status=ProjectStatus.ARCHIVED,
            archived_at=datetime.now(timezone.utc),
        )


# ─── TaskRepository ─────────────────────────────────────────────────────────

class TaskRepository:
    async def create(self, task: Task) -> Task:
        async with tenant_transaction(task.tenant_id) as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO work_tasks(
                    id, tenant_id, title, description, status, priority, assignee,
                    due_at, source, created_by, created_at, updated_at
                ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                RETURNING *
                """,
                _uid(task.id), _uid(task.tenant_id), task.title, task.description,
                task.status.value, task.priority.value, task.assignee, task.due_at,
                task.source, task.created_by, task.created_at, task.updated_at,
            )
        return _row_to_task(row)

    async def get(self, tenant_id: str, task_id: str) -> Task | None:
        async with tenant_transaction(tenant_id) as conn:
            row = await conn.fetchrow(
                "SELECT * FROM work_tasks WHERE id = $1", _uid(task_id),
            )
        return _row_to_task(row) if row else None

    async def list(
        self,
        tenant_id: str,
        *,
        status: str | None = None,
        assignee: str | None = None,
        project_id: str | None = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Task]:
        clauses = ["t.tenant_id = t.tenant_id"]  # placeholder, RLS já filtra tenant
        joins = ""
        args: list[Any] = []
        if project_id:
            joins = "JOIN work_task_projects tp ON tp.task_id = t.id"
            args.append(_uid(project_id))
            clauses.append(f"tp.project_id = ${len(args)}")
        if status:
            args.append(status)
            clauses.append(f"t.status = ${len(args)}")
        elif not include_archived:
            clauses.append("t.status <> 'archived'")
        if assignee:
            args.append(assignee)
            clauses.append(f"t.assignee = ${len(args)}")
        args.append(limit)
        limit_idx = len(args)
        args.append(offset)
        offset_idx = len(args)
        query = (
            f"SELECT DISTINCT t.* FROM work_tasks t {joins} "
            f"WHERE {' AND '.join(clauses)} "
            f"ORDER BY t.updated_at DESC LIMIT ${limit_idx} OFFSET ${offset_idx}"
        )
        async with tenant_transaction(tenant_id) as conn:
            rows = await conn.fetch(query, *args)
        return [_row_to_task(r) for r in rows]

    async def list_blocked(self, tenant_id: str, limit: int = 50) -> list[Task]:
        """Tarefas com status='blocked' OU com dependência ainda não concluída."""
        query = """
            SELECT DISTINCT t.* FROM work_tasks t
            WHERE t.status = 'blocked'
               OR EXISTS (
                    SELECT 1 FROM work_task_dependencies d
                    JOIN work_tasks dep ON dep.id = d.depends_on_task_id
                    WHERE d.task_id = t.id
                      AND dep.status NOT IN ('done','cancelled','archived')
               )
            ORDER BY t.updated_at DESC
            LIMIT $1
        """
        async with tenant_transaction(tenant_id) as conn:
            rows = await conn.fetch(query, limit)
        return [_row_to_task(r) for r in rows]

    async def update(
        self,
        tenant_id: str,
        task_id: str,
        *,
        title: Any = UNSET,
        description: Any = UNSET,
        status: Any = UNSET,
        priority: Any = UNSET,
        assignee: Any = UNSET,
        due_at: Any = UNSET,
        source: Any = UNSET,
        completed_at: Any = UNSET,
        archived_at: Any = UNSET,
    ) -> Task | None:
        fields: dict[str, Any] = {
            "title": title, "description": description,
            "status": status.value if isinstance(status, TaskStatus) else status,
            "priority": priority.value if isinstance(priority, Priority) else priority,
            "assignee": assignee, "due_at": due_at, "source": source,
            "completed_at": completed_at, "archived_at": archived_at,
        }
        set_clause, args = _build_set_clause(fields, start_index=1)
        if not set_clause:
            return await self.get(tenant_id, task_id)
        set_clause += ", updated_at = NOW()"
        args.append(_uid(task_id))
        query = f"UPDATE work_tasks SET {set_clause} WHERE id = ${len(args)} RETURNING *"
        async with tenant_transaction(tenant_id) as conn:
            row = await conn.fetchrow(query, *args)
        return _row_to_task(row) if row else None

    async def archive(self, tenant_id: str, task_id: str) -> Task | None:
        return await self.update(
            tenant_id, task_id, status=TaskStatus.ARCHIVED,
            archived_at=datetime.now(timezone.utc),
        )


# ─── WorkLinkRepository (M2M + dependências) ───────────────────────────────

class WorkLinkRepository:
    async def link_idea_project(
        self, tenant_id: str, idea_id: str, project_id: str, created_by: str,
        relation: str = "contributes_to",
    ) -> IdeaProjectLink:
        async with tenant_transaction(tenant_id) as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO work_idea_projects(tenant_id, idea_id, project_id, relation, created_by)
                VALUES($1,$2,$3,$4,$5)
                ON CONFLICT (idea_id, project_id) DO UPDATE SET relation = EXCLUDED.relation
                RETURNING *
                """,
                _uid(tenant_id), _uid(idea_id), _uid(project_id), relation, created_by,
            )
        return IdeaProjectLink(
            id=str(row["id"]), tenant_id=str(row["tenant_id"]),
            idea_id=str(row["idea_id"]), project_id=str(row["project_id"]),
            relation=row["relation"], created_by=row["created_by"], created_at=row["created_at"],
        )

    async def link_task_project(
        self, tenant_id: str, task_id: str, project_id: str, created_by: str,
        is_primary: bool = False,
    ) -> TaskProjectLink:
        async with tenant_transaction(tenant_id) as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO work_task_projects(tenant_id, task_id, project_id, is_primary, created_by)
                VALUES($1,$2,$3,$4,$5)
                ON CONFLICT (task_id, project_id) DO UPDATE SET is_primary = EXCLUDED.is_primary
                RETURNING *
                """,
                _uid(tenant_id), _uid(task_id), _uid(project_id), is_primary, created_by,
            )
        return TaskProjectLink(
            id=str(row["id"]), tenant_id=str(row["tenant_id"]),
            task_id=str(row["task_id"]), project_id=str(row["project_id"]),
            is_primary=row["is_primary"], created_by=row["created_by"], created_at=row["created_at"],
        )

    async def link_task_idea(
        self, tenant_id: str, task_id: str, idea_id: str, created_by: str,
        relation: str = "implements",
    ) -> TaskIdeaLink:
        async with tenant_transaction(tenant_id) as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO work_task_ideas(tenant_id, task_id, idea_id, relation, created_by)
                VALUES($1,$2,$3,$4,$5)
                ON CONFLICT (task_id, idea_id) DO UPDATE SET relation = EXCLUDED.relation
                RETURNING *
                """,
                _uid(tenant_id), _uid(task_id), _uid(idea_id), relation, created_by,
            )
        return TaskIdeaLink(
            id=str(row["id"]), tenant_id=str(row["tenant_id"]),
            task_id=str(row["task_id"]), idea_id=str(row["idea_id"]),
            relation=row["relation"], created_by=row["created_by"], created_at=row["created_at"],
        )

    async def add_dependency(
        self, tenant_id: str, task_id: str, depends_on_task_id: str, created_by: str,
    ) -> TaskDependency:
        if task_id == depends_on_task_id:
            raise ValueError("Uma tarefa não pode depender de si mesma")
        async with tenant_transaction(tenant_id) as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO work_task_dependencies(tenant_id, task_id, depends_on_task_id, created_by)
                VALUES($1,$2,$3,$4)
                ON CONFLICT (task_id, depends_on_task_id) DO UPDATE SET task_id = EXCLUDED.task_id
                RETURNING *
                """,
                _uid(tenant_id), _uid(task_id), _uid(depends_on_task_id), created_by,
            )
        return TaskDependency(
            id=str(row["id"]), tenant_id=str(row["tenant_id"]),
            task_id=str(row["task_id"]), depends_on_task_id=str(row["depends_on_task_id"]),
            created_by=row["created_by"], created_at=row["created_at"],
        )

    async def list_projects_for_idea(self, tenant_id: str, idea_id: str) -> list[str]:
        async with tenant_transaction(tenant_id) as conn:
            rows = await conn.fetch(
                "SELECT project_id FROM work_idea_projects WHERE idea_id = $1", _uid(idea_id),
            )
        return [str(r["project_id"]) for r in rows]

    async def list_ideas_for_project(self, tenant_id: str, project_id: str) -> list[str]:
        async with tenant_transaction(tenant_id) as conn:
            rows = await conn.fetch(
                "SELECT idea_id FROM work_idea_projects WHERE project_id = $1", _uid(project_id),
            )
        return [str(r["idea_id"]) for r in rows]

    async def list_projects_for_task(self, tenant_id: str, task_id: str) -> list[str]:
        async with tenant_transaction(tenant_id) as conn:
            rows = await conn.fetch(
                "SELECT project_id FROM work_task_projects WHERE task_id = $1", _uid(task_id),
            )
        return [str(r["project_id"]) for r in rows]

    async def list_tasks_for_project(self, tenant_id: str, project_id: str) -> list[str]:
        async with tenant_transaction(tenant_id) as conn:
            rows = await conn.fetch(
                "SELECT task_id FROM work_task_projects WHERE project_id = $1", _uid(project_id),
            )
        return [str(r["task_id"]) for r in rows]

    async def list_ideas_for_task(self, tenant_id: str, task_id: str) -> list[str]:
        async with tenant_transaction(tenant_id) as conn:
            rows = await conn.fetch(
                "SELECT idea_id FROM work_task_ideas WHERE task_id = $1", _uid(task_id),
            )
        return [str(r["idea_id"]) for r in rows]

    async def list_dependencies(self, tenant_id: str, task_id: str) -> list[dict[str, Any]]:
        """Tarefas das quais `task_id` depende (bloqueadoras), com status atual."""
        query = """
            SELECT dep.id AS task_id, dep.title, dep.status
            FROM work_task_dependencies d
            JOIN work_tasks dep ON dep.id = d.depends_on_task_id
            WHERE d.task_id = $1
        """
        async with tenant_transaction(tenant_id) as conn:
            rows = await conn.fetch(query, _uid(task_id))
        return [{"task_id": str(r["task_id"]), "title": r["title"], "status": r["status"]} for r in rows]

    async def list_blocking(self, tenant_id: str, task_id: str) -> list[dict[str, Any]]:
        """Tarefas que dependem de `task_id` (o que fica destravado se esta concluir)."""
        query = """
            SELECT t.id AS task_id, t.title, t.status
            FROM work_task_dependencies d
            JOIN work_tasks t ON t.id = d.task_id
            WHERE d.depends_on_task_id = $1
        """
        async with tenant_transaction(tenant_id) as conn:
            rows = await conn.fetch(query, _uid(task_id))
        return [{"task_id": str(r["task_id"]), "title": r["title"], "status": r["status"]} for r in rows]

    async def is_blocked(self, tenant_id: str, task_id: str) -> bool:
        deps = await self.list_dependencies(tenant_id, task_id)
        return any(d["status"] not in ("done", "cancelled", "archived") for d in deps)


# ─── WorkEventRepository (append-only) ─────────────────────────────────────

class WorkEventRepository:
    async def record(self, event: WorkEvent) -> str:
        entity_type = (
            event.entity_type.value if hasattr(event.entity_type, "value") else event.entity_type
        )
        async with tenant_transaction(event.tenant_id) as conn:
            await conn.execute(
                """
                INSERT INTO work_events(
                    id, tenant_id, entity_type, entity_id, event_type,
                    before_state, after_state, actor_id, correlation_id, created_at
                ) VALUES($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8,$9,$10)
                """,
                _uid(event.id), _uid(event.tenant_id), entity_type, _uid(event.entity_id),
                event.event_type, serialize_jsonb(event.before_state),
                serialize_jsonb(event.after_state), event.actor_id, event.correlation_id,
                event.created_at,
            )
        logger.info(
            "WORK_EVENT tenant=%s entity=%s/%s event=%s actor=%s correlation=%s",
            event.tenant_id, entity_type, event.entity_id, event.event_type,
            event.actor_id, event.correlation_id,
        )
        return event.id

    async def already_processed(self, tenant_id: str, correlation_id: str) -> bool:
        """Dedupe/anti-echo: existe algum WorkEvent com este correlation_id?

        Usado pelo webhook Trello (ANTI_ECHO) e por retries idempotentes —
        nunca reprocessa a própria atualização (mesmo correlation_id)."""
        async with tenant_transaction(tenant_id) as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM work_events WHERE correlation_id = $1 LIMIT 1",
                correlation_id,
            )
        return row is not None

    async def list_for_entity(
        self, tenant_id: str, entity_type: str, entity_id: str, limit: int = 50,
    ) -> list[WorkEvent]:
        async with tenant_transaction(tenant_id) as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM work_events
                WHERE entity_type = $1 AND entity_id = $2
                ORDER BY created_at DESC LIMIT $3
                """,
                entity_type, _uid(entity_id), limit,
            )
        return [_row_to_work_event(r) for r in rows]
