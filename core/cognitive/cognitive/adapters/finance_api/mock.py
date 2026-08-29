"""
adapters/finance_api/mock.py — MockFinanceApiAdapter para testes e CI.

Não faz chamadas HTTP reais. Espelha o mesmo contrato de retorno do
FinanceApiAdapter real (client.py): {"success": True, "data": ...} ou
{"success": False, "error": {...}} para respostas de negócio — nunca chama
a Finance API de verdade.
"""

from __future__ import annotations

import logging
from typing import Any

from ..prosperfy_skills.guard import guard_arguments

logger = logging.getLogger(__name__)

_MOCK_RESPONSES: dict[str, dict[str, Any]] = {
    "finance.summary.read": {
        "month": "2026-08",
        "category": None,
        "totalBalance": 1000.0,
        "monthIncome": 500.0,
        "monthExpense": 300.0,
        "monthResult": 200.0,
        "openCardBalance": 0.0,
        "lastSync": None,
    },
    "finance.transactions.read": {"transactions": []},
    "finance.accounts.read": {"accounts": []},
    "finance.bills.read": {"bills": []},
    "finance.manual.create": {
        "transaction": {"id": "mock-manual-1", "source": "manual", "amount": 0, "category": None},
        "message": "Registrado (mock).",
    },
    "finance.category.update": {"updated": {"id": "mock-tx-1"}, "category": None},
    "finance.budget.read": {"month": "2026-08", "budgets": []},
    "finance.budget.write": {"budget": {"id": "mock-budget-1", "month": "2026-08", "status": "ok"}},
    "finance.sync.run": {
        "success": True,
        "status": "success",
        "items": 0,
        "accounts": 0,
        "transactionsCreated": 0,
        "transactionsUpdated": 0,
        "errorCount": 0,
        "durationMs": 0,
    },
    "finance.sync.status": {"latest": None, "recent": [], "nextSync": None, "syncEnabled": False},
}


class MockFinanceApiAdapter:
    """
    Adapter mock para a Finance API.

    Implementa a interface de SkillsAdapterPort sem chamadas HTTP.
    Usado por padrão em testes e quando a Finance API real não está
    configurada (FINANCE_API_BASE_URL/FINANCE_API_TOKEN ausentes).
    """

    async def invoke_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        tenant_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        guard_arguments(tool_name, arguments)

        logger.debug(
            "MockFinanceApiAdapter.invoke_tool tool=%s tenant=%s correlation=%s",
            tool_name, tenant_id, correlation_id,
        )
        response = _MOCK_RESPONSES.get(tool_name)
        if response is None:
            return {"success": False, "error": {"code": "unmapped_mock_tool", "message": tool_name, "http_status": 404, "details": {}}}
        return {"success": True, "data": response}

    async def health(self) -> bool:
        return True
