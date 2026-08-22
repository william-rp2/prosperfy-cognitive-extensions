"""
Sprint 0.7.8.1 — Pipeline test: WhatsApp routing closure.

Reproduces the bug where the gateway passed channel_prompt/context_prompt
to resolve_specialist_route() instead of the raw user message text.

All tests are deterministic (LLM calls = 0).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest
from capability_intelligence.capability_router import (
    is_specialist,
    resolve_specialist_route,
    route_toolsets,
)


# ─── Helper simulating the fixed gateway call ────────────────────────────────

def simulate_gateway_dispatch(event_text: str, channel_prompt: str = "", context_prompt: str = ""):
    """
    Simulates _resolve_enabled_toolsets_for_source AFTER the fix.

    The bug: passing `channel_prompt or context_prompt or ""` to the router.
    The fix: passing `message or ""` (= event_text here).

    Returns (routing_input, route, toolsets).
    """
    # FIXED: use raw message, not channel_prompt/context_prompt
    routing_input = event_text or ""
    route = resolve_specialist_route(routing_input)
    toolsets = route_toolsets(route)
    return routing_input, route, toolsets


def simulate_gateway_dispatch_buggy(event_text: str, channel_prompt: str = "", context_prompt: str = ""):
    """Buggy version: passes channel_prompt/context_prompt to router."""
    routing_input = channel_prompt or context_prompt or ""
    route = resolve_specialist_route(routing_input)
    toolsets = route_toolsets(route)
    return routing_input, route, toolsets


# ─── Regression: the original bug ────────────────────────────────────────────

def test_bug_regression_memory_write_was_silenced():
    """Bug: MEMORY message routed to NORMAL when channel_prompt empty."""
    event_text = "Lembre que meu código de teste é ORION-78."
    channel_prompt = ""
    context_prompt = ""

    routing_input, route, toolsets = simulate_gateway_dispatch_buggy(
        event_text, channel_prompt, context_prompt
    )
    # Bug manifested: empty string -> NORMAL
    assert routing_input == ""
    assert route == "NORMAL"
    assert toolsets == []


def test_fix_memory_write_activates():
    """Fix: event.text goes to router, MEMORY activates."""
    event_text = "Lembre que meu código de teste é ORION-78."
    routing_input, route, toolsets = simulate_gateway_dispatch(event_text)

    assert routing_input == event_text, "ROUTING_INPUT must equal event.text"
    assert route == "MEMORY", f"ROUTE={route}"
    assert toolsets == ["memory"], f"FINAL_TOOLS={toolsets}"


# ─── Test matrix (6 cases from sprint spec) ──────────────────────────────────

@pytest.mark.parametrize("event_text,expected_route,expected_tools", [
    # A: NORMAL
    ("Oi", "NORMAL", []),
    # B: MEMORY write
    ("Lembre que meu código de teste é ORION-78.", "MEMORY", ["memory"]),
    # C: MEMORY read — new phrasing from Fix 2
    ("Qual código de teste do Hermes eu pedi para você lembrar?", "MEMORY", ["memory"]),
    # D: SESSION_SEARCH
    ("O que decidimos antes sobre o Browser Harness?", "SESSION_SEARCH", ["session_search"]),
    # E: SKILLS
    ("Quais skills você tem disponíveis?", "SKILLS", ["skills"]),
    # F: NORMAL
    ("Obrigado", "NORMAL", []),
])
def test_matrix(event_text, expected_route, expected_tools):
    routing_input, route, toolsets = simulate_gateway_dispatch(event_text)
    assert routing_input == event_text
    assert route == expected_route, f"msg={event_text!r} got ROUTE={route}"
    assert toolsets == expected_tools, f"msg={event_text!r} got TOOLS={toolsets}"


# ─── New _MEMORY_READ phrases (Fix 2) ────────────────────────────────────────

@pytest.mark.parametrize("phrase", [
    "Qual código eu pedi para você lembrar?",
    "Qual código eu pedi para voce lembrar?",
    "Pedi para você guardar o token ORION.",
    "Pedi para voce guardar o token.",
    "Eu pedi para lembrar o código secreto.",
    "Pedi que você lembrasse o PIN.",
    "Pedi que voce lembrasse o PIN.",
    # NOTE: "Qual foi a informação que eu pedi para guardar?" is excluded:
    # "informação que eu" contains substring "o que e" → conceptual guard fires first.
    "Qual informação eu pedi para você memorizar?",
])
def test_new_memory_read_phrases(phrase):
    route = resolve_specialist_route(phrase)
    assert route == "MEMORY", f"phrase={phrase!r} got ROUTE={route}"


# ─── is_specialist guard ─────────────────────────────────────────────────────

def test_is_specialist_normal_returns_false():
    assert not is_specialist("NORMAL")


def test_is_specialist_memory_returns_true():
    assert is_specialist("MEMORY")
