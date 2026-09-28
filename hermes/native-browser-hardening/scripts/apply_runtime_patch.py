#!/usr/bin/env python3
"""Apply native-browser hardening to a Hermes install (idempotent). Run on Prosperfy host."""

from __future__ import annotations

import os
import re
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
MARKER_V2 = "# --- native-browser-hardening-v2 ---"


NEW_CLICK = '''def browser_click(ref: str, task_id: Optional[str] = None, target_hint: Optional[str] = None) -> str:
    """Click the element ``ref`` (e.g. "@e5"). Use ref "@?" with target_hint when no usable @ref."""
    if _is_camofox_mode():
        return _camofox("camofox_click", ref, task_id)
    ref = _at_ref(ref)
    effective_task_id = _last_session_key(task_id or "default")
    blocked = _blocked_private_page_action(effective_task_id, "click")
    if blocked is not None:
        return blocked
    from tools.browser_tool_generic_fallback import (
        failure_suggests_locate_or_click_failure,
        is_discovery_click_ref,
        is_unknown_ref_error,
        try_click_discovery,
        try_click_fallback,
    )
    if is_discovery_click_ref(ref, target_hint):
        fb = try_click_discovery(task_id or "default", (target_hint or "").strip())
        if fb.get("success"):
            return _dumps({"success": True, "clicked": ref, "fallback_used": fb.get("method"), **fb})
        return _dumps(_err(fb.get("error") or "discovery click failed"))
    primary = _session._run_browser_command(effective_task_id, "click", [ref])
    if primary.get("success"):
        return _tool_response(primary, {"clicked": ref}, f"Failed to click {ref}")
    err = str(primary.get("error") or "")
    if is_unknown_ref_error(err):
        if target_hint and str(target_hint).strip():
            fb = try_click_discovery(task_id or "default", str(target_hint).strip())
            if fb.get("success"):
                return _dumps({"success": True, "clicked": ref, "fallback_used": fb.get("method"), **fb})
        return _failed_response(primary, f"Failed to click {ref}")
    if failure_suggests_locate_or_click_failure(err):
        fb = try_click_fallback(task_id or "default", ref)
        if fb.get("success"):
            return _dumps({"success": True, "clicked": ref, "fallback_used": fb.get("method"), **fb})
    return _failed_response(primary, f"Failed to click {ref}")'''


NEW_TYPE_TAIL = '''    if result.get("success"):
        response = {"success": True, "typed": display_text, "element": ref}
    else:
        from tools.browser_tool_generic_fallback import (
            failure_suggests_locate_or_click_failure,
            is_unknown_ref_error,
            try_type_fallback,
        )
        err = str(result.get("error") or "")
        if is_unknown_ref_error(err) or failure_suggests_locate_or_click_failure(err):
            fb = try_type_fallback(
                task_id or "default",
                ref,
                text,
                field_hint=field_hint,
            )
            if fb.get("success"):
                response = {"success": True, "typed": display_text, "element": ref, "fallback_used": fb.get("method"), **fb}
                return _dumps(redact_browser_typed_text_for_display(_lp._copy_fallback_warning(response, result), text))
            response = _err(fb.get("error") or result.get("error", f"Failed to type into {ref}"))
            return _dumps(redact_browser_typed_text_for_display(_lp._copy_fallback_warning(response, result), text))
        response = _err(result.get("error", f"Failed to type into {ref}"))
    return _dumps(redact_browser_typed_text_for_display(_lp._copy_fallback_warning(response, result), text))'''


def _replace_browser_click(text: str) -> str:
    pattern = r"def browser_click\(ref: str.*?\n(?=def browser_type\()"
    if not re.search(pattern, text, flags=re.DOTALL):
        raise ValueError("browser_click block not found")
    return re.sub(pattern, NEW_CLICK + "\n\n", text, count=1, flags=re.DOTALL)


def _replace_browser_type_signature(text: str) -> str:
    old = 'def browser_type(ref: str, text: str, task_id: Optional[str] = None) -> str:'
    new = 'def browser_type(ref: str, text: str, task_id: Optional[str] = None, field_hint: Optional[str] = None) -> str:'
    if old in text:
        return text.replace(old, new, 1)
    if new in text:
        return text
    raise ValueError("browser_type signature not found")


