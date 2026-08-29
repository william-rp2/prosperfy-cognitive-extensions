"""
finance_service.py — Serviço fino do Hermes para a vertical Financeiro
Pessoal (Track P2 — Financeiro pelo WhatsApp).

Mesmo espírito de infra_service.py / work_management_service.py: o Hermes
NÃO duplica policy/tenancy/auth/SQLite/Pluggy aqui — tudo isso vive no
Cognitive (finance.* capabilities) e é alcançado via CognitiveApiAdapter
(reuso total, zero mudança nele).

    Hermes → FinanceService → CognitiveApiAdapter → Cognitive API
    → Policy/Grant → FinanceApiAdapter (HTTP) → apps/financeiro-pessoal-api
    (SQLite, Pluggy)

Determinístico, sem LLM aqui. Falha fechada: qualquer erro do Cognitive/
transporte propaga como exceção — as tools (finance_tools.py) convertem em
`tool_error(...)`, nunca em sucesso fabricado.
"""

from __future__ import annotations

from typing import Any

from .transport.cognitive_api_adapter import CognitiveApiAdapter


class FinanceService:
    """Chama qualquer capability `finance.*` do Cognitive via CognitiveApiAdapter."""

    def __init__(self, adapter: CognitiveApiAdapter) -> None:
        self._adapter = adapter

    @classmethod
    def from_env(cls) -> "FinanceService":
        """Monta a partir de env vars do CognitiveApiAdapter
        (COGNITIVE_GATEWAY_URL / CREDENTIAL / TENANT_ID / ACTOR_ID)."""
        return cls(CognitiveApiAdapter())

    async def call(self, capability_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """Executa uma capability finance.* e retorna `data` em caso de sucesso.

        Levanta RuntimeError (via CognitiveApiAdapter) em DENY/CONFIRM/erro de
        transporte/validação — nunca retorna sucesso vazio/fabricado. Um 409
        de ambiguidade ou 404 de "não encontrado" da Finance API chega aqui
        como `result.data` normal (a Finance API responde 2xx-equivalente do
        ponto de vista do Cognitive: ver FinanceApiAdapter — 400/404/409 são
        {"success": False, "error": {...}} retornado como dado, não exceção),
        então o caller (finance_tools.py) precisa inspecionar
        `data.get("success")` além do try/except.
        """
        from .models import ExecutionRequest

        ref = await self._adapter.execute(
            ExecutionRequest(capability_id=capability_id, params=params)
        )
        result = await self._adapter.get_result(ref)
        if not result.success:
            raise RuntimeError(result.error or f"Execução de '{capability_id}' falhou")
        return result.data or {}
