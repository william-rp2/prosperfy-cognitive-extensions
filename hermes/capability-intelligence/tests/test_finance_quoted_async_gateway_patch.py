"""
tests/test_finance_quoted_async_gateway_patch.py — V2 patch content contracts.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PATCH_SCRIPT = ROOT / "ops" / "hermes" / "update" / "apply_finance_quoted_async_gateway_patch.py"

sys.path.insert(0, str(PATCH_SCRIPT.parent))

from apply_finance_quoted_async_gateway_patch import (  # noqa: E402
    INNER_V1,
    INNER_V2,
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


def test_patch_fresh_install_has_eager_boot_and_no_silent_except(tmp_path: Path):
    target = tmp_path / "run.py"
    target.write_text("F2B_CHANNEL_PROPAGATION\n" + CHANNEL_STUB, encoding="utf-8")
    apply(target)
    text = target.read_text(encoding="utf-8")
    assert MARKER_V2 in text
    assert "ensure_finance_quoted_binding_ready()" in text
    assert "F2B_ACTIVE_BINDING_PRESENT" in text
    assert "BINDING_NOT_INITIALIZED" in text
    assert "F2B_GATE_EXCEPTION" in text
    assert "except Exception:\n            _f2b_quoted = None" not in text
    assert "except Exception as _f2b_gate_exc:" in text


def test_upgrade_v1_removes_silent_swallow(tmp_path: Path):
    target = tmp_path / "run.py"
    target.write_text("F2B_CHANNEL_PROPAGATION\n" + INNER_V1, encoding="utf-8")
    apply(target)
    text = target.read_text(encoding="utf-8")
    assert MARKER_V2 in text
    assert INNER_V1 not in text
    assert "ensure_finance_quoted_binding_ready()" in text
    assert "except Exception:\n            _f2b_quoted = None" not in text