def _replace_type_fallback_tail(text: str) -> str:
    pattern = (
        r"    if result\.get\(\"success\"\):\n"
        r"        response = \{\"success\": True, \"typed\": display_text, \"element\": ref\}\n"
        r"    else:\n"
        r"        from tools\.browser_tool_generic_fallback import.*?"
        r"    return _dumps\(redact_browser_typed_text_for_display\(_lp\._copy_fallback_warning\(response, result\), text\)\)"
    )
    if not re.search(pattern, text, flags=re.DOTALL):
        raise ValueError("browser_type fallback tail not found")
    return re.sub(pattern, NEW_TYPE_TAIL, text, count=1, flags=re.DOTALL)


def _dedupe_browser_type_tail(text: str) -> str:
    dup = (
        r"(    return _dumps\(redact_browser_typed_text_for_display\(_lp\._copy_fallback_warning\(response, result\), text\)\))\n"
        r"        response = _err\(result\.get\(\"error\", f\"Failed to type into \{ref\}\"\)\)\n"
        r"    return _dumps\(redact_browser_typed_text_for_display\(_lp\._copy_fallback_warning\(response, result\), text\)\)\n"
    )
    return re.sub(dup, r"\1\n", text, count=1)


def upgrade_v2(text: str) -> str:
    text = _replace_browser_click(text)
    text = _replace_browser_type_signature(text)
    text = _replace_type_fallback_tail(text)
    text = _dedupe_browser_type_tail(text)
    if MARKER_V2 not in text:
        text = text.rstrip() + "\n" + MARKER_V2 + "\n"
    return text


def main() -> int:
    src = OVERLAY / "browser_tool_generic_fallback.py"
    dst = HERMES_TOOLS / "browser_tool_generic_fallback.py"
    if not src.is_file():
        print("overlay missing:", src, file=sys.stderr)
        return 1
    shutil.copy2(src, dst)
    if not BROWSER_TOOL.is_file():
        print("browser_tool.py missing:", BROWSER_TOOL, file=sys.stderr)
        return 1
    text = BROWSER_TOOL.read_text(encoding="utf-8")
    if MARKER in text:
        try:
            text = upgrade_v2(text)
            BROWSER_TOOL.write_text(text, encoding="utf-8")
            print("upgraded browser_tool.py to v2 fallback; overlay copied")
        except ValueError as exc:
            print("upgrade skipped:", exc, file=sys.stderr)
        return 0
    if 'name": "browser_press"' not in text:
        print("unexpected browser_tool.py layout", file=sys.stderr)
        return 1
    upload_schema = '''    {
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
    get_images_anchor = '''    {
        "name": "browser_get_images",'''
    if get_images_anchor not in text:
        print("browser_get_images anchor not found", file=sys.stderr)
        return 1
    text = text.replace(get_images_anchor, upload_schema + "\n" + get_images_anchor, 1)
    old_click = '''def browser_click(ref: str, task_id: Optional[str] = None) -> str:
    """Click the element ``ref`` (e.g. "@e5")."""
    if _is_camofox_mode():
        return _camofox("camofox_click", ref, task_id)
    ref = _at_ref(ref)
    return _guarded_action(task_id, "click", "click", [ref], {"clicked": ref}, f"Failed to click {ref}")'''
    if old_click not in text:
        print("browser_click block not found for initial patch", file=sys.stderr)
        return 1
    text = text.replace(old_click, NEW_CLICK, 1)
    text = _replace_browser_type_signature(text)
    old_type_tail = '''    if result.get("success"):
        response = {"success": True, "typed": display_text, "element": ref}
    else:
        response = _err(result.get("error", f"Failed to type into {ref}"))
    return _dumps(redact_browser_typed_text_for_display(_lp._copy_fallback_warning(response, result), text))'''
    if old_type_tail not in text:
        print("browser_type tail not found", file=sys.stderr)
        return 1
    text = text.replace(old_type_tail, NEW_TYPE_TAIL, 1)
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
    text = text.rstrip() + "\n" + MARKER + "\n" + MARKER_V2 + "\n"
    bak = BROWSER_TOOL.with_suffix(".py.bak-native-hardening")
    shutil.copy2(BROWSER_TOOL, bak)
    BROWSER_TOOL.write_text(text, encoding="utf-8")
    print("patched", BROWSER_TOOL, "backup", bak)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
