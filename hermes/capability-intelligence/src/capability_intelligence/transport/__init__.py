"""
transport/__init__.py — Camada de transporte do Capability Intelligence.

Único ponto que conhece o protocolo de comunicacão com a plataforma
Prosperfy Skills (MCP, REST, gRPC, CLI, SDK...).
"""

from .protocol_adapter import ProtocolAdapter