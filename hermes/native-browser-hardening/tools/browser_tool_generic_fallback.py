"""Generic fallbacks for Hermes native browser tools (upload, click, modal fill).

Uses upstream agent-browser commands where possible; CDP via browser_supervisor when needed.
No application-specific selectors or copy.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --- Authorized file paths (upload) -----------------------------------------

_DEFAULT_UPLOAD_ROOT_NAMES = (
    "attachments",
    "cache",
    "uploads",
    "browser_uploads",
    "files",
)


def _hermes_home() -> Path:
    from hermes_constants import get_hermes_home

    return Path(get_hermes_home()).resolve()


def _extra_upload_roots() -> List[Path]:
    raw = os.environ.get("HERMES_BROWSER_UPLOAD_ALLOWED_DIRS", "")
    roots: List[Path] = []
    for part in raw.split(os.pathsep):
        part = part.strip()
        if part:
            roots.append(Path(part).resolve())
    return roots


def resolve_authorized_upload_path(file_path: str) -> Tuple[Optional[Path], Optional[str]]:
    """Return (resolved_path, error). Denies traversal, dirs, missing files."""
    if not file_path or not str(file_path).strip():
        return None, "file_path is required"
    raw = str(file_path).strip()
    if ".." in raw.replace("\\", "/"):
        return None, "path traversal denied"
    p = Path(raw).expanduser()
    try:
        resolved = p.resolve()
    except OSError as exc:
        return None, f"invalid path: {exc}"
    if not resolved.is_file():
        return None, "file does not exist or is not a regular file"
    home = _hermes_home()
    allowed_roots = [home] + _extra_upload_roots()
    tmp = Path(os.environ.get("TMPDIR", "/tmp")).resolve()
    allowed_roots.append(tmp)
    for root in allowed_roots:
        try:
            resolved.relative_to(root)
            return resolved, None
        except ValueError:
            continue
    # Also allow explicit subpaths under home by name (attachments under profile)
    for name in _DEFAULT_UPLOAD_ROOT_NAMES:
        for candidate in home.rglob(name):
            if candidate.is_dir():
                try:
                    resolved.relative_to(candidate.resolve())
                    return resolved, None
                except ValueError:
                    pass
    return None, "upload path not under an authorized directory"


# --- JS helpers (generic) ----------------------------------------------------

_DISCOVER_FILE_INPUT_JS = r"""
(function(hint){
  const norm = (s) => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
  const hintN = hint ? norm(hint) : '';
  function cssPath(el){
    if (!el || el.nodeType !== 1) return '';
    if (el.id) return '#'+CSS.escape(el.id);
    const parts = [];
    while (el && el.nodeType === 1 && el.tagName !== 'HTML'){
      let sel = el.tagName.toLowerCase();
      const parent = el.parentElement;
      if (parent){
        const sibs = [...parent.children].filter(c => c.tagName === el.tagName);
        if (sibs.length > 1) sel += ':nth-of-type('+(sibs.indexOf(el)+1)+')';
      }
      parts.unshift(sel);
      el = parent;
    }
    return parts.join('>');
  }
  function score(inp){
    let s = 0;
    const label = inp.labels && inp.labels[0] ? norm(inp.labels[0].innerText) : '';
    const aria = norm(inp.getAttribute('aria-label')||'');
    const zone = inp.closest('label, [role=button], [class]');
    const ctx = norm(zone ? zone.innerText : '');
    if (hintN && (label.includes(hintN) || aria.includes(hintN) || ctx.includes(hintN))) s += 10;
    if (!inp.hidden && inp.offsetParent !== null) s += 1;
    return s;
  }
  const inputs = [...document.querySelectorAll('input[type=file]')];
  if (!inputs.length) return null;
  inputs.sort((a,b)=>score(b)-score(a));
  return cssPath(inputs[0]);
})(%s)
"""

_CLICK_ANCESTOR_JS = r"""
(function(ref){
  const r = ref.replace(/^@/,'');
  const map = globalThis.__agentBrowserRefs || globalThis.__abRefs;
  if (map && map[r]) {
    let el = map[r];
    const clickTarget = (node) => {
      if (!node) return null;
      const role = node.getAttribute && node.getAttribute('role');
      const tag = node.tagName ? node.tagName.toLowerCase() : '';
      if (tag === 'button' || tag === 'a' || role === 'button' || role === 'link' || node.onclick) return node;
      if (node.tabIndex >= 0 && node.getAttribute('tabindex') !== null) return node;
      return clickTarget(node.parentElement);
    };
    const target = clickTarget(el) || el;
    target.dispatchEvent(new MouseEvent('click', {bubbles:true,cancelable:true,view:window}));
    return {clicked:true, tag: target.tagName};
  }
  return {clicked:false, reason:'ref map unavailable'};
})(%s)
"""

_MODAL_FILL_JS = r"""
(function(text, fieldHint, fieldIndex){
  const norm = (s) => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
  const root = document.querySelector('[role=dialog],[aria-modal="true"],dialog[open]') || document.body;
  const visible = (el) => {
    if (!el) return false;
    const st = window.getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none') return false;
    return el.offsetParent !== null || el.isContentEditable;
  };
  const fields = [...root.querySelectorAll('input:not([type=hidden]):not([type=file]),textarea,[contenteditable="true"]')]
    .filter(visible);
  if (!fields.length) return {ok:false, error:'no editable fields in active surface'};
  let target = null;
  const hintN = fieldHint ? norm(fieldHint) : '';
  if (hintN) {
    for (const el of fields) {
      const id = norm(el.id||'');
      const name = norm(el.name||'');
      const ph = norm(el.placeholder||'');
      const aria = norm(el.getAttribute('aria-label')||'');
      let label = '';
      if (el.labels && el.labels[0]) label = norm(el.labels[0].innerText);
      if ([id,name,ph,aria,label].some(x => x && x.includes(hintN))) { target = el; break; }
    }
  }
  if (!target && typeof fieldIndex === 'number' && fieldIndex >= 0 && fieldIndex < fields.length) {
    target = fields[fieldIndex];
  }
  if (!target && fields.length === 1) target = fields[0];
  if (!target) return {ok:false, error:'ambiguous modal fields', count: fields.length};
  if (target.isContentEditable) {
    target.focus();
    target.textContent = text;
    target.dispatchEvent(new Event('input', {bubbles:true}));
  } else {
    target.focus();
    target.value = text;
    target.dispatchEvent(new Event('input', {bubbles:true}));
    target.dispatchEvent(new Event('change', {bubbles:true}));
  }
  return {ok:true, tag: target.tagName, type: target.type || 'textarea'};
})(%s, %s, %s)
"""


def _js_string(s: Optional[str]) -> str:
    return json.dumps(s if s is not None else "")


def _run(task_id: str, command: str, args: List[str]) -> Dict[str, Any]:
    from tools import browser_tool_session as _session
    from tools.browser_tool import _last_session_key

    effective = _last_session_key(task_id or "default")
    return _session._run_browser_command(effective, command, args)


def _eval_json(task_id: str, expression: str) -> Tuple[Optional[Any], Optional[str]]:
    from tools.browser_tool import browser_console

    raw = browser_console(expression=expression, task_id=task_id)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None, "invalid eval response"
    if not payload.get("success"):
        return None, payload.get("error") or "eval failed"
    result = payload.get("result")
    if isinstance(result, str):
        try:
            return json.loads(result), None
        except json.JSONDecodeError:
            return result, None
    return result, None


def _supervisor_cdp(task_id: str, method: str, params: Dict[str, Any], timeout: float = 10.0) -> Dict[str, Any]:
    try:
        from tools.browser_supervisor import SUPERVISOR_REGISTRY, _schedule
    except ImportError:
        return {"ok": False, "error": "supervisor unavailable"}
    sup = SUPERVISOR_REGISTRY.get(task_id or "default")
    if sup is None:
        return {"ok": False, "error": "no supervisor for task"}
    loop = sup._loop
    if loop is None or not loop.is_running():
        return {"ok": False, "error": "supervisor loop not running"}
    with sup._state_lock:
        if not sup._active or not sup._page_session_id:
            return {"ok": False, "error": "supervisor not attached"}
        sid = sup._page_session_id

    async def _go():
        return await sup._cdp(method, params, session_id=sid, timeout=timeout)

    try:
        resp = _schedule(_go(), loop, timeout=timeout + 1)
        return {"ok": True, "response": resp}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def cdp_set_file_input(task_id: str, selector: str, local_path: str) -> Dict[str, Any]:
    doc = _supervisor_cdp(task_id, "DOM.getDocument", {})
    if not doc.get("ok"):
        return doc
    root_id = doc["response"].get("result", {}).get("root", {}).get("nodeId")
    if not root_id:
        return {"ok": False, "error": "DOM.getDocument missing root"}
    q = _supervisor_cdp(
        task_id,
        "DOM.querySelector",
        {"nodeId": root_id, "selector": selector},
    )
    if not q.get("ok"):
        return q
    node_id = q["response"].get("result", {}).get("nodeId")
    if not node_id:
        return {"ok": False, "error": "file input selector not found in DOM"}
    up = _supervisor_cdp(
        task_id,
        "DOM.setFileInputFiles",
        {"nodeId": node_id, "files": [local_path]},
    )
    if not up.get("ok"):
        return up
    err = up["response"].get("error")
    if err:
        return {"ok": False, "error": str(err)}
    return {"ok": True, "selector": selector, "path": local_path}


def try_upload_fallback(
    task_id: str,
    file_path: str,
    *,
    ref: Optional[str] = None,
    target_hint: Optional[str] = None,
) -> Dict[str, Any]:
    resolved, err = resolve_authorized_upload_path(file_path)
    if err:
        return {"success": False, "error": err, "fallback": "upload"}
    assert resolved is not None
    path_str = str(resolved)
    if ref:
        ref_sel = ref if ref.startswith("@") else f"@{ref}"
        result = _run(task_id, "upload", [ref_sel, path_str])
        if result.get("success"):
            return {"success": True, "method": "agent-browser-upload-ref", "path": path_str}
    expr = _DISCOVER_FILE_INPUT_JS % _js_string(target_hint or "")
    selector, eval_err = _eval_json(task_id, expr)
    if eval_err:
        return {"success": False, "error": eval_err, "fallback": "upload"}
    if not selector or not isinstance(selector, str):
        cdp_only = cdp_set_file_input(task_id, 'input[type="file"]', path_str)
        if cdp_only.get("ok"):
            return {"success": True, "method": "cdp-setFileInputFiles-generic", "path": path_str}
        return {"success": False, "error": "no file input discovered", "fallback": "upload"}
    result = _run(task_id, "upload", [selector, path_str])
    if result.get("success"):
        return {"success": True, "method": "agent-browser-upload-discovered", "selector": selector, "path": path_str}
    cdp = cdp_set_file_input(task_id, selector, path_str)
    if cdp.get("ok"):
        return {"success": True, "method": "cdp-setFileInputFiles", "selector": selector, "path": path_str}
    return {
        "success": False,
        "error": result.get("error") or cdp.get("error") or "upload failed",
        "fallback": "upload",
    }


def _failure_suggests_missing_target(error: str) -> bool:
    if not error:
        return False
    e = error.lower()
    needles = (
        "not found",
        "no element",
        "could not find",
        "not clickable",
        "not visible",
        "timeout",
        "invalid ref",
        "unknown ref",
    )
    return any(n in e for n in needles)


def try_click_fallback(task_id: str, ref: str) -> Dict[str, Any]:
    ref_norm = ref if ref.startswith("@") else f"@{ref}"
    box = _run(task_id, "get", ["box", ref_norm])
    if box.get("success"):
        data = box.get("data") or {}
        rect = data.get("box") or data
        try:
            x = float(rect.get("x", 0)) + float(rect.get("width", 0)) / 2
            y = float(rect.get("y", 0)) + float(rect.get("height", 0)) / 2
        except (TypeError, ValueError):
            x = y = None
        if x is not None and y is not None:
            for method, params in (
                ("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y}),
                ("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1}),
                ("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1}),
            ):
                cdp = _supervisor_cdp(task_id, method, params)
                if not cdp.get("ok"):
                    break
            else:
                return {"success": True, "method": "cdp-coordinate-click", "ref": ref_norm, "x": x, "y": y}
    expr = _CLICK_ANCESTOR_JS % _js_string(ref_norm)
    val, eval_err = _eval_json(task_id, expr)
    if not eval_err and isinstance(val, dict) and val.get("clicked"):
        return {"success": True, "method": "js-ancestor-click", "ref": ref_norm, "detail": val}
    return {"success": False, "error": "generic click fallback exhausted", "fallback": "click", "ref": ref_norm}


def try_type_fallback(
    task_id: str,
    ref: str,
    text: str,
    *,
    field_hint: Optional[str] = None,
    field_index: Optional[int] = None,
) -> Dict[str, Any]:
    ref_norm = ref if ref.startswith("@") else f"@{ref}"
    result = _run(task_id, "fill", [ref_norm, text])
    if result.get("success"):
        return {"success": True, "method": "agent-browser-fill-retry", "element": ref_norm}
    idx = field_index if field_index is not None else -1
    expr = _MODAL_FILL_JS % (_js_string(text), _js_string(field_hint or ""), json.dumps(idx))
    val, eval_err = _eval_json(task_id, expr)
    if not eval_err and isinstance(val, dict) and val.get("ok"):
        return {"success": True, "method": "js-modal-editable", "detail": val}
    if field_hint:
        fb = _run(task_id, "find", ["label", field_hint, "fill", text])
        if fb.get("success"):
            return {"success": True, "method": "agent-browser-find-label-fill", "field_hint": field_hint}
    role_fb = _run(task_id, "find", ["role", "textbox", "fill", text])
    if role_fb.get("success"):
        return {"success": True, "method": "agent-browser-find-role-textbox-fill"}
    return {
        "success": False,
        "error": result.get("error") or eval_err or "modal fill fallback failed",
        "fallback": "type",
        "element": ref_norm,
    }


def merge_fallback_result(primary: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(primary)
    out["success"] = True
    out["fallback_used"] = fallback.get("method") or fallback.get("fallback")
    out.update({k: v for k, v in fallback.items() if k not in ("success",)})
    return out
