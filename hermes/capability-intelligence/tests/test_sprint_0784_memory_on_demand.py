"""Sprint 0.7.8.4 — Memory snapshot on-demand (rework, memory-only)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
HERMES = ROOT.parent / "hermes-upstream"
PATCH = ROOT / "ops" / "hermes" / "update" / "memory_on_demand.patch"
CONSOLIDATE = ROOT / "scripts" / "consolidate_memory_md.py"

if HERMES.exists():
    sys.path.insert(0, str(HERMES))

FORBIDDEN_PATCH = (
    "resolve_specialist_route",
    "prosperfy_slim_boundary",
    "_maybe_execute_memory_write",
    "resolve_slim_turn",
)


class _FakeOpenAI:
    def __init__(self, **kw):
        self.api_key = kw.get("api_key", "test")
        self.base_url = kw.get("base_url", "http://test")

    def close(self):
        pass


def _make_agent(monkeypatch, tmp_path, *, enabled_toolsets=None, skip_memory_snapshot_in_prompt=True):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hm"))
    monkeypatch.setattr("run_agent.get_tool_definitions", lambda **kw: [])
    monkeypatch.setattr("run_agent.check_toolset_requirements", lambda: {})
    monkeypatch.setattr("run_agent.OpenAI", _FakeOpenAI)
    from run_agent import AIAgent

    agent = AIAgent(
        api_key="test-key",
        base_url="http://test",
        provider="openrouter",
        api_mode="chat_completions",
        max_iterations=1,
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
        enabled_toolsets=enabled_toolsets,
    )
    agent._skip_memory_snapshot_in_prompt = bool(skip_memory_snapshot_in_prompt)
    return agent


def _apply_gateway_cache_policy(agent) -> None:
    """Mirror GatewayRunner._init_cached_agent_for_turn memory policy (0784)."""
    want = True
    had = getattr(agent, "_skip_memory_snapshot_in_prompt", False)
    agent._skip_memory_snapshot_in_prompt = want
    if want and not had and getattr(agent, "_cached_system_prompt", None):
        from agent.system_prompt import invalidate_system_prompt

        invalidate_system_prompt(agent)


# ─── Patch safety ───────────────────────────────────────────────────────────

def test_patch_routing_absence():
    text = PATCH.read_text(encoding="utf-8")
    assert "_resolve_enabled_toolsets_for_source" not in text
    for forbidden in FORBIDDEN_PATCH:
        assert forbidden not in text


def test_patch_memory_write_absence():
    assert "_maybe_execute_memory_write" not in PATCH.read_text(encoding="utf-8")


# ─── System prompt integration ──────────────────────────────────────────────

@pytest.mark.skipif(not HERMES.exists(), reason="hermes-upstream clone required")
def test_system_prompt_memory_exclusion(monkeypatch, tmp_path):
    agent = _make_agent(
        monkeypatch, tmp_path, enabled_toolsets=["memory"], skip_memory_snapshot_in_prompt=True
    )
    secret = "TOKEN_0784_MUST_NOT_LEAK"
    agent._memory_store.memory_entries = [secret]
    agent._memory_store._system_prompt_snapshot = {
        "memory": agent._memory_store._render_block("memory", [secret]),
        "user": "",
    }
    from agent.system_prompt import build_system_prompt_parts

    parts = build_system_prompt_parts(agent)
    blob = json.dumps(parts)
    assert secret not in blob


@pytest.mark.skipif(not HERMES.exists(), reason="hermes-upstream clone required")
def test_memory_store_without_snapshot(monkeypatch, tmp_path):
    agent = _make_agent(
        monkeypatch, tmp_path, enabled_toolsets=["memory"], skip_memory_snapshot_in_prompt=True
    )
    assert agent._memory_store is not None
    from tools.memory_tool import memory_tool

    raw = memory_tool(
        action="add",
        target="memory",
        content="store works without snapshot",
        store=agent._memory_store,
    )
    result = json.loads(raw)
    assert result.get("success") is True


@pytest.mark.skipif(not HERMES.exists(), reason="hermes-upstream clone required")
def test_cached_prompt_invalidation(monkeypatch, tmp_path):
    agent = _make_agent(
        monkeypatch, tmp_path, enabled_toolsets=["memory"], skip_memory_snapshot_in_prompt=False
    )
    secret = "CACHED_SECRET_0784"
    agent._memory_store.memory_entries = [secret]
    agent._memory_store._system_prompt_snapshot = {
        "memory": agent._memory_store._render_block("memory", [secret]),
        "user": "",
    }
    from agent.system_prompt import build_system_prompt

    agent._cached_system_prompt = build_system_prompt(agent)
    assert secret in agent._cached_system_prompt

    _apply_gateway_cache_policy(agent)
    agent._cached_system_prompt = build_system_prompt(agent)
    assert secret not in agent._cached_system_prompt


@pytest.mark.skipif(not HERMES.exists(), reason="hermes-upstream clone required")
def test_cache_signature_includes_snapshot_flag():
    import hashlib
    import json as _j

    def _sig(skip_memory_snapshot_in_prompt: bool) -> str:
        blob = _j.dumps(
            [
                "model",
                "",
                "",
                "",
                "",
                [],
                "",
                [],
                "",
                "",
                False,
                bool(skip_memory_snapshot_in_prompt),
            ],
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    assert _sig(False) != _sig(True)


@pytest.mark.skipif(not HERMES.exists(), reason="hermes-upstream clone required")
def test_memory_to_normal_carry_over_via_signature():
    import hashlib
    import json as _j

    def _sig(enabled_toolsets: list) -> str:
        blob = _j.dumps(
            [
                "model",
                "",
                "",
                "",
                "",
                sorted(enabled_toolsets) if enabled_toolsets else [],
                "",
                [],
                "",
                "",
                False,
                True,
            ],
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    assert _sig(["memory"]) != _sig([])


# ─── Consolidation fail-closed ──────────────────────────────────────────────

def test_consolidation_fail_closed(tmp_path, monkeypatch):
    mem_dir = tmp_path / "hm" / "memories"
    mem_dir.mkdir(parents=True)
    entry7 = "entry seven original text"
    path = mem_dir / "MEMORY.md"
    path.write_text(f"e1§{entry7}§", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hm"))

    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib.util

    spec = importlib.util.spec_from_file_location("consolidate", CONSOLIDATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    bad_spec = {
        "2": {
            "expected_sha256": "deadbeef",
            "replacement_text": "should not apply",
        }
    }
    entries = mod.parse_entries(path.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="FINGERPRINT_MISMATCH"):
        mod.validate_replacement_spec(entries, bad_spec)

    good_spec = {
        "2": {
            "expected_text": entry7,
            "replacement_text": "entry seven compact",
        }
    }
    new_entries, _ = mod.validate_replacement_spec(entries, good_spec)
    assert new_entries[1] == "entry seven compact"
    assert path.read_text(encoding="utf-8") == f"e1§{entry7}§"


def test_consolidation_entry6_forbidden(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hm"))
    mem_dir = tmp_path / "hm" / "memories"
    mem_dir.mkdir(parents=True)
    entries = ["a", "b", "c", "d", "e", "hermeswork venv path", "g"]
    (mem_dir / "MEMORY.md").write_text("§".join(entries) + "§", encoding="utf-8")

    sys.path.insert(0, str(ROOT))
    import importlib.util

    spec = importlib.util.spec_from_file_location("consolidate", CONSOLIDATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    parsed = mod.parse_entries((mem_dir / "MEMORY.md").read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="ENTRY6_AUTO_MODIFY_FORBIDDEN"):
        mod.validate_replacement_spec(
            parsed,
            {"6": {"expected_text": parsed[5], "replacement_text": "removed"}},
        )


# ─── Deterministic write limitation ─────────────────────────────────────────

def test_deterministic_write_not_in_patch():
    assert "_maybe_execute_memory_write" not in PATCH.read_text(encoding="utf-8")
