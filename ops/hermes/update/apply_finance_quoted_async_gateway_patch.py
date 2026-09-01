"""
Patch gateway/run.py — F2B async quoted-reply gate pré-LLM.

Requer patch F2B_CHANNEL_PROPAGATION já aplicado.

  python3 ops/hermes/update/apply_finance_quoted_async_gateway_patch.py \\
      /home/will/.hermes/hermes-clean/gateway/run.py
"""

from __future__ import annotations

import sys
from pathlib import Path

MARKER = "F2B_QUOTED_ASYNC_GATE"
CHANNEL_MARKER = "F2B_CHANNEL_PROPAGATION"

INNER_AFTER_BIND_OLD = '''            _f2b_token = bind_turn_envelope(_f2b_envelope)
        except Exception:
            _f2b_token = None

        enabled_toolsets = self._resolve_enabled_toolsets_for_source(
            user_config, source, platform_key, message or "",
            reply_to_message_id=str(reply_to_message_id or ""),
        )
'''

INNER_AFTER_BIND_NEW = '''            _f2b_token = bind_turn_envelope(_f2b_envelope)
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


def apply(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        print(f"ALREADY_PATCHED={path}")
        return
    if CHANNEL_MARKER not in text:
        raise SystemExit(f"MISSING_PREREQ={CHANNEL_MARKER} path={path}")
    if INNER_AFTER_BIND_OLD not in text:
        raise SystemExit(f"PATCH_MISS=inner_after_bind path={path}")
    if text.count(INNER_AFTER_BIND_OLD) != 1:
        raise SystemExit("PATCH_AMBIGUOUS=inner_after_bind")
    text = text.replace(INNER_AFTER_BIND_OLD, INNER_AFTER_BIND_NEW, 1)
    path.write_text(text, encoding="utf-8")
    print(f"PATCHED={path}")
    print(f"MARKER={MARKER}=YES")


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
