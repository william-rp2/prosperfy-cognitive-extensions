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
from ..gate.redaction import sanitize_exception
from ..policy.engine import PolicyEngine
from ..registry.registry import InMemoryCapabilityRegistry
from ..registry.grant_resolver import GrantResolverPort, RegistryGrantResolver
from ..telemetry.recorder import InMemoryTelemetryRecorder, TelemetryRecord

logger = logging.getLogger(__name__)

# Chaves de metadados que podem existir em resolved_params (ex.: "type" — o
# tipo do recurso, espelhando a coluna tenant_resources.resource_type) mas
# NUNCA são argumentos das tools MCP. O servidor ProsperfySkill (FastMCP)
# valida arguments contra o schema da tool e rejeita chaves extras
# (ValidationError "Unexpected keyword argument" -> CallToolResult.isError=True
# -> "erro de protocolo MCP" no adapter). Sprint 0.3 HOTFIX: o orquestrador
# remove metadados antes de repassar resolved_params como tool args, porque o
# shape de resolved_params (livre no JSONB) não é o contrato de entrada das
# tools.
_RESOURCE_METADATA_NOT_TOOL_ARG_KEYS = frozenset({"type"})

# Phase 1B Slice 1H: infra.action restart-only enforcement (V1 allowlist).
# TODO/backlog: generalizar capability-resource grants numa fase futura.
_INFRA_ACTION_ALLOWED_RESOURCES = frozenset({"prosperfy-vps-homolog"})
_INFRA_ACTION_TOOL_NAME = "prosperfy_vps_controlar_container"
_INFRA_ACTION_CALLER_FORBIDDEN_KEYS = frozenset({
    "host",
    "acao",
    "confirmar",
    "token",
    "linhas",
})


def _reject_infra_action_caller_controlled_fields(params: dict[str, Any]) -> None:
    """Caller must not supply MCP-bound fields — only resource/action/target_*."""
    present = _INFRA_ACTION_CALLER_FORBIDDEN_KEYS.intersection(params.keys())
    if present:
        raise ForbiddenArgumentError(
            "infra.action: caller não pode definir campos MCP "
            f"{sorted(present)} — somente resource, action, target_type, target."
        )


