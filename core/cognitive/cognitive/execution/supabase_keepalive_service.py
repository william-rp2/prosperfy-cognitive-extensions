"""
execution/supabase_keepalive_service.py — SupabaseKeepaliveService (P0).

Orquestra o keepalive read-only dos projetos Supabase com
keepalive_enabled=true do tenant, via a capability supabase.keepalive.run
(ExecutionOrchestrator -> ComposioMcpAdapter -> Compose MCP -> projeto
real). Determinístico, sem LLM.

Isolamento de falha por projeto: cada tentativa roda em seu próprio
try/except (_attempt_once) — uma exceção (timeout, erro do adapter, DENY de
policy) nunca aborta a rodada; o projeto problemático só fica marcado
'failure' e os demais seguem (doc §9 item 9: "Simular falha de um resource
sem afetar os demais"; doc §10 FAILURE_ISOLATION). Mesmo padrão de
InfraService.servidores_status() (Hermes) — aqui do lado Cognitive porque
quem dispara em produção é o scheduler (systemd timer), sem passar por
Hermes/HTTP.

Retry (doc §4.1/§8: "RETRY=1m, 5m, 30m, máx. 3 retries por janela"):
aplicado em nível de RODADA — todos os projetos ainda pendentes numa
mesma passagem, não um retry isolado por projeto. Isso limita o pior caso
da janela inteira a soma(delays)=36min, em vez de escalar linearmente com
o número de projetos que falharem (17 projetos falhando em série com até
36min cada estouraria a janela de 8h até o próximo round). Ver run_all().

Alerta (doc §8: "2 falhas consecutivas: alerta"): sinalizado em
ProjectRunOutcome.alert; o disparo real de notificação (WhatsApp) é
responsabilidade de quem consome KeepaliveRoundResult — este service não
conhece canal de notificação.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from ..contracts.tenancy import ActorContext
from ..db.repositories.supabase_ops_repo import (
    SupabaseKeepaliveRunRepository,
    SupabaseProjectRepository,
    SupabaseProjectRow,
)
from ..gate.redaction import sanitize_exception
from .orchestrator import ExecutionOrchestrator

logger = logging.getLogger(__name__)

KEEPALIVE_CAPABILITY_ID = "supabase.keepalive.run"
_KEEPALIVE_QUERY = "SELECT now()"
ALERT_THRESHOLD_CONSECUTIVE_FAILURES = 2

# doc §4.1/§8: "RETRY=1m, 5m, 30m (máx. 3 retries por janela)". Retries
# adicionais DEPOIS da 1ª tentativa (imediata) — só quando ainda há
# projeto(s) pendente(s) de sucesso. Injetável via
# SupabaseKeepaliveService(retry_delays_seconds=...) para testes (delays
# quase-zero) sem mudar o comportamento de produção.
DEFAULT_RETRY_DELAYS_SECONDS: tuple[float, ...] = (60.0, 300.0, 1800.0)

# Profile do único service_identity real provisionado no Cognitive Homolog
# para o Hermes (ver service_identities.profile — confirmado ao vivo nesta
# track). Reusado aqui como o profile "operacional" padrão do scheduler:
# evita inventar um profile novo que exigiria seu próprio conjunto de
# capability_grants (ver relatório final da track — grants de
# capability_grants para supabase.* ficaram como HUMAN_BLOCKER: escrita
# nessa tabela de autorização foi bloqueada pelo classifier de auto mode).
DEFAULT_PROFILE = "infra-read"
DEFAULT_SCHEDULER_ACTOR_ID = "supabase-keepalive-scheduler"
DEFAULT_WHATSAPP_ACTOR_ID = "whatsapp-actor"


@dataclass
class ProjectRunOutcome:
    project_ref: str
    display_name: str
    status: str  # "success" | "failure"
    latency_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    consecutive_failures: int = 0
    alert: bool = False


@dataclass
class KeepaliveRoundResult:
    started_at: datetime
    ended_at: datetime | None = None
    outcomes: list[ProjectRunOutcome] = field(default_factory=list)
    triggered_by: str = "scheduler"

    @property
    def success_count(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "success")

    @property
    def failure_count(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "failure")

    @property
    def alerts(self) -> list[ProjectRunOutcome]:
        return [o for o in self.outcomes if o.alert]

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "triggered_by": self.triggered_by,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "outcomes": [
                {
                    "project_ref": o.project_ref,
                    "display_name": o.display_name,
                    "status": o.status,
                    "latency_ms": o.latency_ms,
                    "error_code": o.error_code,
                    "consecutive_failures": o.consecutive_failures,
                    "alert": o.alert,
                }
                for o in self.outcomes
            ],
        }


class SupabaseKeepaliveService:
    """Executa keepalive read-only em todos os projetos habilitados do tenant."""

    def __init__(
        self,
        orchestrator: ExecutionOrchestrator,
        project_repo: SupabaseProjectRepository | None = None,
        run_repo: SupabaseKeepaliveRunRepository | None = None,
        retry_delays_seconds: tuple[float, ...] = DEFAULT_RETRY_DELAYS_SECONDS,
    ) -> None:
        self._orchestrator = orchestrator
        self._projects = project_repo or SupabaseProjectRepository()
        self._runs = run_repo or SupabaseKeepaliveRunRepository()
        self._retry_delays_seconds = retry_delays_seconds

    async def run_all(
        self,
        tenant_id: str,
        actor_id: str = DEFAULT_SCHEDULER_ACTOR_ID,
        profile: str = DEFAULT_PROFILE,
        triggered_by: str = "scheduler",
    ) -> KeepaliveRoundResult:
        """Roda keepalive em TODOS os projetos com keepalive_enabled=true.

        Retry em nível de RODADA (ver docstring do módulo): a 1ª passagem
        tenta todos; passagens seguintes (até 3, com delay 1m/5m/30m antes
        de cada uma) tentam só quem ainda falhou. Isolamento de falha
        total — o chamador (systemd CLI / rota WhatsApp) sempre recebe um
        KeepaliveRoundResult completo, nunca uma exceção que aborta o round.
        """
        started_at = datetime.now(timezone.utc)
        result = KeepaliveRoundResult(started_at=started_at, triggered_by=triggered_by)

        projects = await self._projects.list_keepalive_enabled(tenant_id)
        if not projects:
            result.ended_at = datetime.now(timezone.utc)
            return result

        state: dict[str, dict[str, Any]] = {
            p.project_ref: {
                "project": p,
                "correlation_id": str(uuid.uuid4()),
                "run_started_at": datetime.now(timezone.utc),
                "status": "failure",
                "latency_ms": 0,
                "error_code": None,
                "error_message": None,
            }
            for p in projects
        }
        pending_refs = list(state.keys())

        delays = (0.0, *self._retry_delays_seconds)
        last_pass = len(delays) - 1
        for pass_index, delay in enumerate(delays):
            if not pending_refs:
                break
            if delay > 0:
                logger.info(
                    "Keepalive retry: aguardando %.0fs antes de re-tentar %d projeto(s) pendente(s)",
                    delay, len(pending_refs),
                )
                await asyncio.sleep(delay)

            still_pending: list[str] = []
            for ref in pending_refs:
                entry = state[ref]
                status, latency_ms, error_code, error_message = await self._attempt_once(
                    tenant_id=tenant_id,
                    project=entry["project"],
                    actor_id=actor_id,
                    profile=profile,
                    correlation_id=entry["correlation_id"],
                )
                entry["status"] = status
                entry["latency_ms"] = latency_ms
                entry["error_code"] = error_code
                entry["error_message"] = error_message
                if status == "failure":
                    logger.warning(
                        "Keepalive falhou (passagem %d/%d) project_ref=%s correlation=%s error=%s",
                        pass_index + 1, len(delays), ref, entry["correlation_id"], error_message,
                    )
                    if pass_index < last_pass:
                        still_pending.append(ref)
            pending_refs = still_pending

        for entry in state.values():
            outcome = await self._finalize(
                tenant_id=tenant_id,
                project=entry["project"],
                run_started_at=entry["run_started_at"],
                status=entry["status"],
                latency_ms=entry["latency_ms"],
                error_code=entry["error_code"],
                error_message=entry["error_message"],
                triggered_by=triggered_by,
                correlation_id=entry["correlation_id"],
            )
            result.outcomes.append(outcome)

        result.ended_at = datetime.now(timezone.utc)
        logger.info(
            "Keepalive round concluído triggered_by=%s success=%d failure=%d alerts=%d",
            triggered_by, result.success_count, result.failure_count, len(result.alerts),
        )
        return result

    async def run_one_by_name(
        self,
        tenant_id: str,
        name_query: str,
        actor_id: str = DEFAULT_WHATSAPP_ACTOR_ID,
        profile: str = DEFAULT_PROFILE,
    ) -> ProjectRunOutcome | None:
        """'Teste agora o Supabase X' — keepalive on-demand de UM projeto
        identificado por nome (case-insensitive, substring). Retorna None se
        nenhum projeto bater com name_query — o chamador decide a mensagem
        de "não encontrado" (este service não formata texto de usuário).

        SEM retry (diferente de run_all): é um pedido síncrono de um humano
        no WhatsApp — bloquear a resposta por até 36min numa falha
        transitória seria pior UX que simplesmente responder rápido que
        falhou agora e sugerir tentar de novo."""
        matches = await self._projects.find_by_name(tenant_id, name_query)
        if not matches:
            return None
        project = matches[0]
        correlation_id = str(uuid.uuid4())
        run_started_at = datetime.now(timezone.utc)

        status, latency_ms, error_code, error_message = await self._attempt_once(
            tenant_id=tenant_id, project=project, actor_id=actor_id,
            profile=profile, correlation_id=correlation_id,
        )
        return await self._finalize(
            tenant_id=tenant_id,
            project=project,
            run_started_at=run_started_at,
            status=status,
            latency_ms=latency_ms,
            error_code=error_code,
            error_message=error_message,
            triggered_by="whatsapp",
            correlation_id=correlation_id,
        )

    async def _attempt_once(
        self,
        tenant_id: str,
        project: SupabaseProjectRow,
        actor_id: str,
        profile: str,
        correlation_id: str,
    ) -> tuple[str, int, str | None, str | None]:
        """UMA tentativa de keepalive, sem persistir nada. Retorna
        (status, latency_ms, error_code, error_message). Isolamento de
        falha: qualquer exceção (timeout, erro de transporte do adapter,
        DENY de policy) vira status='failure' aqui — nunca propaga."""
        ctx = ActorContext(
            tenant_id=tenant_id,
            actor_id=actor_id,
            correlation_id=correlation_id,
            credential_ref=f"supabase-keepalive:{project.project_ref}",
            profile=profile,
        )
        start_monotonic = time.monotonic()
        try:
            response = await self._orchestrator.execute(
                ctx=ctx,
                capability_id=KEEPALIVE_CAPABILITY_ID,
                params={
                    "ref": project.project_ref,
                    "account": project.composio_account,
                    "query": _KEEPALIVE_QUERY,
                },
            )
            latency_ms = int((time.monotonic() - start_monotonic) * 1000)
            if response.status.value != "completed":
                raise RuntimeError(response.error or f"status={response.status.value}")
            return "success", latency_ms, None, None
        except Exception as exc:  # noqa: BLE001 — isolamento de falha por projeto
            latency_ms = int((time.monotonic() - start_monotonic) * 1000)
            return "failure", latency_ms, type(exc).__name__, sanitize_exception(exc)

    async def _finalize(
        self,
        tenant_id: str,
        project: SupabaseProjectRow,
        run_started_at: datetime,
        status: str,
        latency_ms: int,
        error_code: str | None,
        error_message: str | None,
        triggered_by: str,
        correlation_id: str,
    ) -> ProjectRunOutcome:
        """Persiste o resultado FINAL (pós todas as tentativas) — uma única
        linha em supabase_keepalive_runs por projeto/execução, nunca uma
        por tentativa. Persistência isolada também: se o INSERT/UPDATE
        falhar (ex.: DB fora do ar), não derruba o loop de run_all — vira
        log de erro, resultado em memória ainda é retornado ao chamador."""
        ended_at = datetime.now(timezone.utc)
        next_run_at = _next_scheduled_run(ended_at)

        consecutive_failures = project.consecutive_failures
        try:
            await self._runs.record(
                tenant_id=tenant_id,
                project_id=project.id,
                started_at=run_started_at,
                ended_at=ended_at,
                status=status,
                latency_ms=latency_ms,
                error_code=error_code,
                error_message=error_message,
                triggered_by=triggered_by,
                correlation_id=correlation_id,
            )
            update = await self._projects.record_run_result(
                tenant_id=tenant_id,
                project_id=project.id,
                run_status=status,
                latency_ms=latency_ms if status == "success" else None,
                error_code=error_code,
                next_run_at=next_run_at,
            )
            consecutive_failures = update.get("consecutive_failures", consecutive_failures)
        except Exception as persist_exc:  # noqa: BLE001 — persistência nunca derruba o loop
            logger.error(
                "Falha ao persistir resultado de keepalive project_ref=%s: %s",
                project.project_ref, sanitize_exception(persist_exc),
            )

        alert = status == "failure" and consecutive_failures >= ALERT_THRESHOLD_CONSECUTIVE_FAILURES

        return ProjectRunOutcome(
            project_ref=project.project_ref,
            display_name=project.display_name,
            status=status,
            latency_ms=latency_ms,
            error_code=error_code,
            error_message=error_message,
            consecutive_failures=consecutive_failures,
            alert=alert,
        )


def _next_scheduled_run(after: datetime) -> datetime:
    """Próxima janela fixa (06:10/14:10/22:10 America/Sao_Paulo) após `after`.

    Cálculo em UTC puro (sem depender de tzdata/zoneinfo no host): América/
    Sao_Paulo é UTC-3 o ano inteiro desde o fim do horário de verão
    brasileiro em 2019 — 06:10/14:10/22:10 -03:00 == 09:10/17:10/01:10 UTC.
    """
    utc_runs = ((9, 10), (17, 10), (1, 10))
    after_utc = after.astimezone(timezone.utc)
    candidates = []
    for day_offset in (0, 1):
        day = after_utc + timedelta(days=day_offset)
        for hour, minute in utc_runs:
            candidate = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate > after_utc:
                candidates.append(candidate)
    return min(candidates)
