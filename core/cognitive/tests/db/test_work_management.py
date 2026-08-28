"""
tests/db/test_work_management.py — Matriz de testes obrigatória do Track P1
(P1 spec §10) contra banco real (testcontainers efêmero OU Homolog remoto,
via os mesmos fixtures de tests/db/conftest.py — nunca um DB fake).

Cobertura:
  CREATE_CHAIN          Idea -> Project -> Task, todos persistidos/relacionados.
  MANY_TO_MANY          Idea ligada a 2 projects; task ligada a idea + project.
  DEPENDENCY            Task B depends_on A; is_blocked/list_blocked funcionam.
  HISTORY               Mutations geram WorkEvent com actor/timestamp/correlation.
  TENANT_DENY           RLS real: tenant A não vê linhas do tenant B.
  ARCHIVE_NOT_DELETE    archive() preserva a linha (soft, nunca DELETE físico).
  STATUS_DB_TO_TRELLO   task_update muda status -> outbox -> card muda de lista
                        (Trello fake determinístico via httpx.MockTransport).
  STATUS_TRELLO_TO_DB   card movido manualmente (fake) -> webhook -> task.status muda.
  ANTI_ECHO             Webhook reportando o estado que ACABAMOS de escrever não
                        gera update nem WorkEvent duplicado.
  TRELLO_DOWN           TrelloClient não configurado -> outbox fica pending,
                        mutation DB já está commitada (nunca perdida).

O Trello real (Composio) foi usado para provisionar o board/listas de verdade
(ver relatório final) — aqui usamos um Trello FAKE determinístico porque este
processo de teste não tem TRELLO_API_KEY/TOKEN (só o agente tem, via Composio,
fora deste runtime) — ver TrelloClient(transport=...) injection, mesmo padrão
de CognitiveApiAdapter.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio

from cognitive.adapters.trello.client import TrelloClient
from cognitive.adapters.trello.sync import TrelloSyncEngine, content_hash
from cognitive.contracts.work import Idea, Project, Task
from cognitive.db.repositories.work_repo import (
    IdeaRepository,
    ProjectRepository,
    TaskRepository,
    WorkEventRepository,
    WorkLinkRepository,
)
from cognitive.db.repositories.work_trello_repo import SyncOutboxRepository, TrelloBindingRepository
from cognitive.services.work_service import WorkService

from .conftest import set_tenant_local

pytestmark = pytest.mark.asyncio


# ─── Fake Trello determinístico (httpx.MockTransport) ──────────────────────

class FakeTrelloServer:
    """Backend Trello fake, com estado — permite simular 'humano move o
    card' mutando self.cards diretamente entre passos do teste."""

    def __init__(self) -> None:
        self.cards: dict[str, dict] = {}
        self._next_id = 1

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)

        if request.method == "POST" and path == "/1/cards":
            card_id = f"fakecard-{self._next_id}"
            self._next_id += 1
            card = {
                "id": card_id, "name": params.get("name", ""), "desc": params.get("desc", ""),
                "idList": params.get("idList", ""), "due": params.get("due"), "closed": False,
            }
            self.cards[card_id] = card
            return httpx.Response(200, json=card)

        if request.method == "PUT" and path.startswith("/1/cards/"):
            card_id = path.rsplit("/", 1)[-1]
            card = self.cards.setdefault(card_id, {"id": card_id, "closed": False})
            for key in ("name", "desc", "idList", "due"):
                if key in params:
                    card[key] = params[key]
            if "closed" in params:
                card["closed"] = params["closed"] == "true"
            return httpx.Response(200, json=card)

        if request.method == "GET" and path.startswith("/1/cards/"):
            card_id = path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=self.cards.get(card_id, {"id": card_id}))

        if request.method == "GET" and path.startswith("/1/lists/") and path.endswith("/cards"):
            list_id = path.split("/")[2]
            cards = [c for c in self.cards.values() if c.get("idList") == list_id]
            return httpx.Response(200, json=cards)

        return httpx.Response(404, json={"error": f"unhandled {request.method} {path}"})


