"""
gap_proposal.py — Detecta e registra lacunas de Capabilities.

Quando o Catálogo não encontra Capability adequada para uma intencão,
o Hermes registra a lacuna para que o Prosperfy Skills (ou outro agente)
possa implementar uma nova Capability no futuro.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .models import GapProposal


@dataclass
class GapProposalStore:
    """
    Armazena lacunas detectadas.

    Implementacão inicial: em memória.
    Futuro: Supabase ou Cognitive Register.
    """

    _gaps: list[GapProposal] = field(default_factory=list)

    def register(self, intent: str, domain: str,
                 context: dict | None = None) -> GapProposal:
        """Registra uma lacuna."""
        proposal = GapProposal(
            intent=intent,
            domain=domain,
            context=context or {},
        )
        self._gaps.append(proposal)
        return proposal

    def list_gaps(self) -> list[GapProposal]:
        """Lista todas as lacunas registradas."""
        return list(self._gaps)

    def count_by_domain(self, domain: str) -> int:
        """Quantas lacunas em um domínio."""
        return sum(1 for g in self._gaps if g.domain == domain)