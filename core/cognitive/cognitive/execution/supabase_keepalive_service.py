"""
execution/supabase_keepalive_service.py — SupabaseKeepaliveService (P0).

Orquestra o keepalive read-only dos projetos Supabase com
keepalive_enabled=true do tenant, via a capability supabase.keepalive.run
(ExecutionOrchestrator -> ComposioMcpAdapter -> Compose MCP -> projeto
real). Determinístico, sem LLM.

Isolamento de falha por projeto: cada execução roda em seu próprio
try/except (_run_one) — uma exceção (timeout, erro do adapter, DENY de
policy) vira um ProjectRunOutcome(status='failure') para AQUELE projeto e o
loop sempre segue para o próximo (doc §9 item 9: "Simular falha de um
resource sem afetar os demais"; doc §10 FAILURE_ISOLATION). Mesmo padrão de
InfraService.servidores_status() (Hermes) — aqui do lado Cognitive porque
quem dispara em produção é o scheduler (systemd timer), sem passar por
Hermes/HTTP.

Alerta (doc §8: "2 falhas consecutivas: alerta"): sinalizado no
ProjectRunOutcome.alert; o disparo real de notificação (WhatsApp) é
responsabilidade de quem consome KeepaliveRoundResult — este service não
conhece canal de notificação.
"""

from __future__ import annotations

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
    ) -> None:
        self._orchestrator = orchestrator
        self._projects = project_repo or SupabaseProjectRepository()
        self._runs = run_repo or SupabaseKeepaliveRunRepository()

    async def run_all(
        self,
        tenant_id: str,
        actor_id: str = DEFAULT_SCHEDULER_ACTOR_ID,
        profile: str = DEFAULT_PROFILE,
        triggered_by: str = "scheduler",
    ) -> KeepaliveRoundResult:
        """Roda keepalive em TODOS os projetos com keepalive_enabled=true.

        Isolamento de falha total: ver docstring do módulo. O chamador
        (systemd CLI / rota WhatsApp) sempre recebe um KeepaliveRoundResult
        completo — nunca uma exceção que aborta o round inteiro.
        """
        started_at = datetime.now(timezone.utc)
        result = KeepaliveRoundResult(started_at=started_at, triggered_by=triggered_by)

        projects = await self._projects.list_keepalive_enabled(tenant_id)
        for project in projects:
            outcome = await self._run_one(
                tenant_id=tenant_id,
                project=project,
                actor_id=actor_id,
                profile=profile,
                triggered_by=triggered_by,
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
        de "não encontrado" (este service não formata texto de usuário)."""
        matches = await self._projects.find_by_name(tenant_id, name_query)
        if not matches:
            return None
        project = matches[0]
        return await self._run_one(
            tenant_id=tenant_id,
            project=project,
            actor_id=actor_id,
            profile=profile,
            triggered_by="whatsapp",
        )

    async def _run_one(
        self,
        tenant_id: str,
        project: SupabaseProjectRow,
        actor_id: str,
        profile: str,
        triggered_by: str,
    ) -> ProjectRunOutcome:
        correlation_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc)
        start_monotonic = time.monotonic()

        ctx = ActorContext(
            tenant_id=tenant_id,
            actor_id=actor_id,
            correlation_id=correlation_id,
            credential_ref=f"supabase-keepalive:{project.project_ref}",
            profile=profile,
        )

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

            run_status = "success"
            error_code = None
            error_message = None
        except Exception as exc:  # noqa: BLE001 — isolamento de falha por projeto
            latency_ms = int((time.monotonic() - start_monotonic) * 1000)
            run_status = "failure"
            error_message = sanitize_exception(exc)
            error_code = type(exc).__name__
            logger.warning(
                "Keepalive falhou project_ref=%s correlation=%s error=%s",
                project.project_ref, correlation_id, error_message,
            )

        ended_at = datetime.now(timezone.utc)
        next_run_at = _next_scheduled_run(ended_at)

        consecutive_failures = project.consecutive_failures
        try:
            await self._runs.record(
                tenant_id=tenant_id,
                project_id=project.id,
                started_at=started_at,
                ended_at=ended_at,
                status=run_status,
                latency_ms=latency_ms,
                error_code=error_code,
                error_message=error_message,
                triggered_by=triggered_by,
                correlation_id=correlation_id,
            )
            update = await self._projects.record_run_result(
                tenant_id=tenant_id,
                project_id=project.id,
                run_status=run_status,
                latency_ms=latency_ms if run_status == "success" else None,
                error_code=error_code,
                next_run_at=next_run_at,
            )
            consecutive_failures = update.get("consecutive_failures", consecutive_failures)
        except Exception as persist_exc:  # noqa: BLE001 — persistência nunca derruba o loop
            logger.error(
                "Falha ao persistir resultado de keepalive project_ref=%s: %s",
                project.project_ref, sanitize_exception(persist_exc),
            )

        alert = run_status == "failure" and consecutive_failures >= ALERT_THRESHOLD_CONSECUTIVE_FAILURES

        return ProjectRunOutcome(
            project_ref=project.project_ref,
            display_name=project.display_name,
            status=run_status,
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
