"""
services/work_service.py — WorkService: regras de negócio de Work Management.

Camada entre o WorkManagementAdapter (dispatch de tool_name) e os repositories
(db/repositories/work_repo.py, work_trello_repo.py). Responsabilidades:

1. CRUD de Idea/Project/Task com validação mínima de input.
2. Relações many-to-many (Idea<->Project, Task<->Project, Task<->Idea) e
   dependências Task->Task.
3. Toda mutation gera um WorkEvent (actor/timestamp/correlation_id) —
   histórico append-only, nunca pulado.
4. Toda mutation relevante para Trello (create/update/status-change/archive
   de idea/project/task) enfileira uma linha em work_sync_outbox — DB
   canonical primeiro, Trello é best-effort assíncrono (TRELLO_DOWN nunca
   perde a mutation).
5. Nenhum método aqui conhece Trello diretamente — só grava outbox rows.
   Quem lê a fila e fala com o Trello é adapters/trello/sync.py.

Erros de validação levantam ValueError — o WorkManagementAdapter converte em
RuntimeError (mesma convenção de invoke_tool: nunca retorna sucesso fingido).
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

from ..contracts.work import (
    Idea,
    IdeaStatus,
    Priority,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
    WorkEntityType,
    WorkEvent,
)
from ..db.repositories.work_repo import (
    IdeaRepository,
    ProjectRepository,
    TaskRepository,
    WorkEventRepository,
    WorkLinkRepository,
)
from ..db.repositories.work_trello_repo import SyncOutboxRepository, TrelloBindingRepository

logger = logging.getLogger(__name__)

_VALID_TASK_LINK_TYPES = ("project", "idea", "depends_on")


def _jsonify(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify(v) for v in value]
    return value


def _to_dict(obj: Any) -> dict[str, Any]:
    return {k: _jsonify(v) for k, v in dataclasses.asdict(obj).items()}


def _require(params: dict[str, Any], key: str) -> Any:
    value = params.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"Campo obrigatório ausente: '{key}'")
    return value


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class WorkService:
    def __init__(
        self,
        idea_repo: IdeaRepository,
        project_repo: ProjectRepository,
        task_repo: TaskRepository,
        link_repo: WorkLinkRepository,
        event_repo: WorkEventRepository,
        outbox_repo: SyncOutboxRepository,
        binding_repo: TrelloBindingRepository,
    ) -> None:
        self._ideas = idea_repo
        self._projects = project_repo
        self._tasks = task_repo
        self._links = link_repo
        self._events = event_repo
        self._outbox = outbox_repo
        self._bindings = binding_repo

    # ─── helpers internos ───────────────────────────────────────────────

    async def _emit(
        self,
        tenant_id: str,
        entity_type: WorkEntityType,
        entity_id: str,
        event_type: str,
        actor_id: str,
        correlation_id: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        await self._events.record(WorkEvent(
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            actor_id=actor_id,
            correlation_id=correlation_id,
            before_state=before or {},
            after_state=after or {},
        ))

    async def _enqueue_outbox(
        self,
        tenant_id: str,
        entity_type: str,
        entity_id: str,
        operation: str,
        entity_dict: dict[str, Any],
        correlation_id: str,
    ) -> None:
        """Best-effort — falha aqui NUNCA deve derrubar a mutation DB já commitada.

        A mutation canonical (INSERT/UPDATE em work_ideas/work_projects/work_tasks)
        já foi persistida ANTES desta chamada. Se o enqueue falhar (ex.: blip de
        rede do pool), loga e segue — pior caso é o item ficar fora de sync até
        a próxima reconciliation por polling, nunca uma mutation perdida.
        """
        try:
            await self._outbox.enqueue(
                tenant_id, entity_type, entity_id, operation,
                {"entity": entity_dict}, correlation_id,
            )
        except Exception:
            logger.exception(
                "OUTBOX enqueue falhou (non-fatal) tenant=%s entity=%s/%s op=%s",
                tenant_id, entity_type, entity_id, operation,
            )

    # ─── Idea ────────────────────────────────────────────────────────────

    async def idea_create(
        self, tenant_id: str, actor_id: str, correlation_id: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        title = _require(params, "title")
        idea = Idea(
            tenant_id=tenant_id,
            title=title,
            created_by=actor_id,
            description=params.get("description"),
            source=params.get("source", "whatsapp"),
            impact=params.get("impact"),
            value_notes=params.get("value_notes"),
            tags=list(params.get("tags") or []),
        )
        created = await self._ideas.create(idea)
        after = _to_dict(created)
        await self._emit(
            tenant_id, WorkEntityType.IDEA, created.id, "created",
            actor_id, correlation_id, after=after,
        )
        await self._enqueue_outbox(
            tenant_id, "idea", created.id, "create", after, correlation_id,
        )

        project_ids = params.get("project_ids") or []
        linked_projects: list[str] = []
        for project_id in project_ids:
            await self._links.link_idea_project(tenant_id, created.id, project_id, actor_id)
            linked_projects.append(project_id)
        if linked_projects:
            await self._emit(
                tenant_id, WorkEntityType.IDEA_PROJECT, created.id, "linked",
                actor_id, correlation_id, after={"project_ids": linked_projects},
            )

        result = after
        result["project_ids"] = linked_projects or await self._links.list_projects_for_idea(
            tenant_id, created.id,
        )
        return result

    async def idea_list(
        self, tenant_id: str, actor_id: str, correlation_id: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        ideas = await self._ideas.list(
            tenant_id,
            status=params.get("status"),
            include_archived=bool(params.get("include_archived", False)),
            limit=int(params.get("limit", 50)),
            offset=int(params.get("offset", 0)),
        )
        return {"ideas": [_to_dict(i) for i in ideas], "count": len(ideas)}

    async def idea_get(
        self, tenant_id: str, actor_id: str, correlation_id: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        idea_id = _require(params, "idea_id")
        idea = await self._ideas.get(tenant_id, idea_id)
        if idea is None:
            raise ValueError(f"Idea '{idea_id}' não encontrada")
        result = _to_dict(idea)
        result["project_ids"] = await self._links.list_projects_for_idea(tenant_id, idea_id)
        return result

    async def idea_update(
        self, tenant_id: str, actor_id: str, correlation_id: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        idea_id = _require(params, "idea_id")
        before_row = await self._ideas.get(tenant_id, idea_id)
        if before_row is None:
            raise ValueError(f"Idea '{idea_id}' não encontrada")
        before = _to_dict(before_row)

        kwargs: dict[str, Any] = {}
        for field_name in ("title", "description", "source", "impact", "value_notes", "tags"):
            if field_name in params:
                kwargs[field_name] = params[field_name]
        status_changed = "status" in params
        if status_changed:
            new_status = IdeaStatus(params["status"])
            kwargs["status"] = new_status
            if new_status == IdeaStatus.ARCHIVED:
                kwargs["archived_at"] = datetime.now(timezone.utc)

        updated = await self._ideas.update(tenant_id, idea_id, **kwargs)
        if updated is None:
            raise ValueError(f"Idea '{idea_id}' não encontrada")
        after = _to_dict(updated)

        event_type = "status_changed" if status_changed else "updated"
        await self._emit(
            tenant_id, WorkEntityType.IDEA, idea_id, event_type,
            actor_id, correlation_id, before=before, after=after,
        )
        await self._enqueue_outbox(
            tenant_id, "idea", idea_id,
            "archive" if status_changed and updated.status == IdeaStatus.ARCHIVED else "update",
            after, correlation_id,
        )

        for project_id in params.get("project_ids") or []:
            await self._links.link_idea_project(tenant_id, idea_id, project_id, actor_id)

        after["project_ids"] = await self._links.list_projects_for_idea(tenant_id, idea_id)
        return after

    # ─── Project ────────────────────────────────────────────────────────

    async def project_create(
        self, tenant_id: str, actor_id: str, correlation_id: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        title = _require(params, "title")
        project = Project(
            tenant_id=tenant_id,
            title=title,
            created_by=actor_id,
            description=params.get("description"),
            priority=Priority(params.get("priority", "medium")),
            owner=params.get("owner"),
            start_date=_parse_date(params.get("start_date")),
            due_date=_parse_date(params.get("due_date")),
            tags=list(params.get("tags") or []),
        )
        created = await self._projects.create(project)
        after = _to_dict(created)
        await self._emit(
            tenant_id, WorkEntityType.PROJECT, created.id, "created",
            actor_id, correlation_id, after=after,
        )
        await self._enqueue_outbox(
            tenant_id, "project", created.id, "create", after, correlation_id,
        )

        idea_ids = list(params.get("idea_ids") or [])
        from_idea_id = params.get("from_idea_id")
        if from_idea_id and from_idea_id not in idea_ids:
            idea_ids.append(from_idea_id)

        for idea_id in idea_ids:
            await self._links.link_idea_project(tenant_id, idea_id, created.id, actor_id)

        if from_idea_id:
            # "Transforme essa ideia em um projeto": idea sai do funil (converted).
            idea_before = await self._ideas.get(tenant_id, from_idea_id)
            idea_after_row = await self._ideas.update(
                tenant_id, from_idea_id, status=IdeaStatus.CONVERTED,
            )
            if idea_after_row is not None:
                await self._emit(
                    tenant_id, WorkEntityType.IDEA, from_idea_id, "status_changed",
                    actor_id, correlation_id,
                    before=_to_dict(idea_before) if idea_before else {},
                    after=_to_dict(idea_after_row),
                )
                await self._enqueue_outbox(
                    tenant_id, "idea", from_idea_id, "update",
                    _to_dict(idea_after_row), correlation_id,
                )

        if idea_ids:
            await self._emit(
                tenant_id, WorkEntityType.IDEA_PROJECT, created.id, "linked",
                actor_id, correlation_id, after={"idea_ids": idea_ids},
            )

        after["idea_ids"] = idea_ids
        return after

    async def project_list(
        self, tenant_id: str, actor_id: str, correlation_id: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        projects = await self._projects.list(
            tenant_id,
            status=params.get("status"),
            include_archived=bool(params.get("include_archived", False)),
            limit=int(params.get("limit", 50)),
            offset=int(params.get("offset", 0)),
        )
        return {"projects": [_to_dict(p) for p in projects], "count": len(projects)}

    async def project_get(
        self, tenant_id: str, actor_id: str, correlation_id: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        project_id = _require(params, "project_id")
        project = await self._projects.get(tenant_id, project_id)
        if project is None:
            raise ValueError(f"Project '{project_id}' não encontrado")
        result = _to_dict(project)
        result["idea_ids"] = await self._links.list_ideas_for_project(tenant_id, project_id)
        result["task_ids"] = await self._links.list_tasks_for_project(tenant_id, project_id)
        return result

    async def project_update(
        self, tenant_id: str, actor_id: str, correlation_id: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        project_id = _require(params, "project_id")
        before_row = await self._projects.get(tenant_id, project_id)
        if before_row is None:
            raise ValueError(f"Project '{project_id}' não encontrado")
        before = _to_dict(before_row)

        kwargs: dict[str, Any] = {}
        for field_name in ("title", "description", "owner"):
            if field_name in params:
                kwargs[field_name] = params[field_name]
        if "priority" in params:
            kwargs["priority"] = Priority(params["priority"])
        if "start_date" in params:
            kwargs["start_date"] = _parse_date(params["start_date"])
        if "due_date" in params:
            kwargs["due_date"] = _parse_date(params["due_date"])
        if "tags" in params:
            kwargs["tags"] = params["tags"]
        status_changed = "status" in params
        if status_changed:
            new_status = ProjectStatus(params["status"])
            kwargs["status"] = new_status
            if new_status == ProjectStatus.ARCHIVED:
                kwargs["archived_at"] = datetime.now(timezone.utc)

        updated = await self._projects.update(tenant_id, project_id, **kwargs)
        if updated is None:
            raise ValueError(f"Project '{project_id}' não encontrado")
        after = _to_dict(updated)

        event_type = "status_changed" if status_changed else "updated"
        await self._emit(
            tenant_id, WorkEntityType.PROJECT, project_id, event_type,
            actor_id, correlation_id, before=before, after=after,
        )
        await self._enqueue_outbox(
            tenant_id, "project", project_id,
            "archive" if status_changed and updated.status == ProjectStatus.ARCHIVED else "update",
            after, correlation_id,
        )

        after["idea_ids"] = await self._links.list_ideas_for_project(tenant_id, project_id)
        after["task_ids"] = await self._links.list_tasks_for_project(tenant_id, project_id)
        return after

    # ─── Task ───────────────────────────────────────────────────────────

    async def task_create(
        self, tenant_id: str, actor_id: str, correlation_id: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        title = _require(params, "title")
        task = Task(
            tenant_id=tenant_id,
            title=title,
            created_by=actor_id,
            description=params.get("description"),
            priority=Priority(params.get("priority", "medium")),
            assignee=params.get("assignee"),
            due_at=_parse_datetime(params.get("due_at")),
            source=params.get("source", "whatsapp"),
        )
        created = await self._tasks.create(task)
        after = _to_dict(created)
        await self._emit(
            tenant_id, WorkEntityType.TASK, created.id, "created",
            actor_id, correlation_id, after=after,
        )
        await self._enqueue_outbox(
            tenant_id, "task", created.id, "create", after, correlation_id,
        )

        project_ids = list(params.get("project_ids") or [])
        for i, project_id in enumerate(project_ids):
            await self._links.link_task_project(
                tenant_id, created.id, project_id, actor_id, is_primary=(i == 0),
            )
        idea_ids = list(params.get("idea_ids") or [])
        for idea_id in idea_ids:
            await self._links.link_task_idea(tenant_id, created.id, idea_id, actor_id)

        if project_ids or idea_ids:
            await self._emit(
                tenant_id, WorkEntityType.TASK_PROJECT, created.id, "linked",
                actor_id, correlation_id,
                after={"project_ids": project_ids, "idea_ids": idea_ids},
            )

        depends_on = params.get("depends_on_task_id")
        if depends_on:
            await self._links.add_dependency(tenant_id, created.id, depends_on, actor_id)
            await self._emit(
                tenant_id, WorkEntityType.TASK_DEPENDENCY, created.id, "linked",
                actor_id, correlation_id, after={"depends_on_task_id": depends_on},
            )

        after["project_ids"] = project_ids
        after["idea_ids"] = idea_ids
        return after

    async def task_list(
        self, tenant_id: str, actor_id: str, correlation_id: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        if bool(params.get("blocked_only", False)):
            tasks = await self._tasks.list_blocked(tenant_id, limit=int(params.get("limit", 50)))
        else:
            tasks = await self._tasks.list(
                tenant_id,
                status=params.get("status"),
                assignee=params.get("assignee"),
                project_id=params.get("project_id"),
                include_archived=bool(params.get("include_archived", False)),
                limit=int(params.get("limit", 50)),
                offset=int(params.get("offset", 0)),
            )
        return {"tasks": [_to_dict(t) for t in tasks], "count": len(tasks)}

    async def task_get(
        self, tenant_id: str, actor_id: str, correlation_id: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        task_id = _require(params, "task_id")
        task = await self._tasks.get(tenant_id, task_id)
        if task is None:
            raise ValueError(f"Task '{task_id}' não encontrada")
        result = _to_dict(task)
        result["project_ids"] = await self._links.list_projects_for_task(tenant_id, task_id)
        result["idea_ids"] = await self._links.list_ideas_for_task(tenant_id, task_id)
        result["depends_on"] = await self._links.list_dependencies(tenant_id, task_id)
        result["blocks"] = await self._links.list_blocking(tenant_id, task_id)
        result["is_blocked"] = await self._links.is_blocked(tenant_id, task_id)
        return result

    async def task_update(
        self, tenant_id: str, actor_id: str, correlation_id: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        task_id = _require(params, "task_id")
        before_row = await self._tasks.get(tenant_id, task_id)
        if before_row is None:
            raise ValueError(f"Task '{task_id}' não encontrada")
        before = _to_dict(before_row)

        kwargs: dict[str, Any] = {}
        for field_name in ("title", "description", "assignee", "source"):
            if field_name in params:
                kwargs[field_name] = params[field_name]
        if "priority" in params:
            kwargs["priority"] = Priority(params["priority"])
        if "due_at" in params:
            kwargs["due_at"] = _parse_datetime(params["due_at"])
        status_changed = "status" in params
        if status_changed:
            new_status = TaskStatus(params["status"])
            kwargs["status"] = new_status
            if new_status == TaskStatus.DONE:
                kwargs["completed_at"] = datetime.now(timezone.utc)
            if new_status == TaskStatus.ARCHIVED:
                kwargs["archived_at"] = datetime.now(timezone.utc)

        updated = await self._tasks.update(tenant_id, task_id, **kwargs)
        if updated is None:
            raise ValueError(f"Task '{task_id}' não encontrada")
        after = _to_dict(updated)

        event_type = "status_changed" if status_changed else "updated"
        await self._emit(
            tenant_id, WorkEntityType.TASK, task_id, event_type,
            actor_id, correlation_id, before=before, after=after,
        )
        # status_changed -> 'move' (o outbox worker interpreta como troca de
        # lista no board); demais updates -> 'update'; arquivar -> 'archive'.
        operation = "update"
        if status_changed:
            operation = "archive" if updated.status == TaskStatus.ARCHIVED else "move"
        await self._enqueue_outbox(tenant_id, "task", task_id, operation, after, correlation_id)

        after["project_ids"] = await self._links.list_projects_for_task(tenant_id, task_id)
        after["idea_ids"] = await self._links.list_ideas_for_task(tenant_id, task_id)
        return after

    async def task_link(
        self, tenant_id: str, actor_id: str, correlation_id: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        task_id = _require(params, "task_id")
        link_type = _require(params, "link_type")
        target_id = _require(params, "target_id")
        if link_type not in _VALID_TASK_LINK_TYPES:
            raise ValueError(
                f"link_type inválido '{link_type}' — use um de {_VALID_TASK_LINK_TYPES}"
            )

        task = await self._tasks.get(tenant_id, task_id)
        if task is None:
            raise ValueError(f"Task '{task_id}' não encontrada")

        if link_type == "project":
            await self._links.link_task_project(tenant_id, task_id, target_id, actor_id)
            entity_type = WorkEntityType.TASK_PROJECT
            after = {"task_id": task_id, "project_id": target_id}
        elif link_type == "idea":
            await self._links.link_task_idea(tenant_id, task_id, target_id, actor_id)
            entity_type = WorkEntityType.TASK_IDEA
            after = {"task_id": task_id, "idea_id": target_id}
        else:  # depends_on
            await self._links.add_dependency(tenant_id, task_id, target_id, actor_id)
            entity_type = WorkEntityType.TASK_DEPENDENCY
            after = {"task_id": task_id, "depends_on_task_id": target_id}

        await self._emit(
            tenant_id, entity_type, task_id, "linked",
            actor_id, correlation_id, after=after,
        )
        return {
            "task_id": task_id,
            "link_type": link_type,
            "target_id": target_id,
            "project_ids": await self._links.list_projects_for_task(tenant_id, task_id),
            "idea_ids": await self._links.list_ideas_for_task(tenant_id, task_id),
            "depends_on": await self._links.list_dependencies(tenant_id, task_id),
            "is_blocked": await self._links.is_blocked(tenant_id, task_id),
        }

    # ─── Summary & Sync status ──────────────────────────────────────────

    async def summary(
        self, tenant_id: str, actor_id: str, correlation_id: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        project_id = params.get("project_id")
        if project_id:
            task_ids = await self._links.list_tasks_for_project(tenant_id, project_id)
            tasks = [await self._tasks.get(tenant_id, tid) for tid in task_ids]
            tasks = [t for t in tasks if t is not None]
        else:
            tasks = await self._tasks.list(tenant_id, include_archived=True, limit=1000)

        by_status: dict[str, int] = {}
        for t in tasks:
            by_status[t.status.value] = by_status.get(t.status.value, 0) + 1

        blocked = await self._tasks.list_blocked(tenant_id, limit=1000)
        if project_id:
            blocked_ids = {t.id for t in blocked}
            blocked = [t for t in tasks if t.id in blocked_ids]

        result: dict[str, Any] = {
            "tasks_by_status": by_status,
            "tasks_total": len(tasks),
            "tasks_blocked": len(blocked),
            "blocked_tasks": [{"id": t.id, "title": t.title} for t in blocked],
        }
        if project_id:
            project = await self._projects.get(tenant_id, project_id)
            result["project"] = _to_dict(project) if project else None
        else:
            projects = await self._projects.list(tenant_id, limit=1000)
            ideas = await self._ideas.list(tenant_id, limit=1000)
            result["projects_total"] = len(projects)
            result["ideas_total"] = len(ideas)
        return result

    async def sync_status(
        self, tenant_id: str, actor_id: str, correlation_id: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        outbox_summary = await self._outbox.status_summary(tenant_id)
        board = await self._bindings.get_board(tenant_id)
        lists = await self._bindings.list_lists(tenant_id)
        return {
            "outbox": outbox_summary,
            "board_bound": board is not None,
            "board_id": board.board_id if board else None,
            "lists_bound": sorted(lists.keys()),
            "lists_count": len(lists),
        }