def _fake_trello_client() -> tuple[TrelloClient, FakeTrelloServer]:
    server = FakeTrelloServer()
    transport = httpx.MockTransport(server.handle)
    client = TrelloClient(api_key="fake-key", token="fake-token", transport=transport)
    return client, server


# ─── Fixtures locais ────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def tenant_a(db_pools, seeded_tenants: dict[str, str]) -> str:
    return seeded_tenants["tenant-a"]


@pytest_asyncio.fixture
async def tenant_b(db_pools, seeded_tenants: dict[str, str]) -> str:
    return seeded_tenants["tenant-b"]


@pytest_asyncio.fixture
async def work_service() -> WorkService:
    return WorkService(
        idea_repo=IdeaRepository(),
        project_repo=ProjectRepository(),
        task_repo=TaskRepository(),
        link_repo=WorkLinkRepository(),
        event_repo=WorkEventRepository(),
        outbox_repo=SyncOutboxRepository(),
        binding_repo=TrelloBindingRepository(),
    )


def _corr() -> str:
    return f"test-{uuid.uuid4()}"


# ─── CREATE_CHAIN ───────────────────────────────────────────────────────────

async def test_create_chain_idea_project_task(work_service: WorkService, tenant_a: str):
    idea = await work_service.idea_create(
        tenant_a, "actor-1", _corr(), {"title": "Onboarding guiado"},
    )
    project = await work_service.project_create(
        tenant_a, "actor-1", _corr(),
        {"title": "ProsperSend Onboarding", "from_idea_id": idea["id"]},
    )
    task = await work_service.task_create(
        tenant_a, "actor-1", _corr(),
        {"title": "Revisar copy", "project_ids": [project["id"]], "idea_ids": [idea["id"]]},
    )

    assert idea["status"] == "inbox"
    # from_idea_id converte a idea:
    idea_after = await work_service.idea_get(tenant_a, "actor-1", _corr(), {"idea_id": idea["id"]})
    assert idea_after["status"] == "converted"
    assert project["id"] in idea_after["project_ids"]

    project_after = await work_service.project_get(
        tenant_a, "actor-1", _corr(), {"project_id": project["id"]},
    )
    assert idea["id"] in project_after["idea_ids"]
    assert task["id"] in project_after["task_ids"]

    task_after = await work_service.task_get(tenant_a, "actor-1", _corr(), {"task_id": task["id"]})
    assert project["id"] in task_after["project_ids"]
    assert idea["id"] in task_after["idea_ids"]


# ─── MANY_TO_MANY ───────────────────────────────────────────────────────────

async def test_many_to_many_idea_two_projects_task_idea_and_project(
    work_service: WorkService, tenant_a: str,
):
    idea = await work_service.idea_create(tenant_a, "actor-1", _corr(), {"title": "Ideia compartilhada"})
    project1 = await work_service.project_create(tenant_a, "actor-1", _corr(), {"title": "Projeto 1"})
    project2 = await work_service.project_create(tenant_a, "actor-1", _corr(), {"title": "Projeto 2"})

    await work_service.idea_update(
        tenant_a, "actor-1", _corr(),
        {"idea_id": idea["id"], "project_ids": [project1["id"], project2["id"]]},
    )
    idea_after = await work_service.idea_get(tenant_a, "actor-1", _corr(), {"idea_id": idea["id"]})
    assert set(idea_after["project_ids"]) == {project1["id"], project2["id"]}

    task = await work_service.task_create(
        tenant_a, "actor-1", _corr(),
        {"title": "Task ligada", "project_ids": [project1["id"]], "idea_ids": [idea["id"]]},
    )
    task_after = await work_service.task_get(tenant_a, "actor-1", _corr(), {"task_id": task["id"]})
    assert project1["id"] in task_after["project_ids"]
    assert idea["id"] in task_after["idea_ids"]


