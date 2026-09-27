#!/usr/bin/env python3
"""
ops/browser-worker/worker.py -- Track BH: isolated Browser Worker.

Runs on a DEDICATED host (never the operator's personal Chrome -- doc 00
Sec.5). One job per process invocation, isolated tmp workdir, hard timeout,
stdlib-only (no extra deps beyond what browser-harness itself needs).

Contract with the caller (cognitive.adapters.browser_harness.client.BrowserAdapter):
  - Input: one JSON object on stdin (see JOB SPEC below).
  - Output: exactly one JSON object on stdout (last line) -- the result.
    Everything else the script prints goes to stderr (debug/log only).
  - Never prints/persists a resolved secret value. `fields` may contain
    "secret_ref:<alias>" strings; the raw value is read from a local 0600
    file and used ONLY inside the in-process browser-harness call -- never
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
at the end, success or failure) -- no cross-job/cross-tenant state. All jobs
share ONE Chrome/CDP endpoint (BU_CDP_URL) on this host; the daemon itself
does not multiplex tenants, so the CALLER must not run concurrent jobs of
different tenants against this single-worker MVP (documented gap -- see
Track BH report REMAINING_GAPS; a queue/lock is the natural next step).
"""

from __future__ import annotations

import base64, json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SECRETS_DIR = os.environ.get(
    "BROWSER_WORKER_SECRETS_DIR", os.path.expanduser("~/.hermes/secrets/browser")
)
BU_CDP_URL = os.environ.get("BU_CDP_URL", "http://127.0.0.1:9222")
ALLOWED_QA_HOSTS = {
    "homologacao.prospersend.com.br",
    "api-homologacao.prospersend.com.br",
}
BROWSER_HARNESS_BIN = os.environ.get("BROWSER_HARNESS_BIN", "browser-harness")
JOBS_ROOT = os.environ.get("BROWSER_WORKER_JOBS_ROOT", "/tmp/browser-jobs")
DEFAULT_TIMEOUT = 90
MAX_FETCH_BYTES = 400_000
MAX_TEXT_CHARS = 6_000
BRIDGE_ENV_FILE = os.environ.get(
    "BROWSER_QA_BRIDGE_ENV",
    "/root/.hermes/browser-qa-bridge.env",
)


