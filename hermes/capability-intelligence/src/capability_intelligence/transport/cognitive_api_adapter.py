"""
transport/cognitive_api_adapter.py — Client fino do Hermes para o Cognitive Gateway V2.

Implementa ProtocolAdapter (contrato abstrato de transporte do Capability
Intelligence) falando HTTP com a API pública do Cognitive Core
(ADR-V2-005, docs/cognitive-v2/27-HERMES-INTEGRATION.md — passo 2 de
migração: "criar client/adapter Hermes").

Caminho que este adapter cobre (Sprint 0.5 — vertical slice "Como estão
meus servidores?"):

    Hermes → Cognitive API → Identity/Tenant/Actor → Capability Registry
    → Policy → Resource Resolver → ProsperfySkill Adapter → MCP
    → VPS → resultado consolidado → Hermes

Falha fechada (fail-closed):
- Credencial com CR/LF é rejeitada na construção — nunca monta header.
- Qualquer HTTP status != 200 vira exceção (nunca "parece sucesso").
- Erro de transporte (DNS/TLS/timeout) vira RuntimeError com mensagem
  sanatizada — nunca inclui o corpo da resposta, headers ou a credencial.
- A credencial nunca é logada (mesmo padrão de redação do Cognitive).

A API do Cognitive é SÍNCRONA: POST /v1/capabilities/{id}/execute retorna o
resultado completo no mesmo request. `get_result` por isso é um cache
in-process das execuções feitas por este adapter (satisfaz o contrato
ProtocolAdapter/Executor sem inventar um endpoint de fetch que não existe).

Config por ambiente (nunca via código hardcoded):
  COGNITIVE_GATEWAY_URL        — base URL da API (ex.: http://127.0.0.1:8000)
  COGNITIVE_GATEWAY_CREDENTIAL — Bearer token/credential de service identity
  COGNITIVE_TENANT_ID          — header X-Tenant-Id (ADR-V2-002)
  COGNITIVE_ACTOR_ID           — header X-Actor-Id
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

import httpx

from ..models import (
    AuthorizationRequest,
    AuthorizationResult,
    CapabilityMetadata,
    CatalogResult,
    CatalogMatch,
    ExecutionReference,
    ExecutionRequest,
    CapabilityResult,
    IntentQuery,
    ResultMetadata,
    StatusResult,
)
from .protocol_adapter import ProtocolAdapter

logger = logging.getLogger(__name__)

# Nomes de env vars aceitos (fail-closed: ausentes → erro de construção).
ENV_BASE_URL = "COGNITIVE_GATEWAY_URL"
ENV_CREDENTIAL = "COGNITIVE_GATEWAY_CREDENTIAL"
ENV_TENANT_ID = "COGNITIVE_TENANT_ID"
ENV_ACTOR_ID = "COGNITIVE_ACTOR_ID"
ENV_CORRELATION_ID = "COGNITIVE_CORRELATION_ID"

DEFAULT_TIMEOUT = 45.0
_DEFAULT_GATEWAY_PREFIX = "/v1/capabilities"


def _validate_credential_no_control(credential: str) -> None:
    """Rejeita CR/LF na credencial (mesmo guard do Cognitive,
    gate/redaction.validate_credential_no_control) — um secret com `\r`
    produziria header malformado. Nunca loga o valor."""
    if "\r" in credential or "\n" in credential:
        raise ValueError("COGNITIVE_GATEWAY_CREDENTIAL inválida (contém caractere de controle)")


class CognitiveApiAdapter(ProtocolAdapter):
    """
    ProtocolAdapter para o Cognitive Gateway V2 via HTTP (httpx).

    Stateless por request (cria AsyncClient por chamada) — uso seguro em
    runtimes async sem lifecycle explícito do client. `transport` injetável
    (httpx.MockTransport/ASGITransport) para testes determinísticos.
    """

    def __init__(
        self,
        base_url: str | None = None,
        credential: str | None = None,
        tenant_id: str | None = None,
        actor_id: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = (base_url or os.getenv(ENV_BASE_URL, "")).rstrip("/")
        self._credential = credential if credential is not None else os.getenv(ENV_CREDENTIAL, "")
        self._tenant_id = tenant_id if tenant_id is not None else os.getenv(ENV_TENANT_ID, "")
        self._actor_id = actor_id if actor_id is not None else os.getenv(ENV_ACTOR_ID, "")

        if not self._base_url:
            raise ValueError(f"{ENV_BASE_URL} não configurada (base URL da Cognitive API)")
        if not self._credential:
            raise ValueError(f"{ENV_CREDENTIAL} não configurada")
        if not self._tenant_id:
            raise ValueError(f"{ENV_TENANT_ID} não configurado")
        if not self._actor_id:
            raise ValueError(f"{ENV_ACTOR_ID} não configurado")
        _validate_credential_no_control(self._credential)

        self._timeout = timeout
        self._transport = transport
        # Cache in-process de execuções (a API é síncrona — não existe
        # endpoint de fetch assíncrono; ver módulo docstring).
        self._results: dict[str, dict[str, Any]] = {}

    # ─── helpers ───────────────────────────────────────────────────────

    def _headers(self, correlation_id: str | None = None) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._credential}",
            "X-Tenant-Id": self._tenant_id,
            "X-Actor-Id": self._actor_id,
            "X-Correlation-Id": correlation_id or str(uuid.uuid4()),
        }

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        """
        Executa a chamada HTTP com fail-closed.

        Levanta RuntimeError com mensagem sanatizada se:
          - transporte falhar (DNS/TLS/timeout/connection);
          - status HTTP não for 200 (auth 401, deny, 404, 5xx).

        Nunca exponha corpo de resposta, headers ou credencial na exceção.
        """
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.request(method, url, headers=self._headers(), **kwargs)
        except httpx.HTTPError as exc:
            # httpx.HTTPError cobre ConnectError/TimeoutError/NetworkError etc.
            logger.error(
                "CognitiveApiAdapter transport error url=%s type=%s",
                url, type(exc).__name__,
            )
            raise RuntimeError(
                f"Cognitive API inacessível ({type(exc).__name__}) — {url}"
            ) from None

        if response.status_code not in (200,):
            logger.error(
                "CognitiveApiAdapter http error url=%s status=%d",
                url, response.status_code,
            )
            raise RuntimeError(
                f"Cognitive API retornou HTTP {response.status_code} — {url}"
            )

        return response.json()

    # ─── ProtocolAdapter ────────────────────────────────────────────────

    async def resolve_catalog(self, query: IntentQuery) -> CatalogResult:
        """Consulta o catálogo de capabilities do Cognitive (GET /v1/capabilities).

        A API não faz matching semântico: devolve a lista completa de
        capabilities registradas no gateway. O Hermes decide a escolha.
        """
        payload = await self._request("GET", f"{self._base_url}/v1/capabilities")
        matches = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            cap_id = str(item.get("id", ""))
            if not cap_id:
                continue
            matches.append(CatalogMatch(
                capability_id=cap_id,
                score=1.0,
                reason="cognitive-gateway capability",
                metadata=CapabilityMetadata(
                    capability_id=cap_id,
                    description=str(item.get("description", "")),
                    domain=str(item.get("domain", "")),
                    required_role=str(item.get("default_policy", "deny")),
                ),
            ))
        return CatalogResult(
            matches=matches,
            no_match_fallback="Nenhuma capability registrada no Cognitive" if not matches else None,
        )

    async def authorize(self, request: AuthorizationRequest) -> AuthorizationResult:
        """Pré-checagem de autorização (GET /v1/capabilities/{id}).

        Prova apenas que a capability existe e a credencial é válida no
        gateway. A decisão real (grant/policy) acontece no servidor no
        momento da execução — este checkpoint nunca substitui isso.
        """
        try:
            await self._request(
                "GET", f"{self._base_url}{_DEFAULT_GATEWAY_PREFIX}/{request.capability_id}"
            )
            return AuthorizationResult(authorized=True)
        except RuntimeError as exc:
            return AuthorizationResult(
                authorized=False,
                reason=self._redact(str(exc)),
            )

    async def execute(self, request: ExecutionRequest) -> ExecutionReference:
        """Executa a capability no Cognitive (POST /v1/capabilities/{id}/execute).

        Falha fechada: status `failed` da aplicação vira RuntimeError. Apenas
        status `completed`/`pending_confirmation` rendem ExecutionReference
        (o resultado completo fica em cache para `get_result`).
        """
        url = f"{self._base_url}{_DEFAULT_GATEWAY_PREFIX}/{request.capability_id}/execute"
        # idempotency_key é metadado do contrato HTTP, nunca um param da
        # capability — extraímos do params caso o chamador tenha passado por
        # lá (sem mutar o dict do chamador).
        params = dict(request.params)
        idem = params.pop("idempotency_key", None)
        body: dict[str, Any] = {"params": params}
        if idem is not None:
            body["idempotency_key"] = idem
        # F2B: channel é irmão de params — NUNCA dentro de params.
        # Só o ExecutionRequest.channel (envelope trusted) popula body.channel.
        if request.channel is not None:
            body["channel"] = request.channel.to_body_dict()

        payload = await self._request("POST", url, json=body)

        status = str(payload.get("status", ""))
        execution_id = str(payload.get("execution_id", ""))
        if not execution_id:
            raise RuntimeError("Cognitive API respondeu sem execution_id")

        self._results[execution_id] = payload
        if status == "failed":
            error = self._redact(str(payload.get("error") or "execução falhou"))
            raise RuntimeError(f"Capability '{request.capability_id}' falhou: {error}")

        return ExecutionReference(ref=execution_id)

    async def get_result(self, ref: ExecutionReference) -> CapabilityResult:
        """Retorna o resultado completo de uma execução feita por este adapter."""
        payload = self._results.get(ref.ref)
        if payload is None:
            return CapabilityResult(
                success=False,
                error="Unknown execution reference (resultado não disponível neste processo)",
            )

        status = str(payload.get("status", ""))
        if status == "completed":
            return CapabilityResult(
                success=True,
                data=payload.get("data"),
                metadata=ResultMetadata(
                    execution_ref=ExecutionReference(ref=str(payload.get("execution_id", ref.ref))),
                    duration_ms=int(payload.get("duration_ms") or 0),
                ),
            )
        if status == "pending_confirmation":
            return CapabilityResult(
                success=False,
                error="Capability requer confirmação explícita antes de executar",
            )
        return CapabilityResult(
            success=False,
            error=self._redact(str(payload.get("error") or "execução falhou")),
        )

    async def get_status(self, ref: ExecutionReference | None = None) -> StatusResult:
        """Status do Cognitive (GET /v1/status)."""
        payload = await self._request("GET", f"{self._base_url}/v1/status")
        count = int(payload.get("capabilities_count") or 0)
        return StatusResult(
            healthy=bool(payload.get("healthy")),
            capabilities_total=count,
            capabilities_available=count,
            capabilities_degraded=0,
        )

    async def list_resources(self, capability: str = "infra.inspect") -> list[str]:
        """Descoberta autorizada de resources utilizáveis (GET /v1/resources).

        Sprint 0.6 FASE 3: retorna apenas resource_keys lógicos para os quais
        a identidade autenticada tem grant da capability e o resource é
        utilizável. O Hermes NUNCA possui lista hardcoded de servidores — a
        descoberta é do Cognitive. A execução por resource continua passando
        pela autorização normal (defense-in-depth).

        Retorna lista vazia se não houver resources elegíveis (sem grant ou
        tenant sem resources utilizáveis) — fail-closed, sem erro."""
        from urllib.parse import quote

        payload = await self._request(
            "GET",
            f"{self._base_url}/v1/resources?capability={quote(capability)}",
        )
        resources = payload.get("resources") or []
        # Sprint 0.7.6.2 closure: o Cognitive passou a expor display_name no
        # /v1/resources (derivado de resolved_params.host — fonte canônica).
        # Consumimos o nome amigável aqui (NUNCA derivado por regex do key) e
        # o propagamos para a visão consolidada (resources OK e falhas).
        return [
            {
                "resource_key": str(item["resource_key"]),
                "display_name": str(item.get("display_name") or item["resource_key"]),
            }
            for item in resources
            if isinstance(item, dict) and item.get("resource_key")
        ]


# ─── helpers públicos ─────────────────────────────────────────────────

    def _redact(self, message: str) -> str:
        """
        Remove a credencial configurada de qualquer mensagem antes de
        propagar/registrar (mesmo que o payload da API a ecoe por algum bug
        servidor).
        """
        if self._credential and self._credential in message:
            return message.replace(self._credential, "***REDACTED***")
        return message