# ─── DEPENDENCY ─────────────────────────────────────────────────────────────

async def test_dependency_task_b_depends_on_a_blocks_query(work_service: WorkService, tenant_a: str):
    task_a = await work_service.task_create(tenant_a, "actor-1", _corr(), {"title": "Tarefa A (bloqueadora)"})
    task_b = await work_service.task_create(
        tenant_a, "actor-1", _corr(),
        {"title": "Tarefa B (bloqueada)", "depends_on_task_id": task_a["id"]},
    )

    task_b_after = await work_service.task_get(tenant_a, "actor-1", _corr(), {"task_id": task_b["id"]})
    assert task_b_after["is_blocked"] is True
    assert any(d["task_id"] == task_a["id"] for d in task_b_after["depends_on"])

    task_a_after = await work_service.task_get(tenant_a, "actor-1", _corr(), {"task_id": task_a["id"]})
    assert any(b["task_id"] == task_b["id"] for b in task_a_after["blocks"])

    blocked_list = await work_service.task_list(tenant_a, "actor-1", _corr(), {"blocked_only": True})
    assert any(t["id"] == task_b["id"] for t in blocked_list["tasks"])

    # Concluir A libera B:
    await work_service.task_update(tenant_a, "actor-1", _corr(), {"task_id": task_a["id"], "status": "done"})
    task_b_after2 = await work_service.task_get(tenant_a, "actor-1", _corr(), {"task_id": task_b["id"]})
    assert task_b_after2["is_blocked"] is False


async def test_dependency_rejects_self_reference(tenant_a: str):
    repo = TaskRepository()
    links = WorkLinkRepository()
    task = await repo.create(Task(tenant_id=tenant_a, title="Self-dep test", created_by="actor-1"))
    with pytest.raises(ValueError):
        await links.add_dependency(tenant_a, task.id, task.id, "actor-1")


# ─── HISTORY ────────────────────────────────────────────────────────────────

async def test_history_work_event_has_actor_timestamp_correlation(work_service: WorkService, tenant_a: str):
    correlation = _corr()
    idea = await work_service.idea_create(tenant_a, "actor-history", correlation, {"title": "Rastreável"})

    events = WorkEventRepository()
    history = await events.list_for_entity(tenant_a, "idea", idea["id"])
    assert len(history) >= 1
    created_event = history[-1]
    assert created_event.actor_id == "actor-history"
    assert created_event.correlation_id == correlation
    assert created_event.created_at is not None
    assert created_event.after_state.get("title") == "Rastreável"

    await work_service.idea_update(
        tenant_a, "actor-history-2", _corr(), {"idea_id": idea["id"], "status": "approved"},
    )
    history_after = await events.list_for_entity(tenant_a, "idea", idea["id"])
    assert len(history_after) >= 2
    assert any(e.event_type == "status_changed" for e in history_after)


# ─── TENANT_DENY (RLS real) ─────────────────────────────────────────────────

async def test_tenant_deny_cross_tenant_isolation(
    work_service: WorkService, tenant_a: str, tenant_b: str,
):
    idea = await work_service.idea_create(tenant_a, "actor-1", _corr(), {"title": "Só do tenant A"})

    # tenant_b não enxerga a idea do tenant_a via RLS (não é erro — é
    # invisibilidade garantida pelo banco, mesmo padrão de audit_repo.py).
    idea_repo = IdeaRepository()
    leaked = await idea_repo.get(tenant_b, idea["id"])
    assert leaked is None

    listed_b = await idea_repo.list(tenant_b, include_archived=True, limit=1000)
    assert all(i.id != idea["id"] for i in listed_b)

    listed_a = await idea_repo.list(tenant_a, include_archived=True, limit=1000)
    assert any(i.id == idea["id"] for i in listed_a)


# ─── ARCHIVE preserva histórico (nunca hard delete) ────────────────────────

