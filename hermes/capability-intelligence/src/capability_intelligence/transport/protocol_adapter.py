"""
protocol_adapter.py — Interface abstrata para todos os adaptadores de transporte.

O restante do Motor Cognitivo nunca depende do protocolo utilizado.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import (
    AuthorizationRequest,
    AuthorizationResult,
    CapabilityResult,
    CatalogResult,
    ExecutionReference,
    ExecutionRequest,
    IntentQuery,
    StatusResult,
)


@dataclass
class ProtocolAdapter(ABC):
    """Interface abstrata que todo adaptador de transporte deve implementar."""

    @abstractmethod
    async def resolve_catalog(self, query: IntentQuery) -> CatalogResult:
        """Consulta o Catálogo com uma intencão."""
        ...

    @abstractmethod
    async def authorize(self, request: AuthorizationRequest) -> AuthorizationResult:
        """Valida autorizacão."""
        ...

    @abstractmethod
    async def execute(self, request: ExecutionRequest) -> ExecutionReference:
        """Executa uma Capability."""
        ...

    @abstractmethod
    async def get_result(self, ref: ExecutionReference) -> CapabilityResult:
        """Obtém resultado de uma execucão."""
        ...

    @abstractmethod
    async def get_status(self, ref: ExecutionReference | None = None) -> StatusResult:
        """Obtém status da plataforma."""
        ...