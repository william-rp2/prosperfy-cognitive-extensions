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
    select_interactive_click_target,
    select_plausible_dropzone,
    try_dropzone_reveal_file_input,
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

    def test_allows_file_under_attachments_root(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            f = home / "attachments" / "doc.pdf"
            f.parent.mkdir(parents=True)
            f.write_bytes(b"%PDF-1.4")
            with patch("browser_tool_generic_fallback._hermes_home", return_value=home):
                p, err = resolve_authorized_upload_path(str(f))
            self.assertIsNone(err)
            self.assertEqual(p, f.resolve())

    def test_allows_profile_scoped_attachments(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            f = home / "profiles" / "qa" / "attachments" / "doc.pdf"
            f.parent.mkdir(parents=True)
            f.write_bytes(b"ok")
            with patch("browser_tool_generic_fallback._hermes_home", return_value=home):
                p, err = resolve_authorized_upload_path(str(f))
            self.assertIsNone(err)
            self.assertEqual(p, f.resolve())

    def test_denies_hermes_env_under_home(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            secret = home / ".env"
            secret.write_text("TOKEN=secret\n", encoding="utf-8")
            with patch("browser_tool_generic_fallback._hermes_home", return_value=home):
                p, err = resolve_authorized_upload_path(str(secret))
            self.assertIsNone(p)
            self.assertIn("authorized", err or "")

    def test_denies_arbitrary_tmp_file(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "hermes_home"
            home.mkdir()
            tmp_file = Path(tempfile.gettempdir()) / f"hermes_upload_tmp_{os.getpid()}.bin"
            tmp_file.write_bytes(b"x")
            try:
                with patch("browser_tool_generic_fallback._hermes_home", return_value=home):
                    with patch.dict(os.environ, {"TMPDIR": tempfile.gettempdir()}, clear=False):
                        p, err = resolve_authorized_upload_path(str(tmp_file))
                self.assertIsNone(p)
                self.assertIn("authorized", err or "")
            finally:
                tmp_file.unlink(missing_ok=True)

    def test_allows_browser_uploads_root(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            f = home / "browser_uploads" / "pic.png"
            f.parent.mkdir(parents=True)
            f.write_bytes(b"\x89PNG")
            with patch("browser_tool_generic_fallback._hermes_home", return_value=home):
                p, err = resolve_authorized_upload_path(str(f))
            self.assertIsNone(err)
            self.assertEqual(p, f.resolve())

    def test_denies_profile_cache_without_explicit_config(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            f = home / "profiles" / "qa" / "cache" / "screenshot.png"
            f.parent.mkdir(parents=True)
            f.write_bytes(b"x")
            with patch("browser_tool_generic_fallback._hermes_home", return_value=home):
                with patch.dict(os.environ, {}, clear=True):
                    p, err = resolve_authorized_upload_path(str(f))
            self.assertIsNone(p)
            self.assertIn("authorized", err or "")

    def test_denies_profile_files_without_explicit_config(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            f = home / "profiles" / "qa" / "files" / "arquivo.txt"
            f.parent.mkdir(parents=True)
            f.write_text("data", encoding="utf-8")
            with patch("browser_tool_generic_fallback._hermes_home", return_value=home):
                with patch.dict(os.environ, {}, clear=True):
                    p, err = resolve_authorized_upload_path(str(f))
            self.assertIsNone(p)
            self.assertIn("authorized", err or "")

    def test_allows_explicit_hermes_browser_upload_allowed_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "hermes_home"
            home.mkdir()
            custom = Path(td) / "legacy_uploads"
            custom.mkdir()
            f = custom / "allowed.bin"
            f.write_bytes(b"ok")
            env_key = "HERMES_BROWSER_UPLOAD_ALLOWED_DIRS"
            with patch("browser_tool_generic_fallback._hermes_home", return_value=home):
                with patch.dict(os.environ, {env_key: str(custom)}, clear=True):
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


class TestInteractiveClickSelection(unittest.TestCase):
    def _btn(self, **kw):
        base = {
            "selector": "button:nth-of-type(1)",
            "tag": "BUTTON",
            "text": "Delete",
            "ariaLabel": "",
            "title": "",
        }
        base.update(kw)
        return base

    def test_ambiguous_two_equivalent_delete_buttons(self):
        idx, err = select_interactive_click_target(
            [self._btn(text="Delete"), self._btn(text="Delete", selector="button:nth-of-type(2)")],
            "Delete",
        )
        self.assertIsNone(idx)
        self.assertEqual(err, "AMBIGUOUS_INTERACTIVE")

    def test_unique_match(self):
        idx, err = select_interactive_click_target(
            [self._btn(text="Cancel"), self._btn(text="Produto/Serviço")],
            "Produto/Serviço",
        )
        self.assertIsNone(err)
        self.assertEqual(idx, 1)


class TestLazyDropzoneSelection(unittest.TestCase):
    def _zone(self, **kw):
        base = {
            "tag": "DIV",
            "role": "",
            "className": "upload-panel dropzone",
            "text": "Arraste arquivos ou clique para enviar",
            "ariaLabel": "",
            "title": "",
            "hasOnDrop": True,
            "containsFileInputPlaceholder": False,
            "area": 12000,
            "selector": "div.upload-panel",
        }
        base.update(kw)
        return base

    def test_requires_target_hint(self):
        idx, err = select_plausible_dropzone([self._zone()], None)
        self.assertIsNone(idx)
        self.assertEqual(err, "TARGET_HINT_REQUIRED")

    def test_picks_hint_matching_dropzone(self):
        zones = [
            self._zone(text="Outra área", className="panel"),
            self._zone(text="Anexar documento de QA", className="file-drop"),
        ]
        idx, err = select_plausible_dropzone(zones, "Anexar documento")
        self.assertIsNone(err)
        self.assertEqual(idx, 1)

    def test_fail_closed_without_plausible_match(self):
        idx, err = select_plausible_dropzone(
            [self._zone(text="Salvar", className="btn-primary", hasOnDrop=False, area=900)],
            "Anexar",
        )
        self.assertIsNone(idx)
        self.assertEqual(err, "NO_PLAUSIBLE_DROPZONE")

    def test_ambiguous_two_equal_matches(self):
        z = self._zone(text="Enviar arquivo QA", className="upload-zone")
        idx, err = select_plausible_dropzone([z, dict(z)], "Enviar arquivo QA")
        self.assertIsNone(idx)
        self.assertEqual(err, "AMBIGUOUS_DROPZONE")

    @patch("browser_tool_generic_fallback._eval_json")
    @patch("browser_tool_generic_fallback.time.sleep", return_value=None)
    def test_reveal_polls_until_file_input_appears(self, _sleep, eval_json):
        zone_list = {
            "ok": True,
            "candidates": [
                {
                    "selector": "div.drop",
                    "tag": "DIV",
                    "role": "",
                    "className": "dropzone upload",
                    "text": "Anexar arquivo de teste",
                    "ariaLabel": "",
                    "title": "",
                    "hasOnDrop": True,
                    "containsFileInputPlaceholder": False,
                    "area": 8000,
                }
            ],
        }
        eval_json.side_effect = [
            (0, None),  # initial count
            (zone_list, None),  # list candidates
            ({"ok": True, "tag": "DIV"}, None),  # click
            (0, None),  # poll 1
            (1, None),  # poll 2
        ]
        out = try_dropzone_reveal_file_input("t1", "Anexar arquivo")
        self.assertTrue(out.get("success"))
        self.assertEqual(out.get("file_input_after_interaction"), 1)
        self.assertTrue(out.get("dropzone_interaction_performed"))


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
