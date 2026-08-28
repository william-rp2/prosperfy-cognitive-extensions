"""
tests/test_capability_router_browser.py -- Track BH BROWSER route contract.

Kept as its own file (not appended to test_capability_router.py) since
capability_router.py is edited by 4 parallel tracks (doc 00 Sec.3 "Regra de
conflito") -- isolating the test the same way keeps every track's diff
independent and avoids a second collision point on the shared test file.

Re-runs every case from test_capability_router.py (imported, not copied) to
prove BROWSER's addition changes nothing about the other routes, then adds
BROWSER-specific cases.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from capability_intelligence.capability_router import (  # noqa: E402
    resolve_specialist_route,
    route_toolsets,
)


def test_normal_stays_empty_toolset():
    assert route_toolsets("NORMAL") == []


def test_browser_toolset_is_isolated_not_in_normal():
    assert route_toolsets("BROWSER") == ["browser_harness"]
    assert "browser_harness" not in route_toolsets("NORMAL")


def test_login_intent_routes_browser():
    assert resolve_specialist_route("Faça login nesse site para mim.") == "BROWSER"


def test_form_fill_intent_routes_browser():
    assert resolve_specialist_route("Preencha o formulário de cadastro nesse site.") == "BROWSER"


def test_signup_intent_routes_browser():
    assert resolve_specialist_route("Crie uma conta em https://exemplo.com para nós.") == "BROWSER"


def test_bare_url_without_interaction_verb_stays_normal():
    """Link solto sem verbo de interação -> NORMAL (fetch resolve fora do
    specialist route, doc 00 Sec.4.2 decision gate)."""
    assert resolve_specialist_route("https://exemplo.com/artigo") == "NORMAL"


def test_read_and_summarize_without_interaction_stays_normal():
    assert resolve_specialist_route("Leia e resuma esse artigo: https://exemplo.com/post") == "NORMAL"


def test_conceptual_question_about_browser_stays_normal():
    """Guard conceitual roda antes do check de BROWSER -- pergunta sobre o
    conceito nunca vira roteamento de specialist."""
    assert resolve_specialist_route("O que é um navegador?") == "NORMAL"


def test_visit_url_with_nav_verb_routes_browser():
    assert resolve_specialist_route("Acesse esse site https://exemplo.com e faça o cadastro.") == "BROWSER"


def test_infra_restart_still_routes_infra_action_not_browser():
    """BROWSER foi inserido no fim da cadeia de precedência -- não deve
    capturar nada que já era INFRA_ACTION."""
    assert resolve_specialist_route("Reinicie o omniroute no Prosperfy.") == "INFRA_ACTION"
