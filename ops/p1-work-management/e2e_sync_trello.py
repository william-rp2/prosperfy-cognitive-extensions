#!/usr/bin/env python3
"""
e2e_sync_trello.py — E2E tecnico do P1 (opcao (b) do owner, 29/08/2026).

Exercita WorkService -> outbox -> TrelloSyncEngine -> TrelloComposioAdapter
DIRETAMENTE, sem passar pelo Hermes. Fecha os gates tecnicos; a rota WhatsApp
fica para o Human Acceptance final.

Gates cobertos:
  DB_TO_TRELLO      task_create persiste e o drain cria o card
  BINDING           binding entity->card criado com card_id e hash
  TRELLO_TO_DB_POLL mover o card no Trello e o reconcile_poll refletir no DB
  ANTI_ECHO         o proprio drain nao dispara mudanca inbound
  IDEMPOTENCY       2o poll sem alteracao nao duplica card/evento nem muta DB

Nao usa LLM em nenhum passo. Roda com as mesmas env vars do servico.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, "/home/will/projetos/prosperfy-cognitive-gate-0.3/core/cognitive")

from cognitive.adapters.trello.composio_client import TrelloComposioAdapter
from cognitive.adapters.trello.sync import TrelloSyncEngine
from cognitive.db.connection import close_pools, create_pools
from cognitive.db.repositories.tenancy_repo import TenantRepository
from cognitive.db.repositories.work_repo import (
    IdeaRepository,
    ProjectRepository,
    TaskRepository,
    WorkEventRepository,
    WorkLinkRepository,
)
from cognitive.db.repositories.work_trello_repo import (
    SyncOutboxRepository,
    TrelloBindingRepository,
)
from cognitive.services.work_service import WorkService

LISTA_TODO = "6a90ce518cc366aede8d11bd"       # "A fazer"
LISTA_EM_ANDAMENTO = "6a90ce518cc366aede8d11be"  # "Em andamento"

resultados: dict[str, str] = {}


def marca(gate: str, ok: bool, detalhe: str = "") -> None:
    resultados[gate] = "PASS" if ok else "FAIL"
    print(f"[{'PASS' if ok else 'FAIL'}] {gate} {detalhe}")


async def main() -> int:
    await create_pools()
    tenant = await TenantRepository().get_by_slug(
        os.getenv("COGNITIVE_TENANT_SLUG", "prosperfy-homolog")
    )
    if tenant is None:
        print("tenant nao encontrado")
        return 1
    tenant_id = str(tenant.id)

    binding_repo = TrelloBindingRepository()
    event_repo = WorkEventRepository()
    task_repo = TaskRepository()

    service = WorkService(
        idea_repo=IdeaRepository(),
        project_repo=ProjectRepository(),
        task_repo=task_repo,
        link_repo=WorkLinkRepository(),
        event_repo=event_repo,
        outbox_repo=SyncOutboxRepository(),
        binding_repo=binding_repo,
    )
    engine = TrelloSyncEngine(
        client=TrelloComposioAdapter(),
        idea_repo=IdeaRepository(),
        project_repo=ProjectRepository(),
        task_repo=task_repo,
        binding_repo=binding_repo,
        outbox_repo=SyncOutboxRepository(),
        event_repo=event_repo,
    )

    titulo = f"Teste de sincronizacao {datetime.now(timezone.utc):%H%M%S}"
    corr = str(uuid.uuid4())
    actor = "e2e-p1"

    # ─── 1. DB -> TRELLO ────────────────────────────────────────────────
    criada = await service.task_create(
        tenant_id, actor, corr, {"title": titulo, "description": "E2E tecnico P1"}
    )
    task_id = criada["id"]
    print(f"task criada id={task_id} titulo={titulo!r}")

    drenado = await engine.drain_outbox_once(tenant_id)
    print("drain:", drenado)

    binding = await binding_repo.get_by_entity(tenant_id, "task", task_id)
    card_id = binding.card_id if binding else None
    marca("DB_TO_TRELLO", bool(card_id), f"card_id={card_id}")
    marca(
        "BINDING",
        bool(binding and binding.card_id and binding.last_synced_hash),
        f"sync_state={getattr(binding, 'sync_state', None)}",
    )
    if not card_id:
        return 1

    # ─── 2. ANTI-ECHO: poll logo apos o drain nao pode aplicar nada ─────
    async def contar_eventos() -> int:
        return len(await event_repo.list_for_entity(tenant_id, "task", task_id))

    eventos_antes = await contar_eventos()
    eco = await engine.reconcile_poll(tenant_id)
    eventos_pos_eco = await contar_eventos()
    marca(
        "ANTI_ECHO",
        eco.get("applied", 0) == 0 and eventos_pos_eco == eventos_antes,
        f"applied={eco.get('applied')} eventos {eventos_antes}->{eventos_pos_eco}",
    )

    # ─── 3. TRELLO -> DB via polling ────────────────────────────────────
    cliente = TrelloComposioAdapter()
    await cliente.update_card(card_id, idList=LISTA_EM_ANDAMENTO)
    movido_em = time.monotonic()
    print("card movido no Trello: A fazer -> Em andamento")

    aplicado = 0
    for tentativa in range(6):
        await asyncio.sleep(5)
        poll = await engine.reconcile_poll(tenant_id)
        if poll.get("applied", 0) > 0:
            aplicado = poll["applied"]
            break
    latencia = time.monotonic() - movido_em

    task = await task_repo.get(tenant_id, task_id)
    status = getattr(task, "status", None)
    status_str = getattr(status, "value", str(status))
    marca(
        "TRELLO_TO_DB_POLL",
        aplicado > 0 and status_str == "in_progress",
        f"status={status_str} applied={aplicado}",
    )
    eventos_pos_poll = await contar_eventos()
    marca("WORK_EVENT_CREATED", eventos_pos_poll > eventos_pos_eco,
          f"eventos {eventos_pos_eco}->{eventos_pos_poll}")
    print(f"TRELLO_TO_DB_LATENCY_SECONDS={latencia:.1f}")

    # ─── 4. IDEMPOTENCIA: novo poll sem alteracao ───────────────────────
    poll2 = await engine.reconcile_poll(tenant_id)
    task2 = await task_repo.get(tenant_id, task_id)
    eventos_final = await contar_eventos()
    binding2 = await binding_repo.get_by_entity(tenant_id, "task", task_id)
    marca(
        "IDEMPOTENCY",
        poll2.get("applied", 0) == 0
        and eventos_final == eventos_pos_poll
        and binding2.card_id == card_id
        and getattr(task2, "updated_at", None) == getattr(task, "updated_at", None),
        f"applied={poll2.get('applied')} eventos={eventos_final} card={binding2.card_id == card_id}",
    )

    print("\n===== RESUMO =====")
    for gate, valor in resultados.items():
        print(f"{gate}={valor}")
    print(f"TRELLO_TO_DB_LATENCY_SECONDS={latencia:.1f}")
    print(f"TASK_ID={task_id}")
    print(f"CARD_ID={card_id}")

    await close_pools()
    return 0 if all(v == "PASS" for v in resultados.values()) else 1


sys.exit(asyncio.run(main()))
