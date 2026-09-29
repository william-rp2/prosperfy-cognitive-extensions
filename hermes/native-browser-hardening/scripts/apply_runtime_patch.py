#!/usr/bin/env python3
"""Apply native-browser hardening to a Hermes install (idempotent). Run on Prosperfy host."""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
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
        is_discovery_ref_token,
        is_unknown_ref_error,
        try_click_discovery,
        try_click_fallback,
    )
    if is_discovery_ref_token(ref) and not (target_hint and str(target_hint).strip()):
        return _dumps(_err("target_hint is required when ref is @? (discovery click without native @ref)"))
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


NEW_UPLOAD = '''def browser_upload(file_path: str, ref: Optional[str] = None, target_hint: Optional[str] = None, task_id: Optional[str] = None) -> str:
    """Upload authorized file via generic discovery."""
    effective_task_id = _last_session_key(task_id or "default")
    blocked = _blocked_private_page_action(effective_task_id, "upload")
    if blocked is not None:
        return blocked
    from tools.browser_tool_generic_fallback import try_upload_fallback
    fb = try_upload_fallback(task_id or "default", file_path, ref=ref, target_hint=target_hint)
    if fb.get("success"):
        return _dumps({"success": True, **fb})
    return _dumps(_err(fb.get("error") or "upload failed"))'''


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


def verify_patched_browser_tool(text: str) -> None:
    """Fail closed if patched browser_tool.py is missing required contracts."""
    required = (
        'def browser_upload(',
        '_blocked_private_page_action(effective_task_id, "upload")',
        '"target_hint"',
        '"field_hint"',
        'def browser_click(ref: str, task_id: Optional[str] = None, target_hint: Optional[str] = None)',
        'def browser_type(ref: str, text: str, task_id: Optional[str] = None, field_hint: Optional[str] = None)',
        '("browser_upload",',
        MARKER,
    )
    missing = [token for token in required if token not in text]
    if missing:
        raise ValueError("patched browser_tool.py missing: " + ", ".join(missing))


def _replace_browser_click(text: str) -> str:
    pattern = r"def browser_click\(ref: str.*?\n(?=def browser_type\()"
    if not re.search(pattern, text, flags=re.DOTALL):
        raise ValueError("browser_click block not found")
    return re.sub(pattern, NEW_CLICK + "\n\n", text, count=1, flags=re.DOTALL)


def _replace_browser_upload(text: str) -> str:
    pattern = r"def browser_upload\(file_path: str.*?\n(?=def browser_scroll\()"
    if not re.search(pattern, text, flags=re.DOTALL):
        raise ValueError("browser_upload block not found")
    return re.sub(pattern, NEW_UPLOAD + "\n\n", text, count=1, flags=re.DOTALL)


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


def _patch_tool_schemas(text: str) -> str:
    click_old = '''        "name": "browser_click",
        "description": "Click on an element identified by its ref ID from the snapshot (e.g., '@e5'). The ref IDs are shown in square brackets in the snapshot output. Requires browser_navigate and browser_snapshot to be called first.",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    "description": "The element reference from the snapshot (e.g., '@e5', '@e12')"
                }
            },
            "required": ["ref"]
        }
    },'''
    click_new = '''        "name": "browser_click",
        "description": "Click on an element identified by its ref ID from the snapshot (e.g., '@e5'). When no usable @ref exists, use ref '@?' plus target_hint (visible label/text). Requires browser_navigate and browser_snapshot first.",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    "description": "Element reference from snapshot (e.g., '@e5') or '@?' for discovery click"
                },
                "target_hint": {
                    "type": "string",
                    "description": "Semantic hint for discovery click (required with ref '@?')"
                }
            },
            "required": ["ref"]
        }
    },'''
    type_old = '''                "text": {
                    "type": "string", "description": "The text to type into the field"
                }
            },
            "required": ["ref", "text"]
        }
    },
    {
        "name": "browser_scroll",'''
    type_new = '''                "text": {
                    "type": "string", "description": "The text to type into the field"
                },
                "field_hint": {
                    "type": "string",
                    "description": "When fill fails inside a dialog, hint to pick the correct editable (label/name/text)"
                }
            },
            "required": ["ref", "text"]
        }
    },
    {
        "name": "browser_scroll",'''
    if click_old in text:
        text = text.replace(click_old, click_new, 1)
    if type_old in text:
        text = text.replace(type_old, type_new, 1)
    click_row_old = '    ("browser_click", "👆", None, {"ref": ""}),'
    click_row_new = '    ("browser_click", "👆", None, {"ref": "", "target_hint": None}),'
    type_row_old = '    ("browser_type", "⌨️", None, {"ref": "", "text": ""}),'
    type_row_new = '    ("browser_type", "⌨️", None, {"ref": "", "text": "", "field_hint": None}),'
    if click_row_old in text:
        text = text.replace(click_row_old, click_row_new, 1)
    if type_row_old in text:
        text = text.replace(type_row_old, type_row_new, 1)
    return text


