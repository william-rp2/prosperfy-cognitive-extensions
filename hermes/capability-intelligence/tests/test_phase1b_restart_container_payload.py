"""
test_phase1b_restart_container_payload.py — Slice 1J: Hermes infra.action payload alignment.

Prova que _cognitive_restart() envia o contrato executável do Cognitive
(resource/action/target_type/target) sem campos MCP caller-controlled.
ZERO MCP real.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

HERMES_ROOT = Path(__file__).resolve().parents[2]
PHASE1_DIR = HERMES_ROOT / "phase1-infra-read"
CI_SRC = HERMES_ROOT / "capability-intelligence" / "src"

sys.path.insert(0, str(CI_SRC))
sys.path.insert(0, str(PHASE1_DIR))

# Hermes runtime stub — restart_container_tools importa tools.registry no load.
if "tools" not in sys.modules:
    sys.modules["tools"] = types.ModuleType("tools")
if "tools.registry" not in sys.modules:
    _registry_mod = types.ModuleType("tools.registry")
    _registry_mod.registry = MagicMock()
    _registry_mod.tool_error = lambda msg, success=False: msg
    sys.modules["tools.registry"] = _registry_mod

import restart_container_tools as rct  # noqa: E402
from capability_intelligence.models import CapabilityResult, ExecutionReference  # noqa: E402

FORBIDDEN_PARAM_KEYS = frozenset({"container", "host", "acao", "confirmar", "token", "linhas"})

EXPECTED_PARAMS = {
    "resource": "prosperfy-vps-homolog",
    "action": "restart",
    "target_type": "container",
    "target": "omniroute",
}


class _RecordingCognitiveAdapter:
    def __init__(self) -> None:
        self.requests: list = []

    async def execute(self, request):
        self.requests.append(request)
        return ExecutionReference(ref="exec-test")

    async def get_result(self, _ref):
        return CapabilityResult(success=True, data={"ok": True})


def test_cognitive_restart_execution_request_payload(monkeypatch):
    recorder = _RecordingCognitiveAdapter()
    monkeypatch.setattr(
        "capability_intelligence.transport.cognitive_api_adapter.CognitiveApiAdapter",
        lambda: recorder,
    )

    result = rct._cognitive_restart(
        "prosperfy-vps-homolog",
        "omniroute",
        "actor-test",
        "tenant-test",
    )

    assert result["ok"] is True
    assert len(recorder.requests) == 1
    req = recorder.requests[0]
    assert req.capability_id == "infra.action"
    assert req.params == EXPECTED_PARAMS
    assert FORBIDDEN_PARAM_KEYS.isdisjoint(req.params.keys())


def test_cognitive_restart_does_not_call_real_http(monkeypatch):
    """Garantia explícita: adapter fake substitui CognitiveApiAdapter — sem HTTP/MCP."""
    recorder = _RecordingCognitiveAdapter()
    monkeypatch.setattr(
        "capability_intelligence.transport.cognitive_api_adapter.CognitiveApiAdapter",
        lambda: recorder,
    )

    rct._cognitive_restart("prosperfy-vps-homolog", "omniroute", "a", "t")

    assert len(recorder.requests) == 1
