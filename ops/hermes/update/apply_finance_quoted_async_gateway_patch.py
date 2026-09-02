"""
Patch gateway/run.py — F2B async quoted-reply gate (V2) + true eager boot.

Markers:
  F2B_QUOTED_ASYNC_GATE_V2   — per-message gate + observability (+ ensure recovery)
  F2B_QUOTED_BOOT_EAGER_V1   — once-per-process install in GatewayRunner.start

Boot strategy: INSERT immediately after the unique anchor line
  `        logger.info("Starting Hermes Gateway...")`
without depending on faulthandler or intervening comments.

Requer patch F2B_CHANNEL_PROPAGATION já aplicado.

  python3 ops/hermes/update/apply_finance_quoted_async_gateway_patch.py \\
      /home/will/.hermes/hermes-clean/gateway/run.py
"""

from __future__ import annotations

import sys
from pathlib import Path

MARKER = "F2B_QUOTED_ASYNC_GATE"
MARKER_V2 = "F2B_QUOTED_ASYNC_GATE_V2"
MARKER_BOOT = "F2B_QUOTED_BOOT_EAGER_V1"
CHANNEL_MARKER = "F2B_CHANNEL_PROPAGATION"

# Pré-V1 (após channel patch, antes do quoted gate).
INNER_AFTER_BIND_OLD = '''            _f2b_token = bind_turn_envelope(_f2b_envelope)
        except Exception:
            _f2b_token = None

        enabled_toolsets = self._resolve_enabled_toolsets_for_source(
            user_config, source, platform_key, message or "",
            reply_to_message_id=str(reply_to_message_id or ""),
        )
'''

# V1 (silent except) — upgrade target.
INNER_V1 = '''            _f2b_token = bind_turn_envelope(_f2b_envelope)
        except Exception:
            _f2b_token = None
            _f2b_envelope = None

        # F2B_QUOTED_ASYNC_GATE: durable lookup + bind_reply antes do LLM.
        _f2b_quoted = None
        try:
            if _f2b_envelope is not None and str(reply_to_message_id or "").strip():
                from capability_intelligence.finance_quoted_gate import (
                    try_handle_quoted_finance_reply,
                )
                from capability_intelligence.finance_reply_binding import (
                    get_active_finance_reply_binding,
                )
                _f2b_binding = get_active_finance_reply_binding()
                if _f2b_binding is not None:
                    _f2b_quoted = await try_handle_quoted_finance_reply(
                        _f2b_binding,
                        message_text=message or "",
                        envelope=_f2b_envelope,
                    )
        except Exception:
            _f2b_quoted = None

        if (
            _f2b_quoted is not None
            and getattr(_f2b_quoted, "skip_llm", False)
            and getattr(_f2b_quoted, "user_message", None) is not None
        ):
            import logging as _f2b_log
            _f2b_log.getLogger("hermes.capability_router").info(
                "CAPABILITY_ROUTE=%s QUOTED_PATH=FINANCE LLM_SKIPPED=YES DURABLE_LOOKUP=%s",
                getattr(_f2b_quoted, "route", "FINANCE"),
                getattr(_f2b_quoted, "durable_lookup_called", False),
            )
            return {
                "final_response": _f2b_quoted.user_message,
                "messages": list(history or []),
                "api_calls": 0,
                "completed": True,
                "failed": False,
                "interrupted": False,
            }

        enabled_toolsets = self._resolve_enabled_toolsets_for_source(
            user_config, source, platform_key, message or "",
            reply_to_message_id=str(reply_to_message_id or ""),
        )
'''

