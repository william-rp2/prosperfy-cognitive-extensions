"""
Testes do Interpreter — especialização por domínio.
"""

import pytest
from unittest.mock import AsyncMock

from capability_intelligence.interpreter import (
    GenericInterpreter,
    InfrastructureInterpreter,
    Interpreter,
)


class FakeCognitiveRegister:
    """Mock do Cognitive Register para testes."""
    def __init__(self):
        self.events = []
        self.entities = []

    async def create_event(self, event):
        self.events.append(event)

    async def update_entity(self, entity):
        self.entities.append(entity)

    async def create_artifact(self, artifact):
        pass

    async def create_task(self, task):
        pass


class TestInterpreter:
    """Testes do dispatcher de interpretadores."""

    @pytest.mark.asyncio
    async def test_infrastructure_interpreter_found(self):
        registry = FakeCognitiveRegister()
        interp = Interpreter(cognitive_register=registry)
        result = await interp.process(
            result_raw={
                "success": True,
                "metadata": {
                    "duration_ms": 45000,
                    "entities_impacted": ["vps-01"],
                    "rollback_executed": False,
                    "warnings": [],
                },
            },
            capability_id="deploy_api",
            domain="infrastructure",
        )
        assert "Infraestrutura" in result.summary
        assert len(registry.events) == 1
        assert registry.events[0]["event_type"] == "capability:executed:infra"
        assert len(registry.entities) == 1

    @pytest.mark.asyncio
    async def test_generic_fallback(self):
        registry = FakeCognitiveRegister()
        interp = Interpreter(cognitive_register=registry)
        result = await interp.process(
            result_raw={"success": True, "metadata": {}},
            capability_id="some_tool",
            domain="unknown_domain",
        )
        assert "Capability executada" in result.summary
        assert len(registry.events) == 1
        assert registry.events[0]["event_type"] == "capability:executed"

    @pytest.mark.asyncio
    async def test_infrastructure_specialization_selected(self):
        interp = Interpreter()
        spec = interp._find_interpreter("infrastructure")
        assert isinstance(spec, InfrastructureInterpreter)

    @pytest.mark.asyncio
    async def test_generic_fallback_for_unknown_domain(self):
        interp = Interpreter()
        spec = interp._find_interpreter("marketing")
        # Sem MarketingInterpreter registrado, usa GenericInterpreter
        assert isinstance(spec, GenericInterpreter)


class TestDomains:
    """Testes de can_handle dos interpretadores."""

    def test_infrastructure_can_handle(self):
        interp = InfrastructureInterpreter()
        assert interp.can_handle("infrastructure")
        assert not interp.can_handle("marketing")

    def test_generic_handles_anything(self):
        interp = GenericInterpreter()
        assert interp.can_handle("infrastructure")
        assert interp.can_handle("marketing")
        assert interp.can_handle("unknown")
        assert interp.can_handle("")