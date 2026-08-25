#!/usr/bin/env python3
"""verify_memory_on_demand.py — Sprint 0.7.8.4 memory-only gate."""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERMES = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes")))
AGENT = Path(os.getenv("HERMES_AGENT_DIR", str(HERMES / "hermes-clean")))
if not AGENT.exists():
    AGENT = HERMES / "hermes-agent"

PATCH = Path(__file__).resolve().parent / "memory_on_demand.patch"
MARKER = "prosperfy-memory-snapshot-0784"
FORBIDDEN = (
    "resolve_specialist_route",
    "prosperfy_slim_boundary",
    "_maybe_execute_memory_write",
    "resolve_slim_turn",
)


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"{name}={'PASS' if ok else 'FAIL'} {detail}")
    return ok


def main() -> int:
    ok = True
    patch_text = PATCH.read_text(encoding="utf-8", errors="replace")
    ok &= check("PATCH_MEMORY_ONLY", not any(f in patch_text for f in FORBIDDEN))
    ok &= check("PATCH_HAS_SNAPSHOT_FLAG", "skip_memory_snapshot_in_prompt" in patch_text)
    ok &= check(
        "PATCH_NO_RESOLVE_TOOLSETS_TOUCH",
        "_resolve_enabled_toolsets_for_source" not in patch_text,
    )

    run_py = AGENT / "gateway" / "run.py"
    if run_py.exists():
        rt = run_py.read_text(encoding="utf-8", errors="replace")
        ok &= check("RUNTIME_MARKER", MARKER in rt or "skip_memory_snapshot_in_prompt=True" in rt)
        ok &= check("RUNTIME_NO_SLIM_BOUNDARY", "prosperfy_slim_boundary" not in rt)
    else:
        ok &= check("RUNTIME_CHECK", False, f"missing {run_py}")

    print(f"MEMORY_ON_DEMAND_VERIFY={'PASS' if ok else 'FAIL_CLOSED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
