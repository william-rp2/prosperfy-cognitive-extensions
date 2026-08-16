"""
execution/orchestrator.py — ExecutionOrchestrator do Cognitive Core V2.

Implementa a ordem de execução inviolável (ADR-V2-004, ADR-V2-005):

  AUTH → TENANT/ACTOR → RESOURCE → CAPABILITY → GRANT → POLICY → EXECUTOR → ADAPTER

O Adapter (ProsperfySkill) NUNCA é chamado antes da Policy retornar ALLOW.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from ..audit.redaction import redact
from ..audit.writer import InMemoryAuditWriter
from ..contracts.audit import AuditEvent, AuditOutcome
from ..contracts.capability import ExecutionRequest, SkillsAdapterPort
from ..contracts.gateway import CapabilityExecuteResponse, GatewayStatus
from ..contracts.policy import PolicyDecision
from ..contracts.tenancy import ActorContext
from ..policy.engine import PolicyEngine
from ..registry.registry import InMemoryCapabilityRegistry
from ..telemetry.recorder import InMemoryTelemetryRecorder, TelemetryRecord

logger = logging.getLogger(__name__)


class ExecutionOrchestrator:
    """
    Orquestra o fluxo completo de execução de uma capability.

    Compõe: Registry → Grant → Policy → Adapter → Audit → Telemetry.
    """

    def __init__(
        self,
        registry: InMemoryCapabilityRegistry,
        policy_engine: PolicyEngine,
        skills_adapter: SkillsAdapterPort,
        audit_writer: InMemoryAuditWriter,
        telemetry_recorder: InMemoryTelemetryRecorder,
    ) -> None:
        self._registry = registry
        self._policy = policy_engine
        self._adapter = skills_adapter
        self._audit = audit_writer
        self._telemetry = telemetry_recorder

    async def execute(
        self,
        ctx: ActorContext,
        capability_id: str,
        params: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> CapabilityExecuteResponse:
        """
        Executa uma capability respeitando a ordem inviolável de segurança.

        Returns:
            CapabilityExecuteResponse com status completed | pending_confirmation | failed.
        """
        execution_id = str(uuid.uuid4())
        start_ms = time.monotonic()

        # ─── STEP 1: CAPABILITY lookup ──────────────────────────────────
        capability = self._registry.get(capability_id)
        if capability is None:
            return CapabilityExecuteResponse(
                execution_id=execution_id,
                correlation_id=ctx.correlation_id,
                status=GatewayStatus.FAILED,
                error=f"Capability '{capability_id}' não encontrada",
            )

        # ─── STEP 2: GRANT resolution ────────────────────────────────────
        grant = self._registry.resolve_grant(
            tenant_id=ctx.tenant_id,
            profile=ctx.profile,
            capability_id=capability_id,
        )

        # ─── STEP 3: POLICY evaluation ───────────────────────────────────
        verdict = await self._policy.evaluate(ctx, capability, params, grant)

        # ─── STEP 4: Audit inputs redigidos ─────────────────────────────
        inputs_redacted = redact(params, extra_fields=capability.redaction_rules)

        # ─── STEP 5: Despacho por PolicyDecision ────────────────────────
        if verdict.decision == PolicyDecision.DENY:
            duration_ms = int((time.monotonic() - start_ms) * 1000)
            audit_event = AuditEvent(
                tenant_id=ctx.tenant_id,
                actor_id=ctx.actor_id,
                capability_id=capability_id,
                correlation_id=ctx.correlation_id,
                policy_decision=verdict.decision.value,
                outcome=AuditOutcome.DENIED,
                inputs_redacted=inputs_redacted,
                result_summary={"reason": verdict.reason},
                duration_ms=duration_ms,
                execution_id=execution_id,
            )
            audit_id = await self._audit.record(audit_event)
            self._record_telemetry(ctx, capability_id, duration_ms, tool_calls=0)
            return CapabilityExecuteResponse(
                execution_id=execution_id,
                correlation_id=ctx.correlation_id,
                status=GatewayStatus.FAILED,
                audit_id=audit_id,
                error=f"Denied: {verdict.reason}",
            )

        if verdict.decision == PolicyDecision.CONFIRM:
            duration_ms = int((time.monotonic() - start_ms) * 1000)
            audit_event = AuditEvent(
                tenant_id=ctx.tenant_id,
                actor_id=ctx.actor_id,
                capability_id=capability_id,
                correlation_id=ctx.correlation_id,
                policy_decision=verdict.decision.value,
                outcome=AuditOutcome.PENDING_CONFIRMATION,
                inputs_redacted=inputs_redacted,
                result_summary={"reason": verdict.reason},
                duration_ms=duration_ms,
                execution_id=execution_id,
            )
            audit_id = await self._audit.record(audit_event)
            self._record_telemetry(ctx, capability_id, duration_ms, tool_calls=0)
            # CONFIRM: NÃO invoca o adapter (ADR-V2-004)
            return CapabilityExecuteResponse(
                execution_id=execution_id,
                correlation_id=ctx.correlation_id,
                status=GatewayStatus.PENDING_CONFIRMATION,
                audit_id=audit_id,
            )

        # ─── STEP 6: ALLOW → executar capability ────────────────────────
        tool_calls = 0
        result_data: dict[str, Any] = {}
        error: str | None = None
        outcome = AuditOutcome.COMPLETED

        try:
            tool_calls, result_data = await self._run_capability_tools(
                capability_id=capability_id,
                tools=capability.tools,
                params=params,
                tenant_id=ctx.tenant_id,
                correlation_id=ctx.correlation_id,
            )
        except Exception as exc:
            logger.exception(
                "Capability execution failed cap=%s tenant=%s", capability_id, ctx.tenant_id
            )
            error = str(exc)
            outcome = AuditOutcome.FAILED

        duration_ms = int((time.monotonic() - start_ms) * 1000)

        # ─── STEP 7: Audit + Telemetry ───────────────────────────────────
        audit_event = AuditEvent(
            tenant_id=ctx.tenant_id,
            actor_id=ctx.actor_id,
            capability_id=capability_id,
            correlation_id=ctx.correlation_id,
            policy_decision=verdict.decision.value,
            outcome=outcome,
            inputs_redacted=inputs_redacted,
            result_summary={"tool_calls": tool_calls, "error": error},
            duration_ms=duration_ms,
            execution_id=execution_id,
        )
        audit_id = await self._audit.record(audit_event)
        self._record_telemetry(ctx, capability_id, duration_ms, tool_calls)

        if outcome == AuditOutcome.FAILED:
            return CapabilityExecuteResponse(
                execution_id=execution_id,
                correlation_id=ctx.correlation_id,
                status=GatewayStatus.FAILED,
                audit_id=audit_id,
                error=error,
            )

        return CapabilityExecuteResponse(
            execution_id=execution_id,
            correlation_id=ctx.correlation_id,
            status=GatewayStatus.COMPLETED,
            data=result_data,
            audit_id=audit_id,
        )

    async def _run_capability_tools(
        self,
        capability_id: str,
        tools: list[dict],
        params: dict[str, Any],
        tenant_id: str,
        correlation_id: str,
    ) -> tuple[int, dict[str, Any]]:
        """
        Executa a sequência de tools de uma capability composta.

        Determinístico: sem LLM escolhendo a sequência.
        Retorna (tool_calls_count, result_data).
        """
        if not tools:
            # Capability simples (sem steps YAML) — invoca pelo capability_id direto
            result = await self._adapter.invoke_tool(
                tool_name=capability_id,
                arguments=params,
                tenant_id=tenant_id,
                correlation_id=correlation_id,
            )
            return 1, result

        results: dict[str, Any] = {}
        call_count = 0

        for tool_def in tools:
            tool_name: str = tool_def["name"]
            required: bool = tool_def.get("required", True)

            # Argumentos para o adapter: params do cliente + resource resolution
            tool_args: dict[str, Any] = {k: v for k, v in params.items()}

            try:
                tool_result = await self._adapter.invoke_tool(
                    tool_name=tool_name,
                    arguments=tool_args,
                    tenant_id=tenant_id,
                    correlation_id=correlation_id,
                )
                results[tool_name] = tool_result
                call_count += 1
            except Exception as exc:
                if required:
                    raise RuntimeError(
                        f"Tool '{tool_name}' obrigatória falhou: {exc}"
                    ) from exc
                logger.warning("Tool opcional '%s' falhou: %s", tool_name, exc)
                results[tool_name] = {"error": str(exc)}

        return call_count, results

    def _record_telemetry(
        self,
        ctx: ActorContext,
        capability_id: str,
        duration_ms: int,
        tool_calls: int,
    ) -> None:
        self._telemetry.record(TelemetryRecord(
            tenant_id=ctx.tenant_id,
            actor_id=ctx.actor_id,
            capability_id=capability_id,
            correlation_id=ctx.correlation_id,
            latency_ms=duration_ms,
            tool_calls=tool_calls,
        ))
