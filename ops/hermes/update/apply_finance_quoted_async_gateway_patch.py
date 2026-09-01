"""
Patch gateway/run.py — F2B async quoted-reply gate pré-LLM (V2).

V2: eager binding boot + structured observability (sem silent swallow).

Requer patch F2B_CHANNEL_PROPAGATION já aplicado.

  python3 ops/hermes/update/apply_finance_quoted_async_gateway_patch.py \\
      /home/will/.hermes/hermes-clean/gateway/run.py
"""

from __future__ import annotations

import sys
from pathlib import Path

MARKER = "F2B_QUOTED_ASYNC_GATE"
MARKER_V2 = "F2B_QUOTED_ASYNC_GATE_V2"
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

        # F2B_QUOTED_ASYNC_GATE_V2: eager boot + durable lookup + observability.
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
            # Eager: binding pronto ANTES do roteamento textual / LLM.
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


def apply(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if CHANNEL_MARKER not in text:
        raise SystemExit(f"MISSING_PREREQ={CHANNEL_MARKER} path={path}")

    if MARKER_V2 in text:
        print(f"ALREADY_PATCHED_V2={path}")
        return

    if INNER_V1 in text:
        text = text.replace(INNER_V1, INNER_V2, 1)
        path.write_text(text, encoding="utf-8")
        print(f"UPGRADED_V1_TO_V2={path}")
        print(f"MARKER={MARKER_V2}=YES")
        return

    if INNER_AFTER_BIND_OLD not in text:
        raise SystemExit(f"PATCH_MISS=inner_after_bind path={path}")
    if text.count(INNER_AFTER_BIND_OLD) != 1:
        raise SystemExit("PATCH_AMBIGUOUS=inner_after_bind")
    text = text.replace(INNER_AFTER_BIND_OLD, INNER_V2, 1)
    path.write_text(text, encoding="utf-8")
    print(f"PATCHED={path}")
    print(f"MARKER={MARKER_V2}=YES")


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