def upgrade_v2(text: str) -> str:
    text = _replace_browser_click(text)
    text = _replace_browser_upload(text)
    text = _replace_browser_type_signature(text)
    text = _replace_type_fallback_tail(text)
    text = _dedupe_browser_type_tail(text)
    text = _patch_tool_schemas(text)
    if MARKER_V2 not in text:
        text = text.rstrip() + "\n" + MARKER_V2 + "\n"
    return text


def _apply_initial_patch(text: str) -> str:
    if 'name": "browser_press"' not in text:
        raise ValueError("unexpected browser_tool.py layout")
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
        raise ValueError("browser_get_images anchor not found")
    text = text.replace(get_images_anchor, upload_schema + "\n" + get_images_anchor, 1)
    old_click = '''def browser_click(ref: str, task_id: Optional[str] = None) -> str:
    """Click the element ``ref`` (e.g. "@e5")."""
    if _is_camofox_mode():
        return _camofox("camofox_click", ref, task_id)
    ref = _at_ref(ref)
    return _guarded_action(task_id, "click", "click", [ref], {"clicked": ref}, f"Failed to click {ref}")'''
    if old_click not in text:
        raise ValueError("browser_click block not found for initial patch")
    text = text.replace(old_click, NEW_CLICK, 1)
    text = _replace_browser_type_signature(text)
    old_type_tail = '''    if result.get("success"):
        response = {"success": True, "typed": display_text, "element": ref}
    else:
        response = _err(result.get("error", f"Failed to type into {ref}"))
    return _dumps(redact_browser_typed_text_for_display(_lp._copy_fallback_warning(response, result), text))'''
    if old_type_tail not in text:
        raise ValueError("browser_type tail not found")
    text = text.replace(old_type_tail, NEW_TYPE_TAIL, 1)
    anchor = "def browser_scroll(direction: str, task_id: Optional[str] = None) -> str:"
    if anchor not in text:
        raise ValueError("browser_scroll anchor missing")
    text = text.replace(anchor, NEW_UPLOAD + "\n\n" + anchor, 1)
    click_row = '    ("browser_click", "👆", None, {"ref": ""}),'
    type_row = '    ("browser_type", "⌨️", None, {"ref": "", "text": ""}),'
    if click_row in text:
        text = text.replace(
            click_row,
            '    ("browser_click", "👆", None, {"ref": "", "target_hint": None}),',
            1,
        )
    if type_row in text:
        text = text.replace(
            type_row,
            '    ("browser_type", "⌨️", None, {"ref": "", "text": "", "field_hint": None}),',
            1,
        )
    upload_after = '    ("browser_type", "⌨️", None, {"ref": "", "text": "", "field_hint": None}),'
    if upload_after not in text:
        raise ValueError("tool table line missing")
    text = text.replace(
        upload_after,
        upload_after + '\n    ("browser_upload", "📎", None, {"file_path": "", "ref": None, "target_hint": None}),',
        1,
    )
    text = _patch_tool_schemas(text)
    text = text.rstrip() + "\n" + MARKER + "\n" + MARKER_V2 + "\n"
    return text


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _deploy_overlay_and_browser_tool(overlay_src: Path, overlay_dst: Path, patched_text: str) -> None:
    verify_patched_browser_tool(patched_text)
    shutil.copy2(overlay_src, overlay_dst)
    if BROWSER_TOOL.is_file() and not BROWSER_TOOL.with_suffix(".py.bak-native-hardening").is_file():
        shutil.copy2(BROWSER_TOOL, BROWSER_TOOL.with_suffix(".py.bak-native-hardening"))
    _atomic_write(BROWSER_TOOL, patched_text)


def main() -> int:
    src = OVERLAY / "browser_tool_generic_fallback.py"
    dst = HERMES_TOOLS / "browser_tool_generic_fallback.py"
    if not src.is_file():
        print("overlay missing:", src, file=sys.stderr)
        return 1
    if not BROWSER_TOOL.is_file():
        print("browser_tool.py missing:", BROWSER_TOOL, file=sys.stderr)
        return 1

    original = BROWSER_TOOL.read_text(encoding="utf-8")
    try:
        if MARKER in original:
            patched = upgrade_v2(original)
        else:
            patched = _apply_initial_patch(original)
        verify_patched_browser_tool(patched)
    except ValueError as exc:
        print("patch validation failed:", exc, file=sys.stderr)
        return 1

    try:
        _deploy_overlay_and_browser_tool(src, dst, patched)
    except ValueError as exc:
        print("deploy failed:", exc, file=sys.stderr)
        return 1

    if MARKER in original:
        print("upgraded browser_tool.py to v2 fallback; overlay copied")
    else:
        print("patched", BROWSER_TOOL, "backup", BROWSER_TOOL.with_suffix(".py.bak-native-hardening"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
