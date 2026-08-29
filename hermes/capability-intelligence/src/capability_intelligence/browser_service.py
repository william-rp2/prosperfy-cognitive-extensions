"""
browser_service.py — Serviço fino do Hermes para o Browser Harness (Track BH).

Mesmo espírito de infra_service.py / finance_service.py /
work_management_service.py: o Hermes NÃO duplica policy/tenancy/SecretBroker/
CDP aqui — tudo isso vive no Cognitive (capabilities browser.*) e é alcançado
via CognitiveApiAdapter.

    Hermes (rota BROWSER) → BrowserService → CognitiveApiAdapter
    → Cognitive → policy/grant/audit → BrowserAdapter → Browser Worker
    isolado (host dedicado) → browser-harness/CDP → Chrome dedicado → site

Determinístico, sem LLM aqui. Falha fechada: qualquer erro do Cognitive ou do
transporte propaga como exceção — as tools (browser_tools.py) convertem em
`tool_error(...)`, nunca em sucesso fabricado.

Bloqueio humano NÃO é falha: MFA, CAPTCHA, verificação por e-mail, pagamento
e termos atípicos voltam do worker como dado (`blocked_reason`), com
`submitted: false`. O serviço repassa íntegro — quem decide o que fazer é o
LLM da rota, e a decisão final é sempre do usuário.
"""

from __future__ import annotations

from typing import Any

from .transport.cognitive_api_adapter import CognitiveApiAdapter


class BrowserService:
    """Chama qualquer capability `browser.*` do Cognitive via CognitiveApiAdapter."""

    def __init__(self, adapter: CognitiveApiAdapter) -> None:
        self._adapter = adapter

    @classmethod
    def from_env(cls) -> "BrowserService":
        """Monta a partir das env vars do CognitiveApiAdapter
        (COGNITIVE_GATEWAY_URL / CREDENTIAL / TENANT_ID / ACTOR_ID)."""
        return cls(CognitiveApiAdapter())

    async def call(self, capability_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """Executa uma capability browser.* e retorna `data` em caso de sucesso.

        Levanta RuntimeError (via CognitiveApiAdapter) em DENY/CONFIRM/erro de
        transporte. `browser.act` e `browser.account` têm default_policy=deny:
        sem grant explícito, o DENY chega aqui como exceção — que é o
        comportamento correto, não um bug a contornar.
        """
        from .models import ExecutionRequest

        ref = await self._adapter.execute(
            ExecutionRequest(capability_id=capability_id, params=params)
        )
        result = await self._adapter.get_result(ref)
        if not result.success:
            raise RuntimeError(result.error or f"Execução de '{capability_id}' falhou")
        return result.data or {}
