"""
resolver.py — Monta a IntentQuery e consulta o Catálogo.

O Resolver é o ponto de entrada do pipeline Capability Intelligence.
Ele recebe uma necessidade do Motor Cognitivo, traduz em IntentQuery
e envia ao Catálogo da plataforma Prosperfy Skills.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import (
    CatalogResult,
    Domain,
    IntentQuery,
)


class CatalogPort(Protocol):
    """Interface abstrata do Catálogo.

    A implementacão concreta fica no Transport (MCP, REST, etc.).
    O Resolver nunca conhece o protocolo usado.
    """

    async def resolve(self, query: IntentQuery) -> CatalogResult:
        ...


@dataclass
class Resolver:
    """Tradutor de necessidade do Motor Cognitivo em consulta ao Catálogo."""

    catalog: CatalogPort

    async def resolve(self, intent: str, domain: Domain | str,
                      context: dict | None = None,
                      preferences: dict | None = None) -> CatalogResult:
        """Recebe uma intencão e retorna candidatos do Catálogo."""
        query = IntentQuery(
            intent=intent,
            domain=domain,
            context=context or {},
            preferences=preferences or {},
        )
        return await self.catalog.resolve(query)