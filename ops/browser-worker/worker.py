#!/usr/bin/env python3
"""
ops/browser-worker/worker.py -- Track BH: isolated Browser Worker.

Runs on a DEDICATED host (never the operator's personal Chrome — doc 00
Sec.5). One job per process invocation, isolated tmp workdir, hard timeout,
stdlib-only (no extra deps beyond what browser-harness itself needs).

Contract with the caller (cognitive.adapters.browser_harness.client.BrowserAdapter):
  - Input: one JSON object on stdin (see JOB SPEC below).
  - Output: exactly one JSON object on stdout (last line) — the result.
    Everything else the script prints goes to stderr (debug/log only).
  - Never prints/persists a resolved secret value. `fields` may contain
    "secret_ref:<alias>" strings; the raw value is read from a local 0600
    file and used ONLY inside the in-process browser-harness call — never
    echoed back, never logged (doc 00 Sec.6.1).
  - Fail-closed: MFA/CAPTCHA/payment/destructive signals on the page abort
    BEFORE any submit/click and return blocked_reason (doc 00 Sec.6.2/8).

JOB SPEC (stdin JSON):
  {
    "job_id": "uuid",                    # caller-assigned, used for the tmp workdir
    "correlation_id": "string",
    "action": "read_links|fill_form|create_account|doctor",
    "urls": ["https://..."],             # read_links
    "url": "https://...",                # fill_form / create_account
    "fields": {"name": "value or secret_ref:<alias>"},
    "submit": false,
    "accept_standard_terms": false,
    "plan": "free",                      # create_account: only 'free' ever proceeds
    "timeout_seconds": 90
  }

Isolation: each job gets its own /tmp/browser-jobs/<job_id>/ workdir (removed
at the end, success or failure) — no cross-job/cross-tenant state. All jobs
share ONE Chrome/CDP endpoint (BU_CDP_URL) on this host; the daemon itself
does not multiplex tenants, so the CALLER must not run concurrent jobs of
different tenants against this single-worker MVP (documented gap — see
Track BH report REMAINING_GAPS; a queue/lock is the natural next step).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

SECRETS_DIR = os.environ.get(
    "BROWSER_WORKER_SECRETS_DIR", os.path.expanduser("~/.hermes/secrets/browser")
)
BU_CDP_URL = os.environ.get("BU_CDP_URL", "http://127.0.0.1:9222")
BROWSER_HARNESS_BIN = os.environ.get("BROWSER_HARNESS_BIN", "browser-harness")
JOBS_ROOT = os.environ.get("BROWSER_WORKER_JOBS_ROOT", "/tmp/browser-jobs")
DEFAULT_TIMEOUT = 90
MAX_FETCH_BYTES = 400_000
MAX_TEXT_CHARS = 6_000

# ─── Fail-closed content scan (doc 00 Sec.6.2 / 8, criterio FAIL_CLOSED) ────
_BLOCK_PATTERNS: dict[str, list[str]] = {
    "captcha": [
        r"captcha", r"are you a human", r"verify you.?re human", r"hcaptcha",
        r"recaptcha", r"prove you.?re not a robot",
    ],
    "mfa": [
        r"two-factor", r"2fa\b", r"one-time code", r"one time passcode",
        r"authenticator app", r"enter the code we (sent|texted)",
        r"verification code", r"security code sent",
    ],
    "payment": [
        r"card number", r"\bcvv\b", r"\bcvc\b", r"credit card", r"debit card",
        r"billing address", r"expiration date", r"cardholder name",
        r"enter your card",
    ],
    "destructive": [
        r"delete (my |your )?account", r"permanently delete",
        r"deactivate (my |your )?account", r"cancel subscription",
        r"revoke access",
    ],
}


def scan_blockers(text: str | None) -> str | None:
    """Return the first blocker category found in page text, or None."""
    low = (text or "").lower()
    for reason, patterns in _BLOCK_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, low):
                return reason
    return None


# ─── SecretBroker reference resolution (never returned/logged) ─────────────

class SecretResolutionError(RuntimeError):
    pass


def _resolve_secret_ref(alias: str) -> str:
    path = os.path.join(SECRETS_DIR, f"{alias}.env")
    if not os.path.isfile(path):
        raise SecretResolutionError(f"secret_ref '{alias}' not found")
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("SECRET_VALUE="):
                return line.rstrip("\n").split("=", 1)[1]
    raise SecretResolutionError(f"secret_ref '{alias}' has no SECRET_VALUE")


def resolve_fields(fields: dict) -> tuple[dict, list[str]]:
    """Resolve 'secret_ref:<alias>' values. Returns (resolved, aliases_used).
    `resolved` lives only in local variables of this process — caller must
    never serialize it back."""
    resolved: dict = {}
    aliases_used: list[str] = []
    for key, value in (fields or {}).items():
        if isinstance(value, str) and value.startswith("secret_ref:"):
            alias = value.split(":", 1)[1]
            resolved[key] = _resolve_secret_ref(alias)
            aliases_used.append(alias)
        else:
            resolved[key] = value
    return resolved, aliases_used


# ─── browser-harness invocation ─────────────────────────────────────────────

def run_harness(py_code: str, timeout_seconds: float) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["BU_CDP_URL"] = BU_CDP_URL
    return subprocess.run(
        [BROWSER_HARNESS_BIN],
        input=py_code,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env=env,
    )


def _strip_tags(html: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


_SPA_SHELL_MARKERS = (
    'id="root">', "id='root'>", 'id="app">', "id='app'>", "enable javascript",
    "checking your browser", "just a moment", "cf-browser-verification",
)


def _looks_like_js_shell(body_text_stripped: str, raw_html_lower: str) -> bool:
    if len(body_text_stripped) < 500:
        return True
    return any(marker in raw_html_lower for marker in _SPA_SHELL_MARKERS)


def _fetch_plain(url: str) -> tuple[int | None, str | None, str | None]:
    """Plain HTTP GET, no browser. Returns (status, html, error)."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (compatible; ProsperfyBrowserHarnessWorker/1.0)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            body = resp.read(MAX_FETCH_BYTES).decode("utf-8", "replace")
            return resp.status, body, None
    except urllib.error.HTTPError as exc:
        return exc.code, None, f"http_error:{exc.code}"
    except Exception as exc:  # noqa: BLE001 -- worker boundary, must not crash the job
        return None, None, f"fetch_error:{type(exc).__name__}"