def _bridge_config() -> tuple[str, str]:
    cfg: dict[str, str] = {}
    try:
        with open(BRIDGE_ENV_FILE, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    except OSError:
        pass
    base = cfg.get("BROWSER_QA_BRIDGE_URL", "").rstrip("/")
    if not base:
        host = cfg.get("BROWSER_QA_BRIDGE_HOST", "").strip()
        port = cfg.get("BROWSER_QA_BRIDGE_PORT", "").strip()
        if host and port:
            base = "http://" + host + ":" + port
    return base, cfg.get("BROWSER_QA_BRIDGE_TOKEN", "")


def _bridge_post(path: str, payload: dict, timeout: float = 15.0) -> dict:
    base, token = _bridge_config()
    if not base or not token:
        raise SecretResolutionError("qa bridge not configured")
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        raise SecretResolutionError(f"qa bridge http {exc.code}") from None
    except Exception as exc:
        raise SecretResolutionError(f"qa bridge transport {type(exc).__name__}") from None
    if not isinstance(data, dict) or data.get("status") != "ok":
        raise SecretResolutionError("qa bridge rejected request")
    return data


def _redeem_claim(claim_token: str, materialize_id: str) -> str:
    data = _bridge_post(
        "/redeem",
        {"claim_token": claim_token, "materialize_id": materialize_id},
        timeout=15.0,
    )
    value = data.get("value")
    if not isinstance(value, str) or not value:
        raise SecretResolutionError("claim contained no value")
    return value


def _upload_evidence(path: str, job_id: str, name: str = "screenshot.png") -> dict:
    with open(path, "rb") as fh:
        blob = fh.read()
    return _bridge_post(
        "/evidence",
        {
            "job_id": job_id,
            "name": name,
            "mime_type": "image/png",
            "data_b64": base64.b64encode(blob).decode("ascii"),
        },
        timeout=30.0,
    )

# --- Fail-closed content scan (doc 00 Sec.6.2 / 8, criterio FAIL_CLOSED) ----
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


# --- SecretBroker reference resolution (never returned/logged) -------------

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
    """Resolve sensitive field references only inside the dedicated worker.

    Supports the legacy local secret_ref path and the preferred one-time
    ProsperfySkill claim envelope. Plaintext is never returned.
    """
    resolved: dict = {}
    aliases_used: list[str] = []
    for key, value in (fields or {}).items():
        if isinstance(value, str) and value.startswith("secret_ref:"):
            alias = value.split(":", 1)[1]
            resolved[key] = _resolve_secret_ref(alias)
            aliases_used.append(alias)
        elif isinstance(value, dict) and value.get("harness_claim_token"):
            mid = str(value.get("materialize_id") or "")
            resolved[key] = _redeem_claim(str(value["harness_claim_token"]), mid)
            aliases_used.append("claim:" + (mid or "one-time"))
        else:
            resolved[key] = value
    return resolved, aliases_used


# --- browser-harness invocation ---------------------------------------------

def run_harness(py_code: str, timeout_seconds: float) -> subprocess.CompletedProcess:
    """Run Browser Harness with one automatic retry for transient IPC timeouts."""
    env = dict(os.environ)
    env["BU_CDP_URL"] = BU_CDP_URL
    widened = []
    for line in py_code.splitlines(True):
        widened.append(line)
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        if stripped.startswith("wait_for_load(timeout=20.0)") or stripped.startswith("ensure_real_tab()"):
            widened.append(indent + "try:\n")
            widened.append(indent + "    cdp('Emulation.setDeviceMetricsOverride', width=1440, height=900, deviceScaleFactor=1, mobile=False)\n")
            widened.append(indent + "except Exception:\n")
            widened.append(indent + "    pass\n")
    py_code = "".join(widened)
    last = None
    for attempt in range(2):
        try:
            proc = subprocess.run(
                [BROWSER_HARNESS_BIN],
                input=py_code,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired:
            if attempt == 0:
                time.sleep(0.6)
                continue
            raise
        last = proc
        err = (proc.stderr or "").lower()
        transient = proc.returncode != 0 and (
            "timeouterror" in err
            or "timed out" in err
            or "ipc" in err
            or "connection reset" in err
            or "broken pipe" in err
        )
        if transient and attempt == 0:
            time.sleep(0.6)
            continue
        return proc
    return last


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
    """Fill in phase 1, submit in phase 2 on the exact same tab.

    ProsperSend/React only navigates reliably when the framework has finished
    processing the real key events before the submit event. A process boundary
    provides that flush while the Chrome tab itself persists through CDP.
    """
    url = job["url"]
    submit = bool(job.get("submit", False))
    submit_selector = str(job.get("submit_selector") or "").strip()

    if action_kind == "create_account":
        if job.get("plan") != "free":
            return {"success": False, "submitted": False, "blocked_reason": "payment"}
        if submit and not job.get("accept_standard_terms"):
            return {"success": False, "submitted": False, "blocked_reason": "terms_atypical"}

    field_items = list(resolved_fields.items())
    fill_lines = [f"fill_input({selector!r}, {value!r})" for selector, value in field_items]
    fill_block = "\n".join(fill_lines) if fill_lines else "pass"

    fresh_login = (
        str(url).startswith("https://homologacao.prospersend.com.br/login")
        or str(url).startswith("https://homologacao.prospersend.com.br/login?")
    )
    phase1 = f"""
new_tab({url!r})
wait_for_load(timeout=20.0)
wait_for_network_idle(timeout=12.0, idle_ms=1200)
wait(1.0)
if {fresh_login!r}:
    current_url = js("location.href") or ""
    email_present = bool(js("!!document.querySelector('#email')"))
    if True:
        try:
            cdp(
                "Storage.clearDataForOrigin",
                origin="https://homologacao.prospersend.com.br",
                storageTypes="cookies,local_storage,session_storage,indexeddb,cache_storage,service_workers",
            )
        except Exception:
            pass
        try:
            cdp(
                "Storage.clearDataForOrigin",
                origin="https://homologacao.prospersend.com.br",
                storageTypes="all",
            )
        except Exception:
            try:
                js("localStorage.clear(); sessionStorage.clear();")
            except Exception:
                pass
        new_tab({url!r})
        wait_for_load(timeout=20.0)
        wait_for_network_idle(timeout=12.0, idle_ms=1200)
        wait(1.0)
print("===TARGET===")
print(current_tab().get("targetId") or current_tab().get("target_id") or "")
pre_text = js("document.body.innerText") or ""
print("===PRESCAN===")
print(pre_text[:{MAX_TEXT_CHARS}])
{fill_block}
wait(1.0)
post_text = js("document.body.innerText") or ""
print("===POSTFILL===")
print(post_text[:{MAX_TEXT_CHARS}])
"""
    proc1 = run_harness(phase1, job.get("timeout_seconds", DEFAULT_TIMEOUT))
    if proc1.returncode != 0:
        err = proc1.stderr or ""
        for value in resolved_fields.values():
            if isinstance(value, str) and value:
                err = err.replace(value, "***")
        lines = [line.strip() for line in err.splitlines() if line.strip()]
        safe_tail = lines[-1][:500] if lines else "unknown"
        return {
            "success": False,
            "submitted": False,
            "blocked_reason": None,
            "error": "browser_harness_fill_failed:" + safe_tail,
        }

    out1 = proc1.stdout or ""
    target_match = re.search(r"===TARGET===\r?\n([^\r\n]+)", out1)
    target_id = target_match.group(1).strip() if target_match else ""
    pre_match = re.search(r"===PRESCAN===\r?\n(.*?)===POSTFILL===", out1, re.S)
    post_match = re.search(r"===POSTFILL===\r?\n(.*)$", out1, re.S)
    pre_text = pre_match.group(1).strip() if pre_match else ""
    post_text = post_match.group(1).strip() if post_match else ""

    blocker = scan_blockers(pre_text + "\n" + post_text)
    if blocker:
        return {"success": False, "submitted": False, "blocked_reason": blocker}
    if not submit or not submit_selector:
        return {"success": True, "submitted": False, "blocked_reason": None}
    if not target_id:
        return {"success": False, "submitted": False, "error": "missing_target_id"}

    anchor_selector = str(field_items[0][0]) if field_items else ""
    click_js = (
        "(function(){"
        + "var anchor=document.querySelector(" + json.dumps(anchor_selector) + ");"
        + "var form=anchor&&anchor.form;"
        + "var el=form?form.querySelector('button[type=\"submit\"],input[type=\"submit\"],button:not([type])'):null;"
        + "if(!el) el=document.querySelector(" + json.dumps(submit_selector) + ");"
        + "if(!el) return 'missing'; el.click(); return 'clicked';})()"
    )
    prosper_login_retry = (
        str(url).startswith("https://homologacao.prospersend.com.br/login")
        or str(url).startswith("https://homologacao.prospersend.com.br/login?")
    )
    phase2 = f"""
switch_tab({target_id!r}, activate=True)
wait_for_network_idle(timeout=8.0, idle_ms=800)
wait(1.0)
result = js({click_js!r})
print("===SUBMIT===")
print(result)
wait_for_network_idle(timeout=15.0, idle_ms=1200)
wait(1.0)
first_url = js("location.href") or ""
first_text = js("document.body.innerText") or ""
retry_result = ""
if {prosper_login_retry!r} and str(first_url).startswith("https://homologacao.prospersend.com.br/login"):
    wait(2.0)
    retry_result = js({click_js!r})
    wait_for_network_idle(timeout=15.0, idle_ms=1200)
    wait(1.0)
print("===RETRY===")
print(retry_result)
final_text = js("document.body.innerText") or ""
print("===FINAL===")
print(final_text[:{MAX_TEXT_CHARS}])
print("===FINALURL===")
print(js("location.href") or "")
print("===FINALTITLE===")
print(js("document.title") or "")
"""
    proc2 = run_harness(phase2, job.get("timeout_seconds", DEFAULT_TIMEOUT))
    if proc2.returncode != 0:
        err = (proc2.stderr or "").strip()
        lines = [line.strip() for line in err.splitlines() if line.strip()]
        safe_tail = lines[-1][:500] if lines else "unknown"
        return {
            "success": False,
            "submitted": False,
            "blocked_reason": None,
            "error": "browser_harness_submit_failed:" + safe_tail,
        }

    out2 = proc2.stdout or ""

    def marker_line(name: str) -> str:
        match = re.search(r"===" + re.escape(name) + r"===\r?\n([^\r\n]*)", out2)
        return match.group(1).strip() if match else ""

    submit_result = marker_line("SUBMIT")
    retry_result = marker_line("RETRY")
    final_url = marker_line("FINALURL")
    final_title = marker_line("FINALTITLE")
    final_match = re.search(r"===FINAL===\r?\n(.*?)===FINALURL===", out2, re.S)
    final_text = final_match.group(1).strip() if final_match else ""
    final_blocker = scan_blockers(final_text)
    clicked = submit_result == "clicked" or retry_result == "clicked"
    login_flow = str(url).startswith("https://homologacao.prospersend.com.br/login")
    authenticated = str(final_url).startswith("https://homologacao.prospersend.com.br/app/")
    if login_flow:
        ok = authenticated and not final_blocker
    else:
        ok = clicked and not final_blocker

    return {
        "success": ok,
        "submitted": ok,
        "blocked_reason": final_blocker,
        "url": final_url,
        "title": final_title,
        "page_excerpt": final_text[:1200],
    }

def pick_click_target(candidates: list[dict], text: str) -> dict | None:
    """Pick the visible text target. Exact beats contains. Semantic beats custom."""
    query = " ".join(str(text or "").split())
    if not query or not isinstance(candidates, list):
        return None
    visible: list[dict] = []
    for idx, raw in enumerate(candidates):
        if not isinstance(raw, dict) or not raw.get("visible", True) or raw.get("disabled"):
            continue
        width = float(raw.get("width") or 0)
        height = float(raw.get("height") or 0)
        if width < 2 or height < 2:
            continue
        label = " ".join(str(raw.get("text") or "").split())
        if not label:
            continue
        exact = label == query
        contains = (not exact) and query in label and len(label) <= max(len(query) + 48, 80)
        if not exact and not contains:
            continue
        item = dict(raw)
        item["_idx"] = idx
        item["_label"] = label
        item["_area"] = width * height
        item["_exact"] = exact
        visible.append(item)
    exact_pool = [item for item in visible if item["_exact"]]
    pool = exact_pool or [item for item in visible if not item["_exact"]]
    if not pool:
        return None

    def tier(item: dict) -> int:
        if item.get("semantic"):
            return 3
        if item.get("interactive"):
            return 2
        return 1

    pool.sort(key=lambda item: (-tier(item), item["_area"], -int(item.get("depth") or 0), -item["_idx"]))
    chosen = pool[0]
    strategy = {3: "semantic", 2: "interactive-signal", 1: "custom-visible-text"}[tier(chosen)]
    matched_exact = bool(exact_pool)
    if not matched_exact:
        strategy = "contains-fallback"
    if not chosen.get("semantic"):
        parent_idx = chosen.get("parent")
        hops = 0
        seen: set[int] = set()
        semantic_parent = None
        signal_parent = None
        while isinstance(parent_idx, int) and parent_idx not in seen and hops < 5:
            seen.add(parent_idx)
            if parent_idx < 0 or parent_idx >= len(candidates):
                break
            parent = candidates[parent_idx]
            hops += 1
            if not isinstance(parent, dict):
                break
            pw = float(parent.get("width") or 0)
            ph = float(parent.get("height") or 0)
            if pw > 640 or ph > 320:
                break
            usable = parent.get("visible", True) and not parent.get("disabled") and pw >= 2 and ph >= 2
            if usable and parent.get("semantic"):
                semantic_parent = parent
                semantic_parent["_idx"] = parent_idx
                break
            if usable and signal_parent is None and parent.get("interactive"):
                signal_parent = dict(parent)
                signal_parent["_idx"] = parent_idx
            parent_idx = parent.get("parent")
        promoted = semantic_parent or (signal_parent if tier(chosen) == 1 else None)
        if promoted is not None:
            chosen = promoted if isinstance(promoted, dict) else dict(promoted)
            if "_idx" not in chosen:
                chosen["_idx"] = parent_idx
            chosen["_label"] = " ".join(str(chosen.get("text") or "").split())[:160]
            strategy = "semantic-ancestor" if semantic_parent is not None else "interactive-ancestor"
    return {
        "found": True,
        "tag": str(chosen.get("tag") or ""),
        "text": str(chosen.get("_label") or "")[:160],
        "strategy": strategy,
        "matched_exact": matched_exact,
    }


def resolve_click_target_by_text(text: str) -> str:
    """JS click resolver for semantic controls and custom Vue elements."""
    query = json.dumps(" ".join(str(text or "").split()))
    return ("(function(){\nvar t=__QUERY__;\nfunction norm(s){return String(s||'').replace(/[ \\t\\r\\n]+/g,' ').trim();}\nfunction vis(el){if(!el||el.disabled||el.getAttribute('aria-disabled')==='true'||el.getAttribute('aria-hidden')==='true')return false;var r=el.getBoundingClientRect();if(r.width<2||r.height<2)return false;var s=getComputedStyle(el);if(s.visibility==='hidden'||s.display==='none'||s.pointerEvents==='none')return false;if(parseFloat(s.opacity||'1')===0)return false;return true;}\nfunction semantic(el){var tag=el.tagName.toLowerCase();var role=(el.getAttribute('role')||'').toLowerCase();return tag==='button'||tag==='a'||tag==='label'||tag==='input'||tag==='textarea'||tag==='select'||role==='button'||role==='option'||role==='menuitem'||role==='tab'||role==='link';}\nfunction signal(el){var tab=el.getAttribute('tabindex');if(tab!==null&&tab!==''&&Number(tab)>=0)return true;if(el.onclick||el.getAttribute('onclick'))return true;if(getComputedStyle(el).cursor==='pointer')return true;var cls='';try{cls=String(el.className||'');}catch(e){cls='';}return /card|choice|selectable|clickable|chip|option/i.test(cls);}\nfunction tier(el){if(semantic(el))return 3;if(signal(el))return 2;return 1;}\nvar nodes=document.querySelectorAll('button,a,[role=button],[role=option],[role=menuitem],[role=tab],label,input,textarea,select,[tabindex],[onclick],div,span,section,article,p,li');\nvar exact=[];var loose=[];\nfor(var i=0;i<nodes.length;i++){var el=nodes[i];if(!vis(el))continue;var label=norm(el.innerText||el.value||el.textContent||'');if(!label)continue;var rect=el.getBoundingClientRect();var depth=0;var walk=el;while(walk&&depth<40){depth++;walk=walk.parentElement;}var item={el:el,text:label,area:rect.width*rect.height,depth:depth,index:i};if(label===t)exact.push(item);else if(label.indexOf(t)>=0&&label.length<=Math.max(t.length+48,80))loose.push(item);}\nfunction inChrome(el){return !!(el.closest&&el.closest('nav,aside,header'));}var mex=exact.filter(function(x){return !inChrome(x.el);});if(mex.length)exact=mex;var mlo=loose.filter(function(x){return !inChrome(x.el);});if(mlo.length)loose=mlo;var pool=exact.length?exact:loose;if(!pool.length)return {found:false};\npool.sort(function(a,b){var dt=tier(b.el)-tier(a.el);if(dt)return dt;if(Math.abs(a.area-b.area)>1)return a.area-b.area;if(b.depth!==a.depth)return b.depth-a.depth;return b.index-a.index;});\nvar chosen=pool[0];var strategy=tier(chosen.el)===3?'semantic':(tier(chosen.el)===2?'interactive-signal':'custom-visible-text');if(!exact.length)strategy='contains-fallback';\nif(!semantic(chosen.el)){var anc=chosen.el.parentElement;var hops=0;var sem=null;var sig=null;while(anc&&hops<5){var ar=anc.getBoundingClientRect();if(ar.width>640||ar.height>320)break;if(vis(anc)&&semantic(anc)){sem=anc;break;}if(!sig&&vis(anc)&&signal(anc))sig=anc;anc=anc.parentElement;hops++;}var use=sem||(tier(chosen.el)===1?sig:null);if(use){var ur=use.getBoundingClientRect();chosen={el:use,text:norm(use.innerText||use.textContent||'').slice(0,160),area:ur.width*ur.height,depth:chosen.depth,index:chosen.index};strategy=sem?'semantic-ancestor':'interactive-ancestor';}}\nchosen.el.scrollIntoView({block:'center',inline:'center'});var rr=chosen.el.getBoundingClientRect();\nreturn {found:true,tag:chosen.el.tagName.toLowerCase(),text:norm(chosen.el.innerText||chosen.el.value||chosen.el.textContent||'').slice(0,160),x:rr.left+rr.width/2,y:rr.top+rr.height/2,strategy:strategy,matched_exact:exact.length>0};})()").replace("__QUERY__", query)


def interactive_candidates_js() -> str:
    """Short visible custom controls for inspect. No page HTML."""
    return "(function(){function norm(s){return String(s||'').replace(/[ \\t\\r\\n]+/g,' ').trim();}function vis(el){if(!el||el.disabled||el.getAttribute('aria-disabled')==='true'||el.getAttribute('aria-hidden')==='true')return false;var r=el.getBoundingClientRect();if(r.width<2||r.height<2)return false;var s=getComputedStyle(el);if(s.visibility==='hidden'||s.display==='none'||s.pointerEvents==='none')return false;if(parseFloat(s.opacity||'1')===0)return false;return true;}function signal(el){var tab=el.getAttribute('tabindex');if(tab!==null&&tab!==''&&Number(tab)>=0)return true;if(getComputedStyle(el).cursor==='pointer')return true;var role=(el.getAttribute('role')||'').toLowerCase();if(role==='button'||role==='option'||role==='menuitem'||role==='tab')return true;var cls='';try{cls=String(el.className||'');}catch(e){cls='';}return /card|choice|selectable|clickable|chip|option/i.test(cls);}var nodes=document.querySelectorAll('button,a,[role=button],[role=option],[role=menuitem],[role=tab],[tabindex],[onclick],div,span,section,article,p,li');var out=[];var seen={};for(var i=0;i<nodes.length;i++){var el=nodes[i];if(!vis(el))continue;if(el.closest&&el.closest('nav,aside,header'))continue;var label=norm(el.innerText||el.value||el.textContent||'');if(!label||label.length>60)continue;var tag=el.tagName.toLowerCase();var interactive=signal(el);var custom=tag==='div'||tag==='span'||tag==='section'||tag==='article'||tag==='p'||tag==='li';var rect=el.getBoundingClientRect();if(!interactive){if(!custom||el.children.length>4||rect.width>520||rect.height>180)continue;}var key=tag+'|'+label;if(seen[key])continue;seen[key]=1;var tab=el.getAttribute('tabindex');out.push({tag:tag,text:label.slice(0,80),role:el.getAttribute('role')||'',cursor:getComputedStyle(el).cursor||'',tabindex:tab===null||tab===''?null:Number(tab),interactive:!!interactive});if(out.length>=60)break;}return JSON.stringify(out);})()"


def action_interact(job: dict) -> dict:
    """Perform structured UI interactions on an authenticated SPA page."""
    url = str(job.get("url") or "").strip()
    steps = job.get("steps") or []
    if not isinstance(steps, list) or not steps:
        return {"success": False, "error": "steps_required"}

    code_lines: list[str] = []
    if url:
        code_lines.extend([
            f"new_tab({url!r})",
            "wait_for_load(timeout=20.0)",
            "try:",
            "    wait_for_network_idle(timeout=20.0, idle_ms=1200)",
            "except Exception:",
            "    pass",
            "wait(1.0)",
        ])
    else:
        code_lines.extend(["ensure_real_tab()", "wait(0.5)"])

    _cookie_js = (
        "(function(){var xs=Array.from(document.querySelectorAll('button'));"
        "var e=null;for(var i=0;i<xs.length;i++){var t=(xs[i].innerText||'').trim();"
        "if(t==='Aceitar'){var r=xs[i].getBoundingClientRect();if(r.width>2&&r.height>2)e=xs[i];}}"
        "if(!e)return null;var r=e.getBoundingClientRect();"
        "return {x:r.left+r.width/2,y:r.top+r.height/2};})()"
    )
    code_lines.append(f"_cookie=js({_cookie_js!r})")
    code_lines.append("if _cookie: click_at_xy(float(_cookie['x']), float(_cookie['y'])); wait(0.4)")

    for idx, raw in enumerate(steps[:30]):
        if not isinstance(raw, dict):
            return {"success": False, "error": f"invalid_step:{idx}"}
        op = str(raw.get("op") or "").strip().lower()
        selector = str(raw.get("selector") or "").strip()
        text_value = str(raw.get("text") or "")
        value = str(raw.get("value") or "")
        key = str(raw.get("key") or "")
        seconds = raw.get("seconds", 0.8)

        if op == "click":
            if selector:
                target_expr = (
                    "(function(){var e=document.querySelector(" + json.dumps(selector) + ");"
                    "if(!e)return null;e.scrollIntoView({block:'center',inline:'center'});"
                    "var r=e.getBoundingClientRect();"
                    "return {x:r.left+r.width/2,y:r.top+r.height/2,"
                    "label:(e.innerText||e.value||e.textContent||e.tagName||'').toString().slice(0,160)};})()"
                )
            elif text_value:
                target_expr = resolve_click_target_by_text(text_value)
            else:
                return {"success": False, "error": f"click_target_required:{idx}"}
            code_lines.append(f"_click_target_{idx}=js({target_expr!r})")
            code_lines.append(
                f"if not _click_target_{idx} or _click_target_{idx}.get('found') is False: raise RuntimeError('click target missing')"
            )
            code_lines.append(
                f"click_at_xy(float(_click_target_{idx}['x']), float(_click_target_{idx}['y']))"
            )
            code_lines.append(
                f"print('===STEP{idx}===', _click_target_{idx}.get('label') or _click_target_{idx}.get('text') or 'clicked')"
            )
            code_lines.append(
                f"print('===CLICKMETA{idx}===', _click_target_{idx}.get('strategy') or 'selector', _click_target_{idx}.get('tag') or 'node', _click_target_{idx}.get('matched_exact'))"
            )
            code_lines.append("wait(0.8)")
            _state_js = "(function(){var out=[];var nodes=document.querySelectorAll('button');for(var i=0;i<nodes.length;i++){var b=nodes[i];if(String(b.className||'').indexOf('border-primary')<0)continue;out.push((b.innerText||'').replace(/\\s+/g,' ').trim().slice(0,60));}return out.join('|');})()"
            code_lines.append(f"print('===CLICKSTATE{idx}===', js({_state_js!r}) or '')")
        elif op == "type":
            if not selector:
                return {"success": False, "error": f"type_selector_required:{idx}"}
            code_lines.append(f"fill_input({selector!r}, {value!r}, clear_first=True, timeout=8.0)")
            code_lines.append(f"print('===STEP{idx}=== typed')")
        elif op == "select":
            if not selector:
                return {"success": False, "error": f"select_selector_required:{idx}"}
            select_expr = (
                "(function(){var e=document.querySelector(" + json.dumps(selector) + ");"
                "if(!e)return 'missing';"
                "var p=Object.getPrototypeOf(e);"
                "var d=Object.getOwnPropertyDescriptor(p,'value');"
                "if(d&&d.set){d.set.call(e," + json.dumps(value) + ");}else{e.value=" + json.dumps(value) + ";}"
                "try{e.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:" + json.dumps(value) + "}));}"
                "catch(_){e.dispatchEvent(new Event('input',{bubbles:true}));}"
                "e.dispatchEvent(new Event('change',{bubbles:true}));"
                "return e.value;})()"
            )
            code_lines.append(f"print('===STEP{idx}===', js({select_expr!r}))")
            code_lines.append("wait(0.8)")
        elif op == "press":
            if not key:
                return {"success": False, "error": f"press_key_required:{idx}"}
            code_lines.append(f"press_key({key!r})")
            code_lines.append(f"print('===STEP{idx}=== pressed')")
        elif op == "wait":
            try:
                sec = max(0.0, min(float(seconds), 10.0))
            except Exception:
                sec = 0.8
            code_lines.append(f"wait({sec!r})")
            code_lines.append(f"print('===STEP{idx}=== waited')")
        else:
            return {"success": False, "error": f"unsupported_step:{op or idx}"}

    code_lines.extend([
        "try:",
        "    wait_for_network_idle(timeout=20.0, idle_ms=1200)",
        "except Exception:",
        "    pass",
        "wait(1.0)",
        "print('===FINALURL===')",
        "print(js('location.href') or '')",
        "print('===FINALTITLE===')",
        "print(js('document.title') or '')",
        "print('===MAINTEXT===')",
        'print((js("(document.querySelector(\'main\')||document.body).innerText||\'\'") or \'\')[:4000])',
        "print('===FINALTEXT===')",
        "print((js('document.body.innerText') or '')[:6000])",
        "print('===SPINNERS===')",
        "print(js(\"document.querySelectorAll('[role=progressbar],[class*=spinner],[class*=loading],[class*=animate-spin]').length\"))",
    ])
    proc = run_harness("\n".join(code_lines) + "\n", job.get("timeout_seconds", DEFAULT_TIMEOUT))
    if proc.returncode != 0:
        return {
            "success": False,
            "error": "interact_failed:" + ((proc.stderr or "").strip().splitlines()[-1][:500] if (proc.stderr or "").strip() else "unknown"),
        }
    out = proc.stdout or ""

    def marker_line(name: str) -> str:
        m = re.search(r"===" + re.escape(name) + r"===\r?\n([^\r\n]*)", out)
        return m.group(1).strip() if m else ""

    final_match = re.search(r"===FINALTEXT===\r?\n(.*?)===SPINNERS===", out, re.S)
    final_text = final_match.group(1).strip() if final_match else ""
    main_match = re.search(r"===MAINTEXT===\r?\n(.*?)===FINALTEXT===", out, re.S)
    main_text = main_match.group(1).strip() if main_match else ""
    clicks = []
    click_states = {}
    for state_match in re.finditer(r"===CLICKSTATE(\d+)===[ 	]*(.*)", out):
        click_states[int(state_match.group(1))] = state_match.group(2).strip()
    for match in re.finditer(r"===CLICKMETA(\d+)===\s+(\S+)\s+(\S+)\s+(\S+)", out):
        clicks.append({
            "step": int(match.group(1)),
            "strategy": match.group(2),
            "tag": match.group(3),
            "matched_exact": match.group(4) == "True",
        })
    return {
        "success": True,
        "url": marker_line("FINALURL"),
        "title": marker_line("FINALTITLE"),
        "page_excerpt": final_text[:2000],
        "main_excerpt": main_text[:4000],
        "spinner_count": int(marker_line("SPINNERS") or 0),
        "clicks": clicks,
        "click_states": click_states,
        "steps_executed": len(steps[:30]),
    }


def action_inspect(job: dict) -> dict:
    """Inspect forms/inputs/buttons without exposing page secrets."""
    url = str(job.get("url") or "").strip()

    inputs_expr = """JSON.stringify(Array.prototype.map.call(
      document.querySelectorAll('input,textarea,select'),
      function(e,i){return {
        index:i,tag:e.tagName.toLowerCase(),type:e.type||'',id:e.id||'',
        name:e.name||'',placeholder:e.placeholder||'',
        value:(String(e.type||'').toLowerCase()==='password'?'':String(e.value||'')),
        checked:!!e.checked,
        accept:e.accept||'',multiple:!!e.multiple,
        files:Array.from(e.files||[]).map(function(f){return {name:f.name,size:f.size,type:f.type||''}}),
        aria:e.getAttribute('aria-label')||'',autocomplete:e.autocomplete||''
      }}
    ))"""
    buttons_expr = """JSON.stringify(Array.prototype.map.call(
      Array.prototype.filter.call(document.querySelectorAll('button,input[type=submit],input[type=button],a,[role=option],[role=menuitem]'),function(e){var r=e.getBoundingClientRect();var s=getComputedStyle(e);return r.width>2&&r.height>2&&s.visibility!=='hidden'&&s.display!=='none';}),
      function(e,i){return {
        index:i,tag:e.tagName.toLowerCase(),type:e.type||'',id:e.id||'',
        text:(e.innerText||e.value||'').trim().slice(0,120),
        aria:e.getAttribute('aria-label')||'',href:e.href||''
      }}
    ))"""
    forms_expr = """JSON.stringify(Array.prototype.map.call(
      document.forms,
      function(f,i){return {index:i,id:f.id||'',action:f.action||'',method:f.method||''}}
    ))"""

    nav = (
        f"new_tab({url!r})\n"
        "wait_for_load(timeout=20.0)\n"
        "try:\n"
        "    wait_for_network_idle(timeout=20.0, idle_ms=1200)\n"
        "except Exception:\n"
        "    pass\n"
        "wait(1.5)\n"
        if url
        else "ensure_real_tab()\nwait(0.5)\n"
    )
    code = (
        nav
        + "print('===TITLE===')\n"
        + "print(js('document.title') or '')\n"
        + "print('===URL===')\n"
        + "print(js('location.href') or '')\n"
        + "print('===INPUTS===')\n"
        + f"print(js({inputs_expr!r}) or '[]')\n"
        + "print('===BUTTONS===')\n"
        + f"print(js({buttons_expr!r}) or '[]')\n"
        + "print('===CANDIDATES===')\n"
        + f"print(js({interactive_candidates_js()!r}) or '[]')\n"
        + "print('===FORMS===')\n"
        + f"print(js({forms_expr!r}) or '[]')\n"
    )
    proc = run_harness(code, job.get("timeout_seconds", DEFAULT_TIMEOUT))
    if proc.returncode != 0:
        return {"success": False, "error": "inspect_failed: " + proc.stderr.strip()[:700]}
    out = proc.stdout or ""

    def section(name: str, next_name: str | None = None) -> str:
        mark = "===" + name + "==="
        if mark not in out:
            return ""
        tail = out.split(mark,1)[1]
        if next_name:
            nmark = "===" + next_name + "==="
            if nmark in tail:
                tail = tail.split(nmark,1)[0]
        return tail.strip()

    title = section("TITLE","URL")
    final_url = section("URL","INPUTS") or url
    raw_inputs = section("INPUTS","BUTTONS") or "[]"
    raw_buttons = section("BUTTONS","CANDIDATES") or "[]"
    raw_candidates = section("CANDIDATES","FORMS") or "[]"
    raw_forms = section("FORMS") or "[]"
    try:
        inputs = json.loads(raw_inputs)
    except Exception:
        inputs = []
    try:
        buttons = json.loads(raw_buttons)
    except Exception:
        buttons = []
    try:
        candidates = json.loads(raw_candidates)
    except Exception:
        candidates = []
    try:
        forms = json.loads(raw_forms)
    except Exception:
        forms = []
    return {
        "success": True,
        "inspect": {
            "title": title,
            "url": final_url,
            "inputs": inputs[:80],
            "buttons": buttons[:120],
            "interactive_candidates": candidates[:60] if isinstance(candidates, list) else [],
            "forms": forms[:20],
        },
    }

def action_upload_file(job: dict) -> dict:
    """Upload one QA attachment to a file input using CDP, preserving framework events."""
    job_id = str(job.get("job_id") or "job")
    selector = str(job.get("selector") or "").strip()
    filename = os.path.basename(str(job.get("filename") or "qa-upload.bin"))
    content_b64 = str(job.get("content_b64") or "")
    url = str(job.get("url") or "").strip()
    if not selector:
        return {"success": False, "error": "upload_selector_required"}
    if not content_b64:
        return {"success": False, "error": "upload_content_required"}

    try:
        raw = base64.b64decode(content_b64, validate=True)
    except Exception:
        return {"success": False, "error": "upload_invalid_base64"}
    if len(raw) > 25 * 1024 * 1024:
        return {"success": False, "error": "upload_too_large"}

    workdir = os.path.join(JOBS_ROOT, job_id)
    os.makedirs(workdir, exist_ok=True)
    path = os.path.join(workdir, filename)
    with open(path, "wb") as fh:
        fh.write(raw)

    nav = (
        f"new_tab({url!r})\n"
        "wait_for_load(timeout=20.0)\n"
        "try:\n"
        "    wait_for_network_idle(timeout=20.0, idle_ms=1200)\n"
        "except Exception:\n"
        "    pass\n"
        "wait(1.0)\n"
        if url
        else "ensure_real_tab()\nwait(0.5)\n"
    )
    event_js = (
        "(()=>{const e=document.querySelector(" + json.dumps(selector) + ");"
        "if(!e)return;"
        "try{e.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertReplacementText'}));}"
        "catch(_){e.dispatchEvent(new Event('input',{bubbles:true}));}"
        "e.dispatchEvent(new Event('change',{bubbles:true}));})()"
    )
    code = (
        nav
        + "root=cdp('DOM.getDocument')['root']['nodeId']\n"
        + f"node=cdp('DOM.querySelector', nodeId=root, selector={selector!r}).get('nodeId',0)\n"
        + "if not node: raise RuntimeError('upload input not found')\n"
        + f"cdp('DOM.setFileInputFiles', files={[path]!r}, nodeId=node)\n"
        + f"js({event_js!r})\n"
        + "try:\n"
        + "    wait_for_network_idle(timeout=20.0, idle_ms=1200)\n"
        + "except Exception:\n"
        + "    pass\n"
        + "wait(1.0)\n"
        + "print('===URL===')\n"
        + "print(js('location.href') or '')\n"
        + "print('===TEXT===')\n"
        + "print((js('document.body.innerText') or '')[:4000])\n"
    )
    proc = run_harness(code, job.get("timeout_seconds", DEFAULT_TIMEOUT))
    if proc.returncode != 0:
        lines = [line.strip() for line in (proc.stderr or "").splitlines() if line.strip()]
        return {
            "success": False,
            "error": "upload_failed:" + (lines[-1][:500] if lines else "unknown"),
        }
    out = proc.stdout or ""
    final_url = ""
    page_excerpt = ""
    if "===URL===" in out and "===TEXT===" in out:
        final_url = out.split("===URL===",1)[1].split("===TEXT===",1)[0].strip()
        page_excerpt = out.split("===TEXT===",1)[1].strip()[:2000]
    return {
        "success": True,
        "url": final_url,
        "filename": filename,
        "bytes": len(raw),
        "page_excerpt": page_excerpt,
    }


def action_screenshot(job: dict) -> dict:
    """Capture browser evidence and upload it to the private Hermes QA bridge."""
    job_id = str(job.get("job_id") or "job")
    workdir = os.path.join(JOBS_ROOT, job_id)
    os.makedirs(workdir, exist_ok=True)
    shot_path = os.path.join(workdir, "screenshot.png")
    url = str(job.get("url") or "").strip()
    full = bool(job.get("full", False))
    try:
        max_dim = int(job.get("max_dim") or 1600)
    except Exception:
        max_dim = 1600
    max_dim = max(480, min(max_dim, 1800))
    nav = (
        f"new_tab({url!r})\n"
        "wait_for_load(timeout=20.0)\n"
        "try:\n"
        "    wait_for_network_idle(timeout=20.0, idle_ms=1200)\n"
        "except Exception:\n"
        "    pass\n"
        "wait(1.5)\n"
        if url
        else "ensure_real_tab()\nwait(0.5)\n"
    )
    code = (
        nav
        + f"path=capture_screenshot({shot_path!r}, full={full!r}, max_dim={max_dim})\n"
        + "print('===TITLE===')\n"
        + "print(js('document.title') or '')\n"
        + "print('===URL===')\n"
        + "print(js('location.href') or '')\n"
    )
    proc = run_harness(code, job.get("timeout_seconds", DEFAULT_TIMEOUT))
    if proc.returncode != 0 or not os.path.isfile(shot_path):
        return {
            "success": False,
            "error": "screenshot_failed: " + (proc.stderr.strip()[:300] if proc.stderr else "no file"),
        }
    out = proc.stdout or ""
    title = ""
    final_url = url
    if "===TITLE===" in out and "===URL===" in out:
        title = out.split("===TITLE===",1)[1].split("===URL===",1)[0].strip()
        tail = out.split("===URL===",1)[1].strip()
        final_url = tail.splitlines()[0] if tail else url
    evidence = _upload_evidence(shot_path, job_id, "screenshot.png")
    return {
        "success": True,
        "title": title,
        "url": final_url,
        "evidence_path": evidence.get("path"),
        "evidence_sha256": evidence.get("sha256"),
        "evidence_bytes": evidence.get("bytes"),
        "mime_type": evidence.get("mime_type", "image/png"),
    }



_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
_SENSITIVE_JSON_RE = re.compile(
    r'(?i)("(?:access_token|refresh_token|id_token|authorization|cookie|set-cookie|password|secret|token)"\s*:\s*)"(?:\\.|[^"\\])*"'
)


def host_allowed(url: str) -> bool:
    if not url:
        return True
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False
    return parsed.scheme == "https" and (parsed.hostname or "").lower() in ALLOWED_QA_HOSTS


def redact_diagnostic(text: str) -> str:
    cleaned = _JWT_RE.sub("[redacted]", text or "")
    return _SENSITIVE_JSON_RE.sub(r'\1"[redacted]"', cleaned)


def _guard_job_urls(job: dict) -> dict | None:
    urls = []
    if job.get("url"):
        urls.append(str(job.get("url")))
    for item in job.get("urls") or []:
        urls.append(str(item))
    for item in urls:
        if not host_allowed(item):
            return {"success": False, "error": "url_not_allowed"}
    return None


def action_api_read(job: dict) -> dict:
    """Authenticated read-only diagnostic. Token stays inside the page."""
    url = str(job.get("url") or "").strip()
    method = str(job.get("method") or "GET").strip().upper()
    if method not in {"GET", "HEAD"}:
        return {"success": False, "error": "method_not_allowed"}
    if not url or not host_allowed(url):
        return {"success": False, "error": "url_not_allowed"}
    expr = (
        "(async function(){"
        + "var url=" + json.dumps(url) + ";"
        + "var method=" + json.dumps(method) + ";"
        + "var token='';"
        + "try{for(var i=0;i<localStorage.length;i++){"
        + "var key=localStorage.key(i)||''; if(key.indexOf('refresh')>=0) continue; var raw=localStorage.getItem(key)||'';"
        + "var found=raw.match(/eyJ[A-Za-z0-9_-]{8,}\\.[A-Za-z0-9_-]{8,}\\.[A-Za-z0-9_-]{8,}/);"
        + "if(found){token=found[0];break;}}}catch(e){}"
        + "var headers={}; if(token) headers['Authorization']='Bearer '+token;"
        + "try{"
        + "var res=await fetch(url,{method:method,credentials:'include',headers:headers});"
        + "var body=method==='HEAD'?'':String(await res.text()||'').slice(0,8000);"
        + "return JSON.stringify({status:res.status,content_type:res.headers.get('content-type')||'',body:body});"
        + "}catch(e){return JSON.stringify({status:0,content_type:'',body:'',error:'fetch_failed'});}"
        + "})()"
    )
    code = (
        "ensure_real_tab()\n"
        "href = js('location.href') or ''\n"
        "if 'homologacao.prospersend.com.br' not in str(href):\n"
        "    new_tab('https://homologacao.prospersend.com.br/app/dashboard')\n"
        "    wait_for_load(timeout=20.0)\n"
        "    wait(1.0)\n"
        "print('===API===')\n"
        + "print(js(%r) or '')\n" % (expr,)
    )
    proc = run_harness(code, job.get("timeout_seconds", DEFAULT_TIMEOUT))
    if proc.returncode != 0:
        lines = [line.strip() for line in (proc.stderr or "").splitlines() if line.strip()]
        return {"success": False, "error": "api_read_failed:" + (lines[-1][:300] if lines else "unknown")}
    out = proc.stdout or ""
    raw = ""
    if "===API===" in out:
        tail = out.split("===API===", 1)[1].strip()
        raw = tail.splitlines()[0] if tail else ""
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        payload = {"status": 0, "body": "", "error": "invalid_api_payload"}
    body = redact_diagnostic(str(payload.get("body") or ""))
    lowered = body.lower()
    if "authorization" in lowered or "set-cookie" in lowered or "eyj" in lowered:
        body = redact_diagnostic(body)
    return {
        "success": True,
        "status": payload.get("status"),
        "content_type": str(payload.get("content_type") or "")[:120],
        "body": body[:4000],
        "method": method,
        "url": url,
    }


def run_job(job: dict) -> dict:
    action = job.get("action")
    guarded = _guard_job_urls(job)
    if guarded:
        return guarded
    if action == "api_read":
        return action_api_read(job)
    if action == "read_links":
        return action_read_links(job)
    if action == "doctor":
        return action_doctor(job)
    if action == "screenshot":
        return action_screenshot(job)
    if action == "inspect":
        return action_inspect(job)
    if action == "interact":
        return action_interact(job)
    if action == "upload_file":
        return action_upload_file(job)
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
