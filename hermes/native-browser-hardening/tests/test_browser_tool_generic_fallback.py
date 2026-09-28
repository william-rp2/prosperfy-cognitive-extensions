"""Contract tests for generic browser fallbacks (no live browser)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Import from overlay path when run from repo root
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from browser_tool_generic_fallback import (  # noqa: E402
    _failure_suggests_missing_target,
    resolve_authorized_upload_path,
)


class TestUploadPathAuth(unittest.TestCase):
    def test_denies_traversal(self):
        p, err = resolve_authorized_upload_path("../../etc/passwd")
        self.assertIsNone(p)
        self.assertIn("traversal", err or "")

    def test_denies_arbitrary_directory(self):
        if not Path("/var/tmp").is_dir():
            self.skipTest("/var/tmp unavailable")
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "hermes_home"
            home.mkdir()
            outside = Path("/var/tmp") / f"hermes_upload_deny_{os.getpid()}.bin"
            outside.write_bytes(b"x")
            try:
                with patch("browser_tool_generic_fallback._hermes_home", return_value=home):
                    with patch.dict(os.environ, {"TMPDIR": str(home / "empty_tmp")}):
                        p, err = resolve_authorized_upload_path(str(outside))
                self.assertIsNone(p)
                self.assertIn("authorized", err or "")
            finally:
                outside.unlink(missing_ok=True)

    def test_denies_missing(self):
        with patch("browser_tool_generic_fallback._hermes_home", return_value=Path(tempfile.gettempdir())):
            p, err = resolve_authorized_upload_path("/nonexistent/file.bin")
        self.assertIsNone(p)
        self.assertIn("exist", err or "")

    def test_allows_file_under_home(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            f = home / "attachments" / "doc.pdf"
            f.parent.mkdir(parents=True)
            f.write_bytes(b"%PDF-1.4")
            with patch("browser_tool_generic_fallback._hermes_home", return_value=home):
                p, err = resolve_authorized_upload_path(str(f))
            self.assertIsNone(err)
            self.assertEqual(p, f.resolve())


class TestFailureHeuristics(unittest.TestCase):
    def test_detects_missing_element(self):
        self.assertTrue(_failure_suggests_missing_target("Element not found for @e3"))

    def test_normal_success_not_missing(self):
        self.assertFalse(_failure_suggests_missing_target("clicked"))


if __name__ == "__main__":
    unittest.main()