def _read_via_browser(url: str, timeout_seconds: float) -> dict:
    code = f"""
new_tab({url!r})
wait_for_load(timeout=20.0)
info = page_info()
title = js("document.title")
text = js("document.body.innerText")
print("===TITLE===")
print(title)
print("===TEXT===")
print(text[:{MAX_TEXT_CHARS}] if text else "")
"""
    proc = run_harness(code, timeout_seconds)
    if proc.returncode != 0:
        return {"error": f"browser_error: {proc.stderr.strip()[:300]}"}
    out = proc.stdout
    title = ""
    text = ""
    if "===TITLE===" in out and "===TEXT===" in out:
        title = out.split("===TITLE===", 1)[1].split("===TEXT===", 1)[0].strip()
        text = out.split("===TEXT===", 1)[1].strip()
    return {"title": title, "text": text[:MAX_TEXT_CHARS]}


def action_read_links(job: dict) -> dict:
    """Decision gate doc 00 Sec.4.2: plain fetch first; browser only when the
    page needs JS/interaction/looks bot-shielded."""
    pages = []
    for url in job.get("urls", []):
        entry = {"url": url, "fetched_via": None, "title": None, "text": None, "error": None}
        status, html, err = _fetch_plain(url)
        if html is not None and status and 200 <= status < 300:
            stripped = _strip_tags(html)
            if not _looks_like_js_shell(stripped, html.lower()):
                title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
                entry["fetched_via"] = "fetch"
                entry["title"] = _strip_tags(title_match.group(1)) if title_match else None
                entry["text"] = stripped[:MAX_TEXT_CHARS]
                pages.append(entry)
                continue
        # Fetch failed or looks like a JS-only/bot-shielded shell -> escalate.
        try:
            browser_result = _read_via_browser(url, job.get("timeout_seconds", DEFAULT_TIMEOUT))
        except subprocess.TimeoutExpired:
            entry["fetched_via"] = "browser"
            entry["error"] = "timeout"
            pages.append(entry)
            continue
        entry["fetched_via"] = "browser"
        entry["title"] = browser_result.get("title")
        entry["text"] = browser_result.get("text")
        entry["error"] = browser_result.get("error")
        pages.append(entry)
    return {"success": True, "pages": pages}


def action_doctor(job: dict) -> dict:
    proc = run_harness("print(page_info())\n", job.get("timeout_seconds", 30))
    return {
        "success": proc.returncode == 0,
        "chrome_reachable": proc.returncode == 0,
        "detail": (proc.stdout or proc.stderr).strip()[:500],
    }


