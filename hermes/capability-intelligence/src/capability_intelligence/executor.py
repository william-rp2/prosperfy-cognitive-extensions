"""
executor.py — Execucão de Capability via contratos públicos.

Responsabilidades:
- Autorizar (contrato público)
- Executar (contrato público)
- Acompanhar execucão
- Obter resultado bruto

O Executor é AGNÓSTICO ao domínio cognitivo.
Ele não conhece Cognitive Register, Feedback, entidades ou eventos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import (
    AuthorizationRequest,
    AuthorizationResult,
    CapabilityResult,
    ExecutionReference,
    ExecutionRequest,
    StatusResult,
)


class AuthorizationPort(Protocol):
    async def authorize(self, request: AuthorizationRequest) -> AuthorizationResult:
        ...


class ExecutionPort(Protocol):
    async def execute(self, request: ExecutionRequest) -> ExecutionReference:
        ...

    async def result(self, ref: ExecutionReference) -> CapabilityResult:
        ...

    async def status(self, ref: ExecutionReference | None = None) -> StatusResult:
        ...


@dataclass
class Executor:
    """
    Executa Capabilities na plataforma externa.
    Não conhece domínio cognitivo, Feedback ou Cognitive Register.
    """

    authorization: AuthorizationPort
    execution: ExecutionPort

    async def run(self, capability_id: str, params: dict,
                  user: str = "", environment: str = "") -> CapabilityResult:
        """Pipeline completo: autoriza → executa → obtém resultado."""
        # 1. Autorizar
        auth_request = AuthorizationRequest(
            capability_id=capability_id,
            user=user,
            environment=environment,
        )
        auth = await self.authorization.authorize(auth_request)
        if not auth.authorized:
            return CapabilityResult(
                success=False,
                error=f"Not authorized: {auth.reason or 'permission denied'}",
            )

        # 2. Executar
        exec_request = ExecutionRequest(
            capability_id=capability_id,
            params=params,
        )
        exec_ref = await self.execution.execute(exec_request)

        # 3. Obter resultado
        result = await self.execution.result(exec_ref)
        return result