async def test_archive_preserves_row_not_hard_delete(tenant_a: str):
    repo = TaskRepository()
    task = await repo.create(Task(tenant_id=tenant_a, title="Vai ser arquivada", created_by="actor-1"))
    archived = await repo.archive(tenant_a, task.id)
    assert archived is not None
    assert archived.status.value == "archived"
    assert archived.archived_at is not None

    still_there = await repo.get(tenant_a, task.id)
    assert still_there is not None
    assert still_there.id == task.id


# ─── Trello: STATUS_DB_TO_TRELLO / STATUS_TRELLO_TO_DB / ANTI_ECHO ─────────

@pytest_asyncio.fixture
async def trello_engine_and_bindings(tenant_a: str):
    """Monta TrelloSyncEngine com Trello FAKE e semeia board/listas no
    tenant de teste (mesmo shape do seed real feito no Homolog)."""
    client, server = _fake_trello_client()
    bindings = TrelloBindingRepository()
    outbox = SyncOutboxRepository()
    idea_repo, project_repo, task_repo = IdeaRepository(), ProjectRepository(), TaskRepository()
    events = WorkEventRepository()

    board_id = "fakeboard-1"
    await bindings.upsert_board(tenant_a, board_id)
    list_ids = {}
    for key in ("inbox", "ideias", "projetos", "todo", "in_progress", "blocked", "waiting", "done"):
        list_id = f"fakelist-{key}"
        await bindings.upsert_list(tenant_a, board_id, key, list_id)
        list_ids[key] = list_id

    engine = TrelloSyncEngine(
        client=client, idea_repo=idea_repo, project_repo=project_repo, task_repo=task_repo,
        binding_repo=bindings, outbox_repo=outbox, event_repo=events,
    )
    return engine, server, list_ids, bindings, outbox, task_repo


async def test_status_db_to_trello_task_move(
    work_service: WorkService, tenant_a: str, trello_engine_and_bindings,
):
    engine, server, list_ids, bindings, outbox, task_repo = trello_engine_and_bindings

    task = await work_service.task_create(tenant_a, "actor-1", _corr(), {"title": "Mover no board"})
    counters = await engine.drain_outbox_once(tenant_a)
    assert counters["done"] >= 1

    binding = await bindings.get_by_entity(tenant_a, "task", task["id"])
    assert binding is not None and binding.card_id is not None
    card = server.cards[binding.card_id]
    assert card["idList"] == list_ids["todo"]

    await work_service.task_update(tenant_a, "actor-1", _corr(), {"task_id": task["id"], "status": "in_progress"})
    counters2 = await engine.drain_outbox_once(tenant_a)
    assert counters2["done"] >= 1
    card_after = server.cards[binding.card_id]
    assert card_after["idList"] == list_ids["in_progress"]


async def test_status_trello_to_db_card_moved_manually(
    work_service: WorkService, tenant_a: str, trello_engine_and_bindings,
):
    engine, server, list_ids, bindings, outbox, task_repo = trello_engine_and_bindings

    task = await work_service.task_create(tenant_a, "actor-1", _corr(), {"title": "Card movido manualmente"})
    await engine.drain_outbox_once(tenant_a)
    binding = await bindings.get_by_entity(tenant_a, "task", task["id"])
    card_id = binding.card_id

    # Simula humano arrastando o card para "Concluído" diretamente no Trello:
    server.cards[card_id]["idList"] = list_ids["done"]

    result = await engine.process_webhook_event(tenant_a, {
        "id": f"action-{uuid.uuid4()}", "type": "updateCard",
        "data": {"card": {"id": card_id}},
    })
    assert result["applied"] is True

    task_after = await task_repo.get(tenant_a, task["id"])
    assert task_after.status.value == "done"
    assert task_after.completed_at is not None