INNER_V2 = '''            _f2b_token = bind_turn_envelope(_f2b_envelope)
        except Exception:
            _f2b_token = None
            _f2b_envelope = None

        # F2B_QUOTED_ASYNC_GATE_V2: durable lookup + observability (+ ensure recovery).
        _f2b_quoted = None
        _f2b_corr = "none"
        try:
            import logging as _f2b_log
            from capability_intelligence.finance_quoted_boot import (
                ensure_finance_quoted_binding_ready,
                f2b_fingerprint,
            )
            _f2b_corr = f2b_fingerprint(
                str(event_message_id or reply_to_message_id or "")
            )
            _f2b_log.getLogger("hermes.f2b").info(
                "F2B_QUOTE_GATE_START corr=%s", _f2b_corr
            )
            # Idempotent recovery: boot já instalou; aqui só reusa / repara.
            ensure_finance_quoted_binding_ready()
            _f2b_reply_present = bool(str(reply_to_message_id or "").strip())
            _f2b_log.getLogger("hermes.f2b").info(
                "F2B_REPLY_TO_PRESENT=%s corr=%s",
                "YES" if _f2b_reply_present else "NO",
                _f2b_corr,
            )
            if _f2b_envelope is not None and _f2b_reply_present:
                from capability_intelligence.finance_quoted_gate import (
                    try_handle_quoted_finance_reply,
                )
                from capability_intelligence.finance_reply_binding import (
                    get_active_finance_reply_binding,
                )
                _f2b_binding = get_active_finance_reply_binding()
                _f2b_log.getLogger("hermes.f2b").info(
                    "F2B_ACTIVE_BINDING_PRESENT=%s corr=%s",
                    "YES" if _f2b_binding is not None else "NO",
                    _f2b_corr,
                )
                if _f2b_binding is None:
                    _f2b_log.getLogger("hermes.f2b").warning(
                        "F2B_FALLTHROUGH_REASON=BINDING_NOT_INITIALIZED "
                        "QUOTED_GATE_OUTCOME=BINDING_NOT_READY corr=%s",
                        _f2b_corr,
                    )
                else:
                    _f2b_quoted = await try_handle_quoted_finance_reply(
                        _f2b_binding,
                        message_text=message or "",
                        envelope=_f2b_envelope,
                    )
                    _f2b_log.getLogger("hermes.f2b").info(
                        "QUOTED_GATE_OUTCOME=%s F2B_SKIP_LLM=%s corr=%s",
                        getattr(_f2b_quoted, "gate_outcome", ""),
                        "YES"
                        if getattr(_f2b_quoted, "skip_llm", False)
                        else "NO",
                        _f2b_corr,
                    )
            elif not _f2b_reply_present:
                _f2b_log.getLogger("hermes.f2b").info(
                    "QUOTED_GATE_OUTCOME=NO_REPLY_ID corr=%s", _f2b_corr
                )
        except Exception as _f2b_gate_exc:
            import logging as _f2b_log
            _f2b_log.getLogger("hermes.f2b").warning(
                "F2B_GATE_EXCEPTION type=%s stage=quoted_gate corr=%s",
                type(_f2b_gate_exc).__name__,
                _f2b_corr,
            )
            _f2b_quoted = None

        if (
            _f2b_quoted is not None
            and getattr(_f2b_quoted, "skip_llm", False)
            and getattr(_f2b_quoted, "user_message", None) is not None
        ):
            import logging as _f2b_log
            _f2b_log.getLogger("hermes.capability_router").info(
                "CAPABILITY_ROUTE=%s QUOTED_PATH=FINANCE LLM_SKIPPED=YES "
                "DURABLE_LOOKUP=%s QUOTED_GATE_OUTCOME=%s",
                getattr(_f2b_quoted, "route", "FINANCE"),
                getattr(_f2b_quoted, "durable_lookup_called", False),
                getattr(_f2b_quoted, "gate_outcome", ""),
            )
            return {
                "final_response": _f2b_quoted.user_message,
                "messages": list(history or []),
                "api_calls": 0,
                "completed": True,
                "failed": False,
                "interrupted": False,
            }

        enabled_toolsets = self._resolve_enabled_toolsets_for_source(
            user_config, source, platform_key, message or "",
            reply_to_message_id=str(reply_to_message_id or ""),
        )
'''

BOOT_ANCHOR = '        logger.info("Starting Hermes Gateway...")'