def _build_infra_action_restart_plan(
    params: dict[str, Any],
    tools: list[dict],
) -> tuple[str, dict[str, Any]]:
    """
    Fail-closed plan for infra.action → prosperfy_vps_controlar_container (restart only).

    Returns (tool_name, tool_args) with a NEW dict — never merges caller/YAML params.
    """
    _reject_infra_action_caller_controlled_fields(params)

    resource = params.get("resource")
    if resource != "prosperfy-vps-homolog":
        raise ForbiddenArgumentError(
            f"infra.action: resource '{resource}' não autorizado neste slice "
            f"(permitido: {sorted(_INFRA_ACTION_ALLOWED_RESOURCES)})."
        )

    if params.get("action") != "restart":
        raise ForbiddenArgumentError(
            f"infra.action: action '{params.get('action')}' não permitida — somente 'restart'."
        )

    if params.get("target_type") != "container":
        raise ForbiddenArgumentError(
            f"infra.action: target_type '{params.get('target_type')}' inválido — "
            "somente 'container'."
        )

    target_raw = params.get("target")
    if not isinstance(target_raw, str):
        raise ForbiddenArgumentError("infra.action: target deve ser string não vazia.")
    validated_target = target_raw.strip()
    if not validated_target:
        raise ForbiddenArgumentError("infra.action: target deve ser string não vazia.")

    resolved = params.get("_resolved_resource")
    if not isinstance(resolved, dict):
        raise ForbiddenArgumentError(
            "infra.action: _resolved_resource ausente ou inválido — resource não resolvido."
        )
    host_raw = resolved.get("host")
    if not isinstance(host_raw, str) or not host_raw.strip():
        raise ForbiddenArgumentError(
            "infra.action: host resolvido ausente ou inválido em _resolved_resource."
        )

    if len(tools) != 1:
        raise ForbiddenArgumentError(
            f"infra.action: exatamente 1 tool exigida, recebidas {len(tools)}."
        )
    tool_name = tools[0].get("name")
    if tool_name != _INFRA_ACTION_TOOL_NAME:
        raise ForbiddenArgumentError(
            f"infra.action: tool '{tool_name}' não permitida — "
            f"somente '{_INFRA_ACTION_TOOL_NAME}'."
        )

    tool_args = {
        "host": host_raw.strip(),
        "container": validated_target,
        "acao": "restart",
        "confirmar": True,
    }
    return _INFRA_ACTION_TOOL_NAME, tool_args


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
        grant_resolver: GrantResolverPort | None = None,
        adapter_registry: dict[str, SkillsAdapterPort] | None = None,
    ) -> None:
        self._registry = registry
        self._policy = policy_engine
        self._adapter = skills_adapter
        self._audit = audit_writer
        self._telemetry = telemetry_recorder
        # Track BH: dispatch opcional por capability.adapter (ex.: "browser_harness"
        # -> BrowserAdapter). Aditivo e retrocompativel -- capabilities cujo
        # .adapter nao esta no registry (ou quando adapter_registry=None, o
        # caso de toda capability existente pre-BH) continuam indo 100% para
        # self._adapter, exatamente como antes desta mudanca.
        self._adapter_registry = adapter_registry or {}
        # ADR-V2-002 §3: resolve params.resource (lógico) -> concretos ANTES do
        # adapter. None é permitido (capabilities sem resource, ou runtime que
        # ainda não fia um resolver) — nesse caso params fluem sem resolução.
        self._resource_resolver = resource_resolver
        # Sprint 0.3 RETURN_TO_DEV (Item A): resolução de grant agora é feita
        # por um GrantResolverPort. Em database mode o gateway injeta
        # PostgresGrantResolver (RLS/capability_grants); sem injetação cai em
        # RegistryGrantResolver (in-memory, retrocompat Sprint 0.1).
        self._grant_resolver = grant_resolver or RegistryGrantResolver(registry)
        # Idempotency-Key (Sprint 0.3): cache in-process, chave
        # (tenant_id, profile, capability_id, idempotency_key) -> resposta já
        # concluída. O profile faz parte da chave: a decisão de grant é feita
        # por (tenant, profile, capability) — um actor de perfil inferior
        # reenviando a mesma chave não pode herdar o COMPLETED de um perfil
        # com grant (revisão adversarial, Sprint 0.3 closure). Só COMPLETED é
        # cacheado (DENY/CONFIRM não — policy pode mudar; CONFIRM precisa do
        # fluxo de aprovação de novo). In-process apenas: não sobrevive
        # restart nem é compartilhado entre instâncias — dedup cross-processo
        # exigiria store em banco (fora de escopo do Sprint 0.3).
        self._idempotency_cache: dict[tuple[str, str, str, str], CapabilityExecuteResponse] = {}

    def _resolve_adapter(self, adapter_name: str) -> SkillsAdapterPort:
        """Track BH: capability.adapter -> adapter concreto, com fallback para
        self._adapter (prosperfy_skills) quando nao ha entrada no registry --
        preserva 100% do comportamento anterior a esta mudanca."""
        return self._adapter_registry.get(adapter_name, self._adapter)

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
        # A chave inclui ctx.profile: um actor de perfil diferente (grant
        # distinto) nunca reusa o COMPLETED de outro perfil — senão o DENY de
        # um perfil sem grant seria contornado pela resposta cacheada.
        cache_key = (
            (ctx.tenant_id, ctx.profile, capability_id, idempotency_key)
            if idempotency_key else None
        )
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
        # Sprint 0.3 RETURN_TO_DEV (Item A): consulta agora passa pelo
        # GrantResolverPort (async) — database mode lê capability_grants via
        # RLS; fail-closed em erro de DB (resolve_grant retorna None → DENY).
        grant = await self._grant_resolver.resolve_grant(
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
            if capability_id == "infra.action":
                _reject_infra_action_caller_controlled_fields(params)
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
                adapter_name=capability.adapter,
            )
        except Exception as exc:
            # Sprint 0.3 RETURN_TO_DEV (Item B): nunca loga o traceback bruto
            # (a mensagem da exceção pode embutir segredo, ex.: erro de header
            # do transporte MCP com prefixo do Bearer) — loga versão
            # sanitizada e registra o mesmo valor no response/audit.
            error = sanitize_exception(exc)
            logger.error(
                "Capability execution failed cap=%s tenant=%s error=%s",
                capability_id, ctx.tenant_id, error,
            )
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
        adapter_name: str = "prosperfy_skills",
    ) -> tuple[int, dict[str, Any]]:
        """
        Executa a sequência de tools de uma capability composta.

        Determinístico: sem LLM escolhendo a sequência.
        Retorna (tool_calls_count, result_data).
        """
        adapter = self._resolve_adapter(adapter_name)
        if capability_id == "infra.action":
            tool_name, tool_args = _build_infra_action_restart_plan(params, tools)
            tool_result = await adapter.invoke_tool(
                tool_name=tool_name,
                arguments=tool_args,
                tenant_id=tenant_id,
                correlation_id=correlation_id,
            )
            return 1, {tool_name: tool_result}

        # 'resource'/'_resolved_resource' são bookkeeping do orquestrador —
        # nunca vão crus para o adapter (ADR-V2-002 §3). Tools com
        # args_from_resource=True recebem exclusivamente os parâmetros
        # concretos resolvidos (ex.: host); as demais recebem os params do
        # cliente, sem as chaves de resource.
        client_args = {k: v for k, v in params.items() if k not in ("resource", "_resolved_resource")}

        if not tools:
            # Capability simples (sem steps YAML) — invoca pelo capability_id direto
            result = await adapter.invoke_tool(
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
                # Sprint 0.3 HOTFIX: resolved_params pode carregar metadados do
                # recurso (ex.: 'type') além das chaves de conexão concretas.
                # Metadados não são argumentos de tool MCP — o servidor FastMCP
                # rejeita 'Unexpected keyword argument' (isError=True). Só
                # repassa chaves de conexão concretas como tool args.
                tool_args: dict[str, Any] = {
                    k: v
                    for k, v in resolved.items()
                    if k not in _RESOURCE_METADATA_NOT_TOOL_ARG_KEYS
                }
            else:
                tool_args = dict(client_args)

            try:
                tool_result = await adapter.invoke_tool(
                    tool_name=tool_name,
                    arguments=tool_args,
                    tenant_id=tenant_id,
                    correlation_id=correlation_id,
                )
                results[tool_name] = tool_result
                call_count += 1
            except Exception as exc:
                if required:
                    # `from None`: sem __cause__ cru (se a exception original
                    # embutir segredo, não fica encadeado p/ vazar num repr/
                    # traceback posterior).
                    raise RuntimeError(
                        f"Tool '{tool_name}' obrigatória falhou: "
                        f"{sanitize_exception(exc)}"
                    ) from None
                logger.warning(
                    "Tool opcional '%s' falhou: %s", tool_name, sanitize_exception(exc),
                )
                results[tool_name] = {"error": sanitize_exception(exc)}

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
