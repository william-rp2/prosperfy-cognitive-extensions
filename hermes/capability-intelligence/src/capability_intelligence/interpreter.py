"""
interpreter.py — Interpreta resultado bruto e atualiza o Cognitive Register.

Responsabilidades:
- Interpretar resultado (extrair dados estruturados)
- Atualizar Cognitive Register (events, entities, artifacts, tasks)
- Extrair Feedback Compartilhado (operacional, no Supabase)
- Encaminhar para Feedback Store (heuristico, Hermes-side)

Suporta especializacão por domínio através de interpretadores registrados.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Interpretation:
    """Saída da interpretacão de um resultado de Capability."""
    summary: str
    cognitive_event: dict | None = None
    entities_updated: list[dict] = field(default_factory=list)
    artifacts_created: list[dict] = field(default_factory=list)
    tasks_created: list[dict] = field(default_factory=list)
    # Feedback Compartilhado (vai para Cognitive Register)
    shared_feedback: dict | None = None


class CognitiveRegister(Protocol):
    """Interface do Cognitive Register (Supabase)."""
    async def create_event(self, event: dict) -> None: ...
    async def update_entity(self, entity: dict) -> None: ...
    async def create_artifact(self, artifact: dict) -> None: ...
    async def create_task(self, task: dict) -> None: ...


class CapabilityInterpreter(ABC):
    """Base para interpretadores especializados por domínio."""

    @abstractmethod
    def can_handle(self, domain: str) -> bool:
        """Retorna True se este interpretador sabe processar o domínio."""

    @abstractmethod
    async def interpret(self, result_raw: dict,
                        capability_id: str,
                        domain: str) -> Interpretation:
        """Interpreta resultado bruto."""


@dataclass
class InfrastructureInterpreter(CapabilityInterpreter):
    """Interpreta resultados de Capabilities de infraestrutura."""

    def can_handle(self, domain: str) -> bool:
        return domain == "infrastructure"

    async def interpret(self, result_raw: dict,
                        capability_id: str,
                        domain: str) -> Interpretation:
        success = result_raw.get("success", False)
        data = result_raw.get("data", {})
        metadata = result_raw.get("metadata", {})
        entities = metadata.get("entities_impacted", [])

        return Interpretation(
            summary="Infraestrutura executada com sucesso"
                    if success else "Falha na execucão de infraestrutura",
            cognitive_event={
                "event_type": "capability:executed:infra",
                "payload": {
                    "capability_id": capability_id,
                    "success": success,
                    "duration_ms": metadata.get("duration_ms"),
                    "rollback": metadata.get("rollback_executed", False),
                },
            },
            entities_updated=[
                {"name": e, "properties": {"last_operation": capability_id}}
                for e in entities
            ],
            shared_feedback={
                "success": success,
                "duration_ms": metadata.get("duration_ms"),
                "rollback_executed": metadata.get("rollback_executed", False),
                "warnings": metadata.get("warnings", []),
                "entities_impacted": entities,
            },
        )


@dataclass
class GenericInterpreter(CapabilityInterpreter):
    """Fallback para qualquer domínio sem especializacão."""

    def can_handle(self, domain: str) -> bool:
        return True  # sempre aceita (último na cadeia)

    async def interpret(self, result_raw: dict,
                        capability_id: str,
                        domain: str) -> Interpretation:
        success = result_raw.get("success", False)
        metadata = result_raw.get("metadata", {})
        entities = metadata.get("entities_impacted", [])

        return Interpretation(
            summary="Capability executada com sucesso"
                    if success else "Falha na execucão da Capability",
            cognitive_event={
                "event_type": "capability:executed",
                "payload": {
                    "capability_id": capability_id,
                    "domain": domain,
                    "success": success,
                    "duration_ms": metadata.get("duration_ms"),
                },
            },
            shared_feedback={
                "success": success,
                "duration_ms": metadata.get("duration_ms"),
                "warnings": metadata.get("warnings", []),
                "entities_impacted": entities,
            },
        )


@dataclass
class Interpreter:
    """Dispatcher que encontra o interpretador adequado para o domínio."""

    cognitive_register: CognitiveRegister | None = None
    specializations: list[CapabilityInterpreter] = field(default_factory=list)

    def __post_init__(self):
        # Registra interpretadores padrão
        if not self.specializations:
            self.specializations = [
                InfrastructureInterpreter(),
                GenericInterpreter(),  # sempre último
            ]

    async def process(self, result_raw: dict,
                      capability_id: str,
                      domain: str) -> Interpretation:
        """Encontra o interpretador adequado e processa o resultado."""
        # Descobre interpretador pelo domínio
        interpreter = self._find_interpreter(domain)
        interpretation = await interpreter.interpret(
            result_raw, capability_id, domain
        )

        # Atualiza Cognitive Register
        if self.cognitive_register:
            if interpretation.cognitive_event:
                await self.cognitive_register.create_event(
                    interpretation.cognitive_event
                )
            for entity in interpretation.entities_updated:
                await self.cognitive_register.update_entity(entity)
            for artifact in interpretation.artifacts_created:
                await self.cognitive_register.create_artifact(artifact)
            for task in interpretation.tasks_created:
                await self.cognitive_register.create_task(task)

        return interpretation

    def _find_interpreter(self, domain: str) -> CapabilityInterpreter:
        for spec in self.specializations:
            if spec.can_handle(domain):
                return spec
        return GenericInterpreter()