# Inserted immediately AFTER the unique anchor line. Does not consume/replace
# whatever follows (comments, blank lines, faulthandler, …).
BOOT_HOOK_INSERT = '''
        # F2B_QUOTED_BOOT_EAGER_V1
        try:
            from capability_intelligence.finance_quoted_boot import (
                ensure_finance_quoted_binding_ready,
            )
            _f2b_boot_binding = ensure_finance_quoted_binding_ready()
            if _f2b_boot_binding is None:
                logger.warning(
                    "FINANCE_QUOTED_BINDING_READY=NO "
                    "F2B_FALLTHROUGH_REASON=BINDING_BOOT_FAILED"
                )
        except Exception as _f2b_boot_exc:
            logger.warning(
                "F2B_GATE_EXCEPTION type=%s stage=boot",
                type(_f2b_boot_exc).__name__,
            )
'''


def _ensure_v2(text: str) -> tuple[str, str]:
    """Return (new_text, status) where status is already|upgraded_v1|patched|miss."""
    if MARKER_V2 in text:
        return text, "already_v2"

    if INNER_V1 in text:
        if text.count(INNER_V1) != 1:
            raise SystemExit("PATCH_AMBIGUOUS=inner_v1")
        return text.replace(INNER_V1, INNER_V2, 1), "upgraded_v1"

    if INNER_AFTER_BIND_OLD not in text:
        raise SystemExit("PATCH_MISS=inner_after_bind")
    if text.count(INNER_AFTER_BIND_OLD) != 1:
        raise SystemExit("PATCH_AMBIGUOUS=inner_after_bind")
    return text.replace(INNER_AFTER_BIND_OLD, INNER_V2, 1), "patched_v2"


def _ensure_boot(text: str) -> tuple[str, str]:
    """Insert boot hook immediately after the unique GatewayRunner.start anchor.

    Raises SystemExit with BOOT_PATCH_MISS / BOOT_PATCH_AMBIGUOUS.
    Does not depend on faulthandler or intervening comments.
    """
    if MARKER_BOOT in text:
        return text, "already_boot"

    anchor_count = text.count(BOOT_ANCHOR)
    if anchor_count == 0:
        raise SystemExit("BOOT_PATCH_MISS")
    if anchor_count > 1:
        raise SystemExit("BOOT_PATCH_AMBIGUOUS")

    idx = text.index(BOOT_ANCHOR)
    line_end = text.find("\n", idx)
    if line_end == -1:
        insert_at = len(text)
    else:
        insert_at = line_end + 1

    new_text = text[:insert_at] + BOOT_HOOK_INSERT + text[insert_at:]
    return new_text, "patched_boot"


def apply(path: Path) -> None:
    """Apply V2 + boot patches atomically (single write after both gates PASS)."""
    text = path.read_text(encoding="utf-8")
    if CHANNEL_MARKER not in text:
        raise SystemExit(f"MISSING_PREREQ={CHANNEL_MARKER} path={path}")

    original = text
    # Compute full result in memory first — never write a partial patch.
    text, v2_status = _ensure_v2(text)
    text, boot_status = _ensure_boot(text)

    if text != original:
        path.write_text(text, encoding="utf-8")

    if v2_status == "already_v2":
        print(f"ALREADY_PATCHED_V2={path}")
    elif v2_status == "upgraded_v1":
        print(f"UPGRADED_V1_TO_V2={path}")
        print(f"MARKER={MARKER_V2}=YES")
    else:
        print(f"PATCHED_V2={path}")
        print(f"MARKER={MARKER_V2}=YES")

    if boot_status == "already_boot":
        print(f"ALREADY_PATCHED_BOOT={path}")
    else:
        print(f"PATCHED_BOOT={path}")
        print(f"MARKER={MARKER_BOOT}=YES")

    if text == original:
        print("IDEMPOTENT=YES")


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "usage: apply_finance_quoted_async_gateway_patch.py <gateway/run.py>",
            file=sys.stderr,
        )
        return 2
    apply(Path(sys.argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
