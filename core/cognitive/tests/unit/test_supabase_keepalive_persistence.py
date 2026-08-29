"""
Regressão de persistência incremental do keepalive (P0).

Garantia sob teste: o sucesso de um projeto é persistido assim que o
resultado dele é final, SEM esperar o backoff de retry de outro projeto.

Antes desta garantia, todo o _finalize acontecia depois da última passagem.
Com a política 1m/5m/30m, sucessos obtidos na passagem 1 ficavam ~36 minutos
apenas em memória e um crash durante o backoff apagava a evidência de todos
eles — observado ao vivo em 29/08/2026, com 30 sucessos não persistidos.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest

from cognitive.db.repositories.supabase_ops_repo import SupabaseProjectRow
from cognitive.execution.supabase_keepalive_service import SupabaseKeepaliveService


def _projeto(ref: str, nome: str) -> SupabaseProjectRow:
    return SupabaseProjectRow(
        id=f"id-{ref}",
        tenant_id="t1",
        composio_account="Supabase - Teste",
        project_ref=ref,
        display_name=nome,
        region="sa-east-1",
        plan="free",
        plan_source="teste",
        keepalive_enabled=True,
        status="unknown",
        last_success_at=None,
        last_latency_ms=None,
        consecutive_failures=0,
        last_error_code=None,
        next_run_at=None,
        active=True,
    )


class _ProjectRepoFake:
    def __init__(self, projetos: list[SupabaseProjectRow]) -> None:
        self._projetos = projetos

    async def list_keepalive_enabled(self, tenant_id: str) -> list[SupabaseProjectRow]:
        return list(self._projetos)

    async def record_run_result(self, **kwargs: Any) -> dict[str, Any]:
        return {"consecutive_failures": 0 if kwargs.get("run_status") == "success" else 1}


class _RunRepoEspiao:
    """Registra o instante lógico de cada persistência."""

    def __init__(self, relogio: list[str]) -> None:
        self.gravados: list[tuple[str, str]] = []
        self._relogio = relogio

    async def record(self, **kwargs: Any) -> None:
        self.gravados.append((kwargs["project_id"], kwargs["status"]))
        self._relogio.append("PERSIST:" + kwargs["project_id"])


@pytest.mark.asyncio
async def test_sucesso_persiste_antes_do_backoff_do_projeto_que_falha(monkeypatch):
    """ok-1 passa na passagem 1; fail-1 só falha. A persistência de ok-1 tem
    de acontecer ANTES do sleep de retry, não depois da rodada inteira."""
    relogio: list[str] = []
    projetos = [_projeto("aaaaaaaaaaaaaaaaaaaa", "ok-1"), _projeto("bbbbbbbbbbbbbbbbbbbb", "fail-1")]
    run_repo = _RunRepoEspiao(relogio)

    service = SupabaseKeepaliveService(
        orchestrator=object(),
        project_repo=_ProjectRepoFake(projetos),
        run_repo=run_repo,
        retry_delays_seconds=(0.01, 0.01),
    )

    async def _attempt_fake(self, *, tenant_id, project, actor_id, profile, correlation_id):
        if project.display_name == "ok-1":
            return "success", 12, None, None
        return "failure", 0, "CONN_TIMEOUT_544", "timeout"

    async def _sleep_instrumentado(segundos: float) -> None:
        relogio.append("SLEEP")

    monkeypatch.setattr(SupabaseKeepaliveService, "_attempt_once", _attempt_fake, raising=True)
    monkeypatch.setattr(asyncio, "sleep", _sleep_instrumentado)

    resultado = await service.run_all(tenant_id="t1")

    assert "PERSIST:id-aaaaaaaaaaaaaaaaaaaa" in relogio, "sucesso nunca foi persistido"
    primeiro_persist = relogio.index("PERSIST:id-aaaaaaaaaaaaaaaaaaaa")
    primeiro_sleep = relogio.index("SLEEP") if "SLEEP" in relogio else len(relogio)
    assert primeiro_persist < primeiro_sleep, (
        "o sucesso foi persistido só DEPOIS do backoff de retry — "
        "um crash durante a espera perderia a evidência"
    )

    # O projeto que falha só é persistido uma vez, na última passagem.
    persistidos_fail = [g for g in run_repo.gravados if g[0] == "id-bbbbbbbbbbbbbbbbbbbb"]
    assert len(persistidos_fail) == 1
    assert persistidos_fail[0][1] == "failure"

    # E o sucesso não é re-executado nem re-gravado pelos retries do outro.
    persistidos_ok = [g for g in run_repo.gravados if g[0] == "id-aaaaaaaaaaaaaaaaaaaa"]
    assert len(persistidos_ok) == 1, "retry repetiu um projeto que já tinha sucesso"

    assert resultado.success_count == 1
    assert resultado.failure_count == 1
