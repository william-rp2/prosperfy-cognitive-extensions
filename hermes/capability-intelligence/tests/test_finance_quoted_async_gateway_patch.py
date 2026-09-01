"""
tests/test_finance_quoted_async_gateway_patch.py — V2 + true eager boot contracts.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PATCH_SCRIPT = ROOT / "ops" / "hermes" / "update" / "apply_finance_quoted_async_gateway_patch.py"

sys.path.insert(0, str(PATCH_SCRIPT.parent))

from apply_finance_quoted_async_gateway_patch import (  # noqa: E402
    BOOT_ANCHOR,
    INNER_V1,
    INNER_V2,
    MARKER_BOOT,
    MARKER_V2,
    apply,
)


CHANNEL_STUB = '''        # F2B_CHANNEL_PROPAGATION: bind trusted envelope for finance tools.
            _f2b_token = bind_turn_envelope(_f2b_envelope)
        except Exception:
            _f2b_token = None

        enabled_toolsets = self._resolve_enabled_toolsets_for_source(
            user_config, source, platform_key, message or "",
            reply_to_message_id=str(reply_to_message_id or ""),
        )
'''

START_STUB = '''
class GatewayRunner:
    async def start(self) -> bool:
        """Start the gateway and all configured platform adapters."""
        logger.info("Starting Hermes Gateway...")
        try:
            faulthandler.enable()
        except Exception:
            pass
        logger.info("Connecting to %s...", "whatsapp")
'''


def _write(tmp_path: Path, body: str) -> Path:
    target = tmp_path / "run.py"
    target.write_text("F2B_CHANNEL_PROPAGATION\n" + body, encoding="utf-8")
    return target


def test_patch_fresh_install_v2_and_boot(tmp_path: Path):
    target = _write(tmp_path, START_STUB + "\n" + CHANNEL_STUB)
    apply(target)
    text = target.read_text(encoding="utf-8")
    assert MARKER_V2 in text
    assert MARKER_BOOT in text
    assert "ensure_finance_quoted_binding_ready()" in text
    assert text.count(MARKER_BOOT) == 1
    assert text.index("Starting Hermes Gateway") < text.index(MARKER_BOOT)
    assert text.index(MARKER_BOOT) < text.index("Connecting to")
    assert "except Exception:\n            _f2b_quoted = None" not in text


def test_upgrade_v1_removes_silent_swallow_and_adds_boot(tmp_path: Path):
    target = _write(tmp_path, START_STUB + "\n" + INNER_V1)
    apply(target)
    text = target.read_text(encoding="utf-8")
    assert MARKER_V2 in text
    assert MARKER_BOOT in text
    assert INNER_V1 not in text
    assert "except Exception:\n            _f2b_quoted = None" not in text


def test_v2_to_v2_plus_boot(tmp_path: Path):
    """Live path: V2 sem boot → adiciona SOMENTE boot hook."""
    target = _write(tmp_path, START_STUB + "\n" + INNER_V2)
    assert MARKER_V2 in target.read_text(encoding="utf-8")
    assert MARKER_BOOT not in target.read_text(encoding="utf-8")
    apply(target)
    text = target.read_text(encoding="utf-8")
    assert MARKER_V2 in text
    assert text.count(MARKER_V2) == 1
    assert text.count(MARKER_BOOT) == 1
    assert text.count("F2B_QUOTED_ASYNC_GATE_V2:") == 1


def test_second_apply_idempotent(tmp_path: Path):
    target = _write(tmp_path, START_STUB + "\n" + CHANNEL_STUB)
    apply(target)
    first = target.read_text(encoding="utf-8")
    apply(target)
    second = target.read_text(encoding="utf-8")
    assert first == second
    assert first.count(MARKER_BOOT) == 1
    assert first.count(MARKER_V2) == 1


def test_boot_anchor_miss_fails(tmp_path: Path):
    target = _write(tmp_path, INNER_V2)  # V2 ok, sem GatewayRunner.start
    with pytest.raises(SystemExit, match="BOOT_PATCH_MISS"):
        apply(target)


def test_boot_anchor_ambiguous_fails(tmp_path: Path):
    dup = START_STUB + "\n" + 'logger.info("Starting Hermes Gateway...")\n' + INNER_V2
    target = _write(tmp_path, dup)
    assert target.read_text(encoding="utf-8").count(BOOT_ANCHOR) > 1
    with pytest.raises(SystemExit, match="BOOT_PATCH_AMBIGUOUS"):
        apply(target)


def test_boot_marker_already_present_idempotent(tmp_path: Path):
    target = _write(tmp_path, START_STUB + "\n" + CHANNEL_STUB)
    apply(target)
    text_once = target.read_text(encoding="utf-8")
    apply(target)
    assert target.read_text(encoding="utf-8") == text_once
