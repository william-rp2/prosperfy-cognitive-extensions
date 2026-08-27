"""
test_phase1b_restart_confirmation_routing.py — Slice 1J hotfix: confirmation continuation.

Prova no boundary pré-LLM (resolve_turn_toolsets) que "Sim" com pending do mesmo
actor → INFRA_ACTION + restart_container; sem pending → NORMAL + [].
ZERO Cognitive/MCP real.
"""

from __future__ import annotations

import sys
import types
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

HERMES_ROOT = Path(__file__).resolve().parents[2]
PHASE1_DIR = HERMES_ROOT / "phase1-infra-read"
CI_SRC = HERMES_ROOT / "capability-intelligence" / "src"

sys.path.insert(0, str(CI_SRC))
sys.path.insert(0, str(PHASE1_DIR))

if "tools" not in sys.modules:
    sys.modules["tools"] = types.ModuleType("tools")
if "tools.registry" not in sys.modules:
    _registry_mod = types.ModuleType("tools.registry")
    _registry_mod.registry = MagicMock()
    _registry_mod.tool_error = lambda msg, success=False: msg
    sys.modules["tools.registry"] = _registry_mod

import restart_container_tools as rct  # noqa: E402
from capability_intelligence.capability_router import (  # noqa: E402
    resolve_specialist_route,
    resolve_turn_toolsets,
    route_toolsets,
    set_pending_restart_checker,
)

ACTOR_A = "hermes-homolog"
ACTOR_B = "other-actor"
RESOURCE = "prosperfy-vps-homolog"
CONTAINER = "omniroute"


def _seed_pending(actor: str) -> None:
    pkey = rct._pending_key(actor, RESOURCE, CONTAINER)
    with rct._lock:
        rct._pending[pkey] = {
            "actor": actor,
            "resource": RESOURCE,
            "container": CONTAINER,
            "action": "restart_container",
            "created_at": time.time(),
        }


def _clear_pending() -> None:
    with rct._lock:
        rct._pending.clear()


@pytest.fixture(autouse=True)
def _wire_checker():
    set_pending_restart_checker(rct.has_pending_restart_for_actor)
    _clear_pending()
    yield
    _clear_pending()
    set_pending_restart_checker(None)


def simulate_gateway_dispatch(message: str, actor_id: str | None = None) -> tuple[str, list[str]]:
    """Espelha CAPABILITY_ROUTE + ENABLED_TOOLSETS no gateway."""
    return resolve_turn_toolsets(message, actor_id=actor_id)


class TestRestartConfirmationRouting:
    def test_turn1_initial_restart_request(self):
        route, toolsets = simulate_gateway_dispatch("Reinicie o omniroute no Prosperfy.")
        assert route == "INFRA_ACTION"
        assert toolsets == ["restart_container"]

    def test_sim_with_pending_same_actor(self):
        _seed_pending(ACTOR_A)
        route, toolsets = simulate_gateway_dispatch("Sim", actor_id=ACTOR_A)
        assert route == "INFRA_ACTION"
        assert toolsets == ["restart_container"]

    def test_sim_without_pending(self):
        route, toolsets = simulate_gateway_dispatch("Sim", actor_id=ACTOR_A)
        assert route == "NORMAL"
        assert toolsets == []

    def test_cross_actor_confirmation_denied(self):
        _seed_pending(ACTOR_A)
        route, toolsets = simulate_gateway_dispatch("Sim", actor_id=ACTOR_B)
        assert route == "NORMAL"
        assert toolsets == []

    def test_confirmo_with_pending(self):
        _seed_pending(ACTOR_A)
        route, toolsets = simulate_gateway_dispatch("Confirmo", actor_id=ACTOR_A)
        assert route == "INFRA_ACTION"
        assert toolsets == ["restart_container"]

    def test_confirmo_without_pending(self):
        route, toolsets = simulate_gateway_dispatch("Confirmo", actor_id=ACTOR_A)
        assert route == "NORMAL"
        assert toolsets == []

    def test_sim_obrigado_without_pending_stays_normal(self):
        route, toolsets = simulate_gateway_dispatch("Sim, obrigado", actor_id=ACTOR_A)
        assert route == "NORMAL"
        assert toolsets == []


class TestOtherRoutesRegression:
    @pytest.mark.parametrize(
        "message,expected_route,expected_toolsets",
        [
            ("Agende todo dia às 9h um lembrete.", "CRON", ["cronjob"]),
            ("O que conversamos sobre o Hermes ontem?", "SESSION_SEARCH", ["session_search"]),
            ("Lembre que meu código é ORION-78.", "MEMORY", ["memory"]),
            ("Quais skills você tem?", "SKILLS", ["skills"]),
            ("Como estão os containers no Prosperfy?", "INFRA_READ", ["infra_read"]),
            ("Oi", "NORMAL", []),
        ],
    )
    def test_routes_unchanged(self, message, expected_route, expected_toolsets):
        route, toolsets = simulate_gateway_dispatch(message)
        assert route == expected_route
        assert toolsets == expected_toolsets


class TestPendingHelper:
    def test_has_pending_restart_read_only(self):
        assert rct.has_pending_restart_for_actor(ACTOR_A) is False
        _seed_pending(ACTOR_A)
        assert rct.has_pending_restart_for_actor(ACTOR_A) is True
        assert rct.has_pending_restart_for_actor(ACTOR_B) is False
        # Read-only: pending ainda presente
        assert rct.has_pending_restart_for_actor(ACTOR_A) is True

    def test_resolve_specialist_route_without_checker_is_normal(self):
        set_pending_restart_checker(None)
        _seed_pending(ACTOR_A)
        assert resolve_specialist_route("Sim", actor_id=ACTOR_A) == "NORMAL"