def _fill_and_maybe_submit(job: dict, resolved_fields: dict, action_kind: str) -> dict:
    url = job["url"]
    submit = bool(job.get("submit", False))
    field_items = list(resolved_fields.items())

    fill_lines = []
    for selector, value in field_items:
        fill_lines.append(f"fill_input({selector!r}, {value!r})")
    fill_block = "\n".join(fill_lines) if fill_lines else "pass"

    submit_selector = job.get("submit_selector")

    code = f"""
new_tab({url!r})
wait_for_load(timeout=20.0)
pre_text = js("document.body.innerText") or ""
print("===PRESCAN===")
print(pre_text[:{MAX_TEXT_CHARS}])
{fill_block}
post_text = js("document.body.innerText") or ""
print("===POSTFILL===")
print(post_text[:{MAX_TEXT_CHARS}])
"""
    proc = run_harness(code, job.get("timeout_seconds", DEFAULT_TIMEOUT))
    if proc.returncode != 0:
        return {"success": False, "blocked_reason": None, "error": proc.stderr.strip()[:300]}

    out = proc.stdout
    pre_text = out.split("===PRESCAN===", 1)[1].split("===POSTFILL===", 1)[0].strip() \
        if "===PRESCAN===" in out else ""
    post_text = out.split("===POSTFILL===", 1)[1].strip() if "===POSTFILL===" in out else ""

    blocker = scan_blockers(pre_text) or scan_blockers(post_text)
    if blocker:
        return {"success": False, "submitted": False, "blocked_reason": blocker}

    if action_kind == "create_account":
        if job.get("plan") != "free":
            return {"success": False, "submitted": False, "blocked_reason": "payment"}
        if submit and not job.get("accept_standard_terms"):
            return {"success": False, "submitted": False, "blocked_reason": "terms_atypical"}

    if not submit or not submit_selector:
        return {"success": True, "submitted": False, "blocked_reason": None}

    submit_code = f"""
result = js("(function(){{var el=document.querySelector({submit_selector!r}); if(!el) return 'missing'; el.click(); return 'clicked';}})()")
print("===SUBMIT===")
print(result)
wait(1.0)
final_text = js("document.body.innerText") or ""
print("===FINAL===")
print(final_text[:{MAX_TEXT_CHARS}])
"""
    proc2 = run_harness(submit_code, job.get("timeout_seconds", DEFAULT_TIMEOUT))
    if proc2.returncode != 0:
        return {"success": False, "submitted": False, "error": proc2.stderr.strip()[:300]}
    out2 = proc2.stdout
    final_text = out2.split("===FINAL===", 1)[1].strip() if "===FINAL===" in out2 else ""
    post_submit_blocker = scan_blockers(final_text)
    return {
        "success": "clicked" in out2,
        "submitted": "clicked" in out2 and not post_submit_blocker,
        "blocked_reason": post_submit_blocker,
    }


def run_job(job: dict) -> dict:
    action = job.get("action")
    if action == "read_links":
        return action_read_links(job)
    if action == "doctor":
        return action_doctor(job)
    if action in ("fill_form", "create_account"):
        resolved, aliases_used = resolve_fields(job.get("fields", {}))
        result = _fill_and_maybe_submit(job, resolved, action)
        result["secret_aliases_used"] = aliases_used  # aliases only, never values
        return result
    return {"success": False, "error": f"unknown action '{action}'"}


def main() -> int:
    raw = sys.stdin.read()
    try:
        job = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"success": False, "error": f"invalid job json: {exc}"}))
        return 1

    job_id = job.get("job_id") or f"job-{int(time.time() * 1000)}"
    workdir = os.path.join(JOBS_ROOT, job_id)
    os.makedirs(workdir, exist_ok=True)
    start = time.monotonic()
    try:
        result = run_job(job)
    except SecretResolutionError as exc:
        result = {"success": False, "error": f"secret_error: {exc}"}
    except subprocess.TimeoutExpired:
        result = {"success": False, "error": "timeout"}
    except Exception as exc:  # noqa: BLE001 -- worker boundary, never leak raw traceback
        result = {"success": False, "error": f"worker_error: {type(exc).__name__}"}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    result["job_id"] = job_id
    result["correlation_id"] = job.get("correlation_id")
    result["duration_ms"] = int((time.monotonic() - start) * 1000)
    print(json.dumps(result))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
