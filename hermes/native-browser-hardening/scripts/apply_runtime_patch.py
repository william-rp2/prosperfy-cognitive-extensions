#!/usr/bin/env python3
"""Apply native-browser hardening to a Hermes install (idempotent). Run on Prosperfy host."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

HERMES_TOOLS = Path("/home/will/.hermes/hermes-v0213-stage/tools")
OVERLAY = Path(
    os.environ.get("HERMES_NATIVE_OVERLAY")
    or (Path(__file__).resolve().parents[1] / "tools")
)
BROWSER_TOOL = HERMES_TOOLS / "browser_tool.py"
MARKER = "# --- native-browser-hardening ---"


def main() -> int:
    src = OVERLAY / "browser_tool_generic_fallback.py"
    dst = HERMES_TOOLS / "browser_tool_generic_fallback.py"
    if not src.is_file():
        print("overlay missing:", src, file=sys.stderr)
        return 1
    shutil.copy2(src, dst)
    text = BROWSER_TOOL.read_text(encoding="utf-8")
    if MARKER in text:
        print("browser_tool.py already patched")
        return 0
    if 'name": "browser_press"' not in text:
        print("unexpected browser_tool.py layout", file=sys.stderr)
        return 1
    upload_schema = '''
    {
        "name": "browser_upload",
        "description": "Attach an authorized file (hidden file inputs / dropzones). Discovers input[type=file] generically.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "ref": {"type": "string"},
                "target_hint": {"type": "string"}
            },
            "required": ["file_path"]
        }
    },'''
    text = text.replace(
        '        "name": "browser_get_images",',
        upload_schema + '\n    {\n        "name": "browser_get_images",',
        1,
    )
    old_click = '''def browser_click(ref: str, task_id: Optional[str] = None) -> str:
    """Click the element ``ref`` (e.g. "@e5")."""
    if _is_camofox_mode():
        return _camofox("camofox_click", ref, task_id)
    ref = _at_ref(ref)
    return _guarded_action(task_id, "click", "click", [ref], {"clicked": ref}, f"Failed to click {ref}")'''
    new_click = '''def browser_click(ref: str, task_id: Optional[str] = None) -> str:
    """Click the element ``ref`` (e.g. "@e5")."""
    if _is_camofox_mode():
        return _camofox("camofox_click", ref, task_id)
    ref = _at_ref(ref)
    effective_task_id = _last_session_key(task_id or "default")
    blocked = _blocked_private_page_action(effective_task_id, "click")
    if blocked is not None:
        return blocked
    primary = _session._run_browser_command(effective_task_id, "click", [ref])
    if primary.get("success"):
        return _tool_response(primary, {"clicked": ref}, f"Failed to click {ref}")
    from tools.browser_tool_generic_fallback import _failure_suggests_missing_target, try_click_fallback
    err = str(primary.get("error") or "")
    if _failure_suggests_missing_target(err):
        fb = try_click_fallback(task_id or "default", ref)
        if fb.get("success"):
            return _dumps({"success": True, "clicked": ref, "fallback_used": fb.get("method"), **fb})
    return _failed_response(primary, f"Failed to click {ref}")'''
    if old_click not in text:
        print("browser_click block not found", file=sys.stderr)
        return 1
    text = text.replace(old_click, new_click, 1)
    old_type_tail = '''    if result.get("success"):
        response = {"success": True, "typed": display_text, "element": ref}
    else:
        response = _err(result.get("error", f"Failed to type into {ref}"))
    return _dumps(redact_browser_typed_text_for_display(_lp._copy_fallback_warning(response, result), text))'''
    new_type_tail = '''    if result.get("success"):
        response = {"success": True, "typed": display_text, "element": ref}
    else:
        from tools.browser_tool_generic_fallback import _failure_suggests_missing_target, try_type_fallback
        if _failure_suggests_missing_target(str(result.get("error") or "")):
            fb = try_type_fallback(task_id or "default", ref, text)
            if fb.get("success"):
                response = {"success": True, "typed": display_text, "element": ref, "fallback_used": fb.get("method"), **fb}
                return _dumps(redact_browser_typed_text_for_display(_lp._copy_fallback_warning(response, result), text))
        response = _err(result.get("error", f"Failed to type into {ref}"))
    return _dumps(redact_browser_typed_text_for_display(_lp._copy_fallback_warning(response, result), text))'''
    if old_type_tail not in text:
        print("browser_type tail not found", file=sys.stderr)
        return 1
    text = text.replace(old_type_tail, new_type_tail, 1)
    upload_fn = '''

def browser_upload(file_path: str, ref: Optional[str] = None, target_hint: Optional[str] = None, task_id: Optional[str] = None) -> str:
    """Upload authorized file via generic discovery."""
    from tools.browser_tool_generic_fallback import try_upload_fallback
    fb = try_upload_fallback(task_id or "default", file_path, ref=ref, target_hint=target_hint)
    if fb.get("success"):
        return _dumps({"success": True, **fb})
    return _dumps(_err(fb.get("error") or "upload failed"))
'''
    anchor = "def browser_scroll(direction: str, task_id: Optional[str] = None) -> str:"
    if anchor not in text:
        print("browser_scroll anchor missing", file=sys.stderr)
        return 1
    text = text.replace(anchor, upload_fn + "\n\n" + anchor, 1)
    table_line = '    ("browser_type", "⌨️", None, {"ref": "", "text": ""}),'
    if table_line not in text:
        print("tool table line missing", file=sys.stderr)
        return 1
    text = text.replace(
        table_line,
        table_line + '\n    ("browser_upload", "📎", None, {"file_path": "", "ref": None, "target_hint": None}),',
        1,
    )
    text = text.rstrip() + "\n" + MARKER + "\n"
    bak = BROWSER_TOOL.with_suffix(".py.bak-native-hardening")
    shutil.copy2(BROWSER_TOOL, bak)
    BROWSER_TOOL.write_text(text, encoding="utf-8")
    print("patched", BROWSER_TOOL, "backup", bak)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
