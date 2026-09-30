"""Tests for apply_runtime_patch validation (no live Hermes install required)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from apply_runtime_patch import (  # noqa: E402
    MARKER,
    NEW_UPLOAD,
    verify_patched_browser_tool,
)


class TestVerifyPatchedBrowserTool(unittest.TestCase):
    def test_rejects_incomplete_patch(self):
        with self.assertRaises(ValueError):
            verify_patched_browser_tool("def browser_click(): pass")

    def test_accepts_minimal_contract_surface(self):
        text = (
            'def browser_click(ref: str, task_id: Optional[str] = None, target_hint: Optional[str] = None):\n'
            'def browser_type(ref: str, text: str, task_id: Optional[str] = None, field_hint: Optional[str] = None):\n'
            + NEW_UPLOAD
            + '\n'
            'def browser_scroll(direction: str, task_id: Optional[str] = None) -> str:\n'
            '    pass\n'
            '"target_hint"\n'
            '"field_hint"\n'
            '("browser_upload",\n'
            + MARKER
            + "\n"
        )
        verify_patched_browser_tool(text)


if __name__ == "__main__":
    unittest.main()
