#!/usr/bin/env python3
"""
ops/browser-worker/test_worker.py -- unit tests for worker.py pure logic.

stdlib-only (unittest), no network/subprocess/chrome required. Run:
  python3 ops/browser-worker/test_worker.py -v

Covers the fail-closed gates (doc 00 Sec.6.2/8, criterio FAIL_CLOSED) and the
SecretBroker reference-resolution contract (doc 00 Sec.6.1: never a value
without going through secret_ref, missing alias raises rather than
fabricating a value).
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import worker  # noqa: E402


class ScanBlockersTests(unittest.TestCase):
    def test_benign_text_no_blocker(self):
        self.assertIsNone(worker.scan_blockers("Welcome to our newsletter signup. Name, email."))

    def test_captcha_detected(self):
        self.assertEqual(worker.scan_blockers("Please complete the reCAPTCHA below"), "captcha")

    def test_mfa_detected(self):
        self.assertEqual(
            worker.scan_blockers("Enter the verification code we sent to your phone"), "mfa"
        )

    def test_payment_detected(self):
        self.assertEqual(worker.scan_blockers("Card number: ____  CVV: ___"), "payment")

    def test_destructive_detected(self):
        self.assertEqual(worker.scan_blockers("Are you sure you want to permanently delete your account?"), "destructive")

    def test_none_and_empty_safe(self):
        self.assertIsNone(worker.scan_blockers(None))
        self.assertIsNone(worker.scan_blockers(""))


class ResolveFieldsTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_secrets_dir = worker.SECRETS_DIR
        worker.SECRETS_DIR = self._tmpdir.name

    def tearDown(self):
        worker.SECRETS_DIR = self._orig_secrets_dir
        self._tmpdir.cleanup()

    def _write_secret(self, alias, value):
        path = os.path.join(worker.SECRETS_DIR, f"{alias}.env")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"SECRET_VALUE={value}\n")

    def test_literal_passthrough(self):
        resolved, used = worker.resolve_fields({"email": "test@example.com"})
        self.assertEqual(resolved, {"email": "test@example.com"})
        self.assertEqual(used, [])

    def test_secret_ref_resolves_and_tracks_alias_only(self):
        self._write_secret("signup-pw-01", "s3cr3t-token-value")
        resolved, used = worker.resolve_fields({"password": "secret_ref:signup-pw-01"})
        self.assertEqual(resolved["password"], "s3cr3t-token-value")
        self.assertEqual(used, ["signup-pw-01"])

    def test_missing_alias_raises_never_fabricates(self):
        with self.assertRaises(worker.SecretResolutionError):
            worker.resolve_fields({"password": "secret_ref:does-not-exist"})

    def test_mixed_fields(self):
        self._write_secret("tok-a", "value-a")
        resolved, used = worker.resolve_fields({
            "email": "a@b.com",
            "password": "secret_ref:tok-a",
        })
        self.assertEqual(resolved["email"], "a@b.com")
        self.assertEqual(resolved["password"], "value-a")
        self.assertEqual(used, ["tok-a"])


class StripTagsTests(unittest.TestCase):
    def test_removes_script_and_style(self):
        html = "<html><head><style>body{color:red}</style></head><body><script>evil()</script>Hello <b>World</b></body></html>"
        text = worker._strip_tags(html)
        self.assertNotIn("evil()", text)
        self.assertNotIn("color:red", text)
        self.assertIn("Hello", text)
        self.assertIn("World", text)

    def test_collapses_whitespace(self):
        html = "<p>a</p>\n\n<p>   b   </p>"
        text = worker._strip_tags(html)
        self.assertEqual(text, "a b")


class LooksLikeJsShellTests(unittest.TestCase):
    def test_short_text_is_shell(self):
        self.assertTrue(worker._looks_like_js_shell("hi", "<html><body>hi</body></html>"))

    def test_spa_root_marker_is_shell(self):
        long_but_empty = "x" * 600
        self.assertTrue(worker._looks_like_js_shell(long_but_empty, '<div id="root"></div>'))

    def test_normal_article_is_not_shell(self):
        long_text = "This is a real article. " * 40  # > 500 chars
        self.assertGreater(len(long_text), 500)
        self.assertFalse(worker._looks_like_js_shell(long_text, "<html><body>" + long_text + "</body></html>"))


class RunJobRoutingTests(unittest.TestCase):
    def test_unknown_action_fails_closed(self):
        result = worker.run_job({"action": "delete_everything"})
        self.assertFalse(result["success"])
        self.assertIn("unknown action", result["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
