"""Contract tests for generic browser fallbacks (no live browser)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from browser_tool_generic_fallback import (  # noqa: E402
    _failure_suggests_missing_target,
    failure_suggests_locate_or_click_failure,
    is_discovery_click_ref,
    is_unknown_ref_error,
    resolve_authorized_upload_path,
    select_editable_in_dialog,
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


class TestClickFailureHeuristics(unittest.TestCase):
    def test_could_not_locate_triggers_locate_failure(self):
        self.assertTrue(
            failure_suggests_locate_or_click_failure("Could not locate element with role=checkbox name=Toggle Todo")
        )

    def test_unknown_ref_is_not_locate_failure(self):
        self.assertFalse(failure_suggests_locate_or_click_failure("Unknown ref: e999"))

    def test_unknown_ref_still_allows_fallback_gate(self):
        self.assertTrue(_failure_suggests_missing_target("Unknown ref: e999"))

    def test_success_not_missing(self):
        self.assertFalse(failure_suggests_locate_or_click_failure("clicked"))

    def test_is_unknown_ref_error(self):
        self.assertTrue(is_unknown_ref_error("Unknown ref: e12"))

    def test_discovery_click_ref_requires_hint(self):
        self.assertTrue(is_discovery_click_ref("@?", "Delete"))
        self.assertFalse(is_discovery_click_ref("@e5", "Delete"))
        self.assertFalse(is_discovery_click_ref("@?", ""))


class TestModalEditableSelection(unittest.TestCase):
    def _candidates_two_anonymous(self):
        return [
            {"type": "text", "labelText": "", "ariaLabel": "", "placeholder": "", "name": "", "id": ""},
            {"type": "text", "labelText": "", "ariaLabel": "", "placeholder": "", "name": "", "id": ""},
        ]

    def test_ambiguous_two_anonymous_without_hint(self):
        idx, err = select_editable_in_dialog(self._candidates_two_anonymous(), None, None)
        self.assertIsNone(idx)
        self.assertEqual(err, "AMBIGUOUS_EDITABLE")

    def test_single_anonymous_field_ok(self):
        one = [self._candidates_two_anonymous()[0]]
        idx, err = select_editable_in_dialog(one, None, None)
        self.assertEqual(idx, 0)
        self.assertIsNone(err)

    def test_hint_selects_unique_name_field(self):
        cands = [
            {"type": "text", "labelText": "Name", "ariaLabel": "", "placeholder": "", "name": "", "id": ""},
            {"type": "text", "labelText": "Email", "ariaLabel": "", "placeholder": "", "name": "", "id": ""},
        ]
        idx, err = select_editable_in_dialog(cands, "Name", None)
        self.assertEqual(idx, 0)
        self.assertIsNone(err)

    def test_excludes_global_search_outside_dialog_semantics(self):
        """Search-type fields are deprioritized; two text fields without hint stay ambiguous."""
        cands = [
            {"type": "search", "labelText": "", "ariaLabel": "", "placeholder": "Buscar", "role": "searchbox"},
            {"type": "text", "labelText": "Nome", "ariaLabel": "", "placeholder": ""},
        ]
        idx, err = select_editable_in_dialog(cands, "Nome", None)
        self.assertEqual(idx, 1)
        self.assertIsNone(err)

    def test_ambiguous_when_two_match_hint(self):
        cands = [
            {"type": "text", "labelText": "User name", "ariaLabel": "", "placeholder": ""},
            {"type": "text", "labelText": "Display name", "ariaLabel": "", "placeholder": ""},
        ]
        idx, err = select_editable_in_dialog(cands, "name", None)
        self.assertIsNone(idx)
        self.assertEqual(err, "AMBIGUOUS_EDITABLE")

    def test_active_dialog_two_plus_anonymous_must_fail_closed(self):
        idx, err = select_editable_in_dialog(self._candidates_two_anonymous(), "", None)
        self.assertEqual(err, "AMBIGUOUS_EDITABLE")


if __name__ == "__main__":
    unittest.main()