async def test_anti_echo_our_own_write_does_not_loop(
    work_service: WorkService, tenant_a: str, trello_engine_and_bindings,
):
    engine, server, list_ids, bindings, outbox, task_repo = trello_engine_and_bindings

    task = await work_service.task_create(tenant_a, "actor-1", _corr(), {"title": "Anti-echo"})
    await engine.drain_outbox_once(tenant_a)
    binding = await bindings.get_by_entity(tenant_a, "task", task["id"])
    card_id = binding.card_id

    events = WorkEventRepository()
    history_before = await events.list_for_entity(tenant_a, "task", task["id"])

    # Webhook chega reportando EXATAMENTE o estado que acabamos de escrever
    # (nenhuma mudança humana real) — deve ser ignorado.
    result = await engine.process_webhook_event(tenant_a, {
        "id": f"action-{uuid.uuid4()}", "type": "updateCard",
        "data": {"card": {"id": card_id}},
    })
    assert result["applied"] is False
    assert "anti-echo" in result["reason"]

    history_after = await events.list_for_entity(tenant_a, "task", task["id"])
    assert len(history_after) == len(history_before)  # nenhum WorkEvent novo


async def test_anti_echo_webhook_redelivery_dedupe(
    work_service: WorkService, tenant_a: str, trello_engine_and_bindings,
):
    engine, server, list_ids, bindings, outbox, task_repo = trello_engine_and_bindings

    task = await work_service.task_create(tenant_a, "actor-1", _corr(), {"title": "Redelivery"})
    await engine.drain_outbox_once(tenant_a)
    binding = await bindings.get_by_entity(tenant_a, "task", task["id"])
    card_id = binding.card_id
    server.cards[card_id]["idList"] = list_ids["waiting"]

    action = {
        "id": "action-fixed-id-123", "type": "updateCard",
        "data": {"card": {"id": card_id}},
    }
    first = await engine.process_webhook_event(tenant_a, action)
    assert first["applied"] is True
    second = await engine.process_webhook_event(tenant_a, dict(action))
    assert second["applied"] is False
    assert "redelivery" in second["reason"]


# ─── TRELLO_DOWN ────────────────────────────────────────────────────────────

async def test_trello_down_outbox_persists_mutation_not_lost(work_service: WorkService, tenant_a: str):
    """TrelloClient sem credenciais (estado real deste ambiente — nenhum
    TRELLO_API_KEY/TOKEN configurado) — a mutation DB já foi commitada
    ANTES de qualquer tentativa de sync; drain vira no-op e o outbox
    continua pending (nunca perdido, nunca marcado done por engano)."""
    unconfigured_client = TrelloClient(api_key="", token="")
    assert unconfigured_client.is_configured() is False

    bindings = TrelloBindingRepository()
    outbox = SyncOutboxRepository()
    engine = TrelloSyncEngine(
        client=unconfigured_client, idea_repo=IdeaRepository(), project_repo=ProjectRepository(),
        task_repo=TaskRepository(), binding_repo=bindings, outbox_repo=outbox,
        event_repo=WorkEventRepository(),
    )

    task = await work_service.task_create(tenant_a, "actor-1", _corr(), {"title": "Trello indisponível"})
    task_repo = TaskRepository()
    persisted = await task_repo.get(tenant_a, task["id"])
    assert persisted is not None  # DB canonical já tem a mutation

    counters = await engine.drain_outbox_once(tenant_a)
    assert counters["skipped_not_configured"] == 1

    pending = await outbox.list_pending(tenant_a, limit=100)
    assert any(item.entity_id == task["id"] and item.status.value == "pending" for item in pending)


# ─── content_hash — propriedades determinísticas (unit, sem I/O) ──────────

async def test_content_hash_deterministic_and_sensitive_to_changes():
    h1 = content_hash("Título", "Descrição", "list-1", None, False)
    h2 = content_hash("Título", "Descrição", "list-1", None, False)
    assert h1 == h2
    assert h1 != content_hash("Título diferente", "Descrição", "list-1", None, False)
    assert h1 != content_hash("Título", "Descrição", "list-2", None, False)
    assert h1 != content_hash("Título", "Descrição", "list-1", None, True)
