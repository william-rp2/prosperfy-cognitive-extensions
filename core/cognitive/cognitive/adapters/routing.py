"""
adapters/routing.py — RoutingSkillsAdapter: despacha invoke_tool por prefixo.

ExecutionOrchestrator recebe um único SkillsAdapterPort no construtor (ver
execution/orchestrator.py) — não sabe, e não precisa saber, que existe mais
de um transporte concreto. Este wrapper implementa o mesmo Protocol e
escolhe internamente entre vários adapters por prefixo de tool_name (que,
para capabilities sem `tools:` no YAML, é o próprio capability_id — ver
orchestrator._run_capability_tools, ramo "capability simples").

Existe para plugar o adapter HTTP da Finance API (P2 — finance.*) ao lado do
ProsperfySkillsAdapter (MCP) sem tocar em orchestrator.py nem em
contracts/capability.py: a arquitetura vigente já lista "adapter
(prosperfy_skills MCP / Composio MCP / HTTP)" como transportes válidos —
isto é a peça de composição que os liga, não um redesenho.
"""

from __future__ import annotations

from typing import Any

from ..contracts.capability import SkillsAdapterPort


class RoutingSkillsAdapter:
    """
    Escolhe um adapter concreto por prefixo de tool_name; sem match, usa
    default_adapter. Implementa SkillsAdapterPort.
    """

    def __init__(
        self,
        default_adapter: SkillsAdapterPort,
        routes: dict[str, SkillsAdapterPort] | None = None,
    ) -> None:
        self._default = default_adapter
        # dict preserva ordem de inserção (Python 3.7+) — primeiro prefixo
        # que bate vence, então rotas mais específicas devem vir primeiro se
        # algum dia dois prefixos puderem colidir no mesmo tool_name.
        self._routes: dict[str, SkillsAdapterPort] = dict(routes or {})

    def _resolve(self, tool_name: str) -> SkillsAdapterPort:
        for prefix, adapter in self._routes.items():
            if tool_name.startswith(prefix):
                return adapter
        return self._default

    async def invoke_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        tenant_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        adapter = self._resolve(tool_name)
        return await adapter.invoke_tool(
            tool_name=tool_name,
            arguments=arguments,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
        )

    async def health(self) -> bool:
        """True apenas se o default e todo adapter roteado estiverem saudáveis."""
        seen: dict[int, SkillsAdapterPort] = {id(self._default): self._default}
        for adapter in self._routes.values():
            seen[id(adapter)] = adapter
        for adapter in seen.values():
            if not await adapter.health():
                return False
        return True
