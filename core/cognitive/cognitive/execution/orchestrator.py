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

from ..adapters.prosperfy_skills.guard import ForbiddenArgumentError, guard_arguments
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
        resource_resolver: Any | None = None,
    ) -> None:
        self._registry = registry
        self._policy = policy_engine
        self._adapter = skills_adapter
        self._audit = audit_writer
        self._telemetry = telemetry_recorder
        # ADR-V2-002 §3: resolve params.resource (lógico) -> concretos ANTES do
        # adapter. None é permitido (capabilities sem resource, ou runtime que
        # ainda não fia um resolver) — nesse caso params fluem sem resolução.
        self._resource_resolver = resource_resolver
        # Idempotency-Key (Sprint 0.3): cache in-process, chave
        # (tenant_id, capability_id, idempotency_key) -> resposta já concluída.
        # Só COMPLETED é cacheado (DENY/CONFIRM não — policy pode mudar; CONFIRM
        # precisa do fluxo de aprovação de novo). In-process apenas: não
        # sobrevive restart nem é compartilhado entre instâncias — dedup
        # cross-processo exigiria store em banco (fora de escopo do Sprint 0.3).
        self._idempotency_cache: dict[tuple[str, str, str], CapabilityExecuteResponse] = {}

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

        # ─── STEP 0: IDEMPOTENCY-KEY cache lookup ───────────────────────
        cache_key = (ctx.tenant_id, capability_id, idempotency_key) if idempotency_key else None
        if cache_key is not None and cache_key in self._idempotency_cache:
            return self._idempotency_cache[cache_key]

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

        # ─── STEP 2.4: BOUNDARY GUARD on raw client params ──────────────
        # Defense-in-depth: reject forbidden keys (command/shell/exec/...)
        # and malformed 'resource' values (IP/host masquerading as a
        # logical slug) as early as possible — before resource resolution
        # or policy even run. The adapter (client.py/mock.py) re-checks
        # this right before the real/mock call as a last-line safety net;
        # this earlier check exists so a poisoned request fails fast and
        # audits clearly, instead of silently having the offending key
        # dropped later (args_from_resource tools only forward resolved
        # params, never raw client params).
        try:
            guard_arguments(capability_id, params)
        except ForbiddenArgumentError as exc:
            # outcome=FAILED (not DENIED): this rejects malformed/malicious
            # *input*, not a policy/grant decision — DENIED is reserved for
            # PolicyEngine verdicts (Step 3). policy_decision is schema-
            # constrained to allow/confirm/deny, so 'deny' is still the
            # closest fit there.
            duration_ms = int((time.monotonic() - start_ms) * 1000)
            inputs_redacted = redact(params, extra_fields=capability.redaction_rules)
            audit_event = AuditEvent(
                tenant_id=ctx.tenant_id,
                actor_id=ctx.actor_id,
                capability_id=capability_id,
                correlation_id=ctx.correlation_id,
                policy_decision=PolicyDecision.DENY.value,
                outcome=AuditOutcome.FAILED,
                inputs_redacted=inputs_redacted,
                result_summary={"reason": str(exc)},
                duration_ms=duration_ms,
                execution_id=execution_id,
            )
            audit_id = await self._audit.record(audit_event)
            await self._record_telemetry(ctx, capability_id, duration_ms, tool_calls=0)
            return CapabilityExecuteResponse(
                execution_id=execution_id,
                correlation_id=ctx.correlation_id,
                status=GatewayStatus.FAILED,
                audit_id=audit_id,
                error=str(exc),
            )

        # ─── STEP 2.5: RESOURCE RESOLUTION (ADR-V2-002 §3, ADR-V2-004) ──
        # Ordem obrigatória: Registry → Resource Resolver → Policy → Adapter.
        # 'resource' lógico (ex. "prosperfy-main") vira parâmetros concretos
        # (ex. host) ANTES da Policy avaliar e ANTES do Adapter ser chamado —
        # nunca o valor cru do cliente chega ao adapter.
        resolved_params = params
        if self._resource_resolver is not None and params.get("resource"):
            try:
                resolved_params = await self._resource_resolver.inject_resource_params(
                    ctx.tenant_id, params,
                )
            except ValueError as exc:
                # outcome=FAILED: resource not found/not owned is an input
                # error, not a PolicyEngine verdict — same reasoning as the
                # boundary guard above.
                duration_ms = int((time.monotonic() - start_ms) * 1000)
                inputs_redacted = redact(params, extra_fields=capability.redaction_rules)
                audit_event = AuditEvent(
                    tenant_id=ctx.tenant_id,
                    actor_id=ctx.actor_id,
                    capability_id=capability_id,
                    correlation_id=ctx.correlation_id,
                    policy_decision=PolicyDecision.DENY.value,
                    outcome=AuditOutcome.FAILED,
                    inputs_redacted=inputs_redacted,
                    result_summary={"reason": str(exc)},
                    duration_ms=duration_ms,
                    execution_id=execution_id,
                )
                audit_id = await self._audit.record(audit_event)
                await self._record_telemetry(ctx, capability_id, duration_ms, tool_calls=0)
                return CapabilityExecuteResponse(
                    execution_id=execution_id,
                    correlation_id=ctx.correlation_id,
                    status=GatewayStatus.FAILED,
                    audit_id=audit_id,
                    error=f"Resource resolution failed: {exc}",
                )

        # ─── STEP 3: POLICY evaluation ───────────────────────────────────
        verdict = await self._policy.evaluate(ctx, capability, resolved_params, grant)

        # ─── STEP 4: Audit inputs redigidos ─────────────────────────────
        inputs_redacted = redact(resolved_params, extra_fields=capability.redaction_rules)

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
            await self._record_telemetry(ctx, capability_id, duration_ms, tool_calls=0)
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
            await self._record_telemetry(ctx, capability_id, duration_ms, tool_calls=0)
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
                params=resolved_params,
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
        await self._record_telemetry(ctx, capability_id, duration_ms, tool_calls)

        if outcome == AuditOutcome.FAILED:
            return CapabilityExecuteResponse(
                execution_id=execution_id,
                correlation_id=ctx.correlation_id,
                status=GatewayStatus.FAILED,
                audit_id=audit_id,
                error=error,
            )

        response = CapabilityExecuteResponse(
            execution_id=execution_id,
            correlation_id=ctx.correlation_id,
            status=GatewayStatus.COMPLETED,
            data=result_data,
            audit_id=audit_id,
        )
        # Idempotency-Key: só cacheia sucesso completo — DENY/CONFIRM já
        # retornaram antes de chegar aqui e nunca são cacheados (policy pode
        # mudar; CONFIRM precisa do fluxo de aprovação de novo a cada tentativa).
        if cache_key is not None:
            self._idempotency_cache[cache_key] = response
        return response

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
        # 'resource'/'_resolved_resource' são bookkeeping do orquestrador —
        # nunca vão crus para o adapter (ADR-V2-002 §3). Tools com
        # args_from_resource=True recebem exclusivamente os parâmetros
        # concretos resolvidos (ex.: host); as demais recebem os params do
        # cliente, sem as chaves de resource.
        client_args = {k: v for k, v in params.items() if k not in ("resource", "_resolved_resource")}

        if not tools:
            # Capability simples (sem steps YAML) — invoca pelo capability_id direto
            result = await self._adapter.invoke_tool(
                tool_name=capability_id,
                arguments=client_args,
                tenant_id=tenant_id,
                correlation_id=correlation_id,
            )
            return 1, result

        results: dict[str, Any] = {}
        call_count = 0

        for tool_def in tools:
            tool_name: str = tool_def["name"]
            required: bool = tool_def.get("required", True)
            args_from_resource: bool = tool_def.get("args_from_resource", False)

            if args_from_resource:
                resolved = params.get("_resolved_resource")
                if resolved is None:
                    raise RuntimeError(
                        f"Tool '{tool_name}' requer args_from_resource, mas nenhum "
                        "resource foi resolvido (params sem 'resource', ou "
                        "resource_resolver não configurado neste orchestrator)."
                    )
                tool_args: dict[str, Any] = dict(resolved)
            else:
                tool_args = dict(client_args)

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

    async def _record_telemetry(
        self,
        ctx: ActorContext,
        capability_id: str,
        duration_ms: int,
        tool_calls: int,
    ) -> None:
        """
        Best-effort — nunca deixa uma falha de telemetry (ex.: blip de rede
        no PostgresTelemetryRecorder) derrubar uma resposta que já foi
        auditada (audit_events já commitado antes de cada chamada a este
        método) ou, no caminho de sucesso, pular o cache de idempotência
        (que só é populado DEPOIS deste método retornar). Telemetry é
        observabilidade (não é o requisito de auditoria R13) — uma falha
        aqui nunca deve virar 500 pro caller nem reexecutar a capability
        num retry por causa de uma linha de métrica perdida.
        """
        try:
            await self._telemetry.record(TelemetryRecord(
                tenant_id=ctx.tenant_id,
                actor_id=ctx.actor_id,
                capability_id=capability_id,
                correlation_id=ctx.correlation_id,
                latency_ms=duration_ms,
                tool_calls=tool_calls,
            ))
        except Exception:
            logger.exception(
                "Telemetry record falhou (non-fatal) tenant=%s cap=%s",
                ctx.tenant_id, capability_id,
            )
