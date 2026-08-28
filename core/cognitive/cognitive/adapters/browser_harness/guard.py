"""
adapters/browser_harness/guard.py -- boundary guard for BrowserAdapter.

Mirrors adapters/prosperfy_skills/guard.py (ADR-V2-003 pattern): defense in
depth *at the adapter*, independent of whether upstream layers (registry
YAML, policy) are correctly wired. Only the tool names the Browser Worker
(ops/browser-worker/worker.py) actually understands may pass; only the
argument keys the worker's JOB SPEC defines may pass per tool.
"""

from __future__ import annotations

from typing import Any

_ALLOWED_TOOLS: dict[str, frozenset[str]] = {
    "browser_read_links": frozenset({"urls", "task", "session_id"}),
    "browser_fill_form": frozenset({"url", "action", "fields", "submit", "submit_selector", "session_id"}),
    "browser_create_account": frozenset({"url", "fields", "accept_standard_terms", "plan", "submit", "submit_selector", "session_id"}),
    "browser_doctor": frozenset(),
}


class BrowserToolError(ValueError):
    """Raised when a tool_name/arguments pair is not a recognized Browser Worker job."""


def guard_browser_tool(tool_name: str, arguments: dict[str, Any]) -> None:
    """
    Validates a browser.* tool call before it becomes a Browser Worker job.

    Never lets an unknown tool_name or an unexpected argument key through --
    those are exactly the shape of a prompt-injected or malformed request
    trying to smuggle something the worker's JOB SPEC does not define.
    """
    allowed_keys = _ALLOWED_TOOLS.get(tool_name)
    if allowed_keys is None:
        raise BrowserToolError(
            f"tool '{tool_name}' nao reconhecida pelo BrowserAdapter "
            f"(permitidas: {sorted(_ALLOWED_TOOLS)})"
        )
    extra = set(arguments.keys()) - allowed_keys
    if extra:
        raise BrowserToolError(
            f"argumento(s) inesperado(s) para '{tool_name}': {sorted(extra)}"
        )
