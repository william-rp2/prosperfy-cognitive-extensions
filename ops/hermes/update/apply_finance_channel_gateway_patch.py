"""
Patch gateway/run.py (hermes-clean) — F2B trusted channel envelope binding.

Aplicar no homolog:
  python3 ops/hermes/update/apply_finance_channel_gateway_patch.py \\
      /home/will/.hermes/hermes-clean/gateway/run.py

Idempotente: se marcadores F2B_CHANNEL já existirem, não reaplica.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

MARKER = "F2B_CHANNEL_PROPAGATION"

RESOLVE_OLD = '''        # Capability router (Sprint 0.7.8): gate determinístico pré-LLM.
        # NORMAL -> 0 tools (slim); CRON/SESSION_SEARCH/MEMORY/SKILLS ->
        # toolset especializado do turno. Sem classifier LLM.
        try:
            from capability_intelligence.capability_router import (
                resolve_specialist_route, route_toolsets, is_specialist,
            )
            if message:
                _route = resolve_specialist_route(message)
                _toolsets = route_toolsets(_route)
'''

RESOLVE_NEW = '''        # Capability router (Sprint 0.7.8): gate determinístico pré-LLM.
        # NORMAL -> 0 tools (slim); CRON/SESSION_SEARCH/MEMORY/SKILLS ->
        # toolset especializado do turno. Sem classifier LLM.
        # F2B_CHANNEL_PROPAGATION: reply_to + ContextEnvelope trusted.
        try:
            from capability_intelligence.capability_router import (
                resolve_specialist_route, route_toolsets, is_specialist,
            )
            from capability_intelligence.turn_context import (
                envelope_from_session_source,
                get_turn_envelope,
            )
            _reply_to = (reply_to_message_id or "").strip()
            _envelope = get_turn_envelope()
            if _envelope is None:
                _envelope = envelope_from_session_source(
                    source,
                    incoming_message_id=str(getattr(source, "message_id", "") or ""),
                    reply_to_message_id=_reply_to,
                )
            if not _reply_to:
                _reply_to = str(getattr(_envelope, "reply_to_message_id", "") or "")
            if message or _reply_to:
                _route = resolve_specialist_route(
                    message or "",
                    reply_to_message_id=_reply_to,
                    context_envelope=_envelope,
                )
                _toolsets = route_toolsets(_route)
'''

SIG_RESOLVE_OLD = '''    def _resolve_enabled_toolsets_for_source(
        self,
        user_config: dict,
        source: "SessionSource",
        platform_key: str,
        message: str = "",
    ) -> list:
'''

SIG_RESOLVE_NEW = '''    def _resolve_enabled_toolsets_for_source(
        self,
        user_config: dict,
        source: "SessionSource",
        platform_key: str,
        message: str = "",
        reply_to_message_id: str = "",
    ) -> list:
'''

INNER_TOOLSETS_OLD = '''        enabled_toolsets = self._resolve_enabled_toolsets_for_source(
            user_config, source, platform_key, message or ""
        )
'''

INNER_TOOLSETS_NEW = '''        # F2B_CHANNEL_PROPAGATION: bind trusted envelope for finance tools.
        _f2b_token = None
        try:
            from capability_intelligence.turn_context import (
                bind_turn_envelope,
                clear_turn_envelope,
                envelope_from_session_source,
            )
            clear_turn_envelope()
            _f2b_envelope = envelope_from_session_source(
                source,
                incoming_message_id=str(event_message_id or getattr(source, "message_id", "") or ""),
                reply_to_message_id=str(reply_to_message_id or ""),
            )
            _f2b_token = bind_turn_envelope(_f2b_envelope)
        except Exception:
            _f2b_token = None

        enabled_toolsets = self._resolve_enabled_toolsets_for_source(
            user_config, source, platform_key, message or "",
            reply_to_message_id=str(reply_to_message_id or ""),
        )
'''

# Insert reply_to into _run_agent / _run_agent_inner signatures (after message_type).
SIG_RUN_AGENT_OLD = '''        persist_user_display_kind: Optional[str] = None,
        message_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Profile-scoping wrapper around the agent run.
'''

SIG_RUN_AGENT_NEW = '''        persist_user_display_kind: Optional[str] = None,
        message_type: Optional[str] = None,
        reply_to_message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Profile-scoping wrapper around the agent run.
'''

SIG_INNER_OLD = '''        persist_user_display_kind: Optional[str] = None,
        message_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run the agent with the given message and context.
'''

SIG_INNER_NEW = '''        persist_user_display_kind: Optional[str] = None,
        message_type: Optional[str] = None,
        reply_to_message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run the agent with the given message and context.
'''

# Pass-through from _run_agent → _run_agent_inner (both multiplex branches)
PASS_OLD = '''                persist_user_display_kind=persist_user_display_kind,
                message_type=message_type,
            )
'''

PASS_NEW = '''                persist_user_display_kind=persist_user_display_kind,
                message_type=message_type,
                reply_to_message_id=reply_to_message_id,
            )
'''

CALL_SITE_OLD = '''            agent_result = await self._run_agent(
                message=message_text,
                context_prompt=context_prompt,
                history=history,
                source=source,
                session_id=_run_start_session_id,
                session_key=session_key,
                run_generation=run_generation,
                event_message_id=self._reply_anchor_for_event(event),
                channel_prompt=event.channel_prompt,
                moa_config=getattr(event, "_moa_config", None),
                persist_user_message=persist_user_message,
                persist_user_timestamp=persist_user_timestamp,
                persist_user_display_kind=persist_user_display_kind,
                message_type=event.message_type,
            )
'''

CALL_SITE_NEW = '''            agent_result = await self._run_agent(
                message=message_text,
                context_prompt=context_prompt,
                history=history,
                source=source,
                session_id=_run_start_session_id,
                session_key=session_key,
                run_generation=run_generation,
                event_message_id=self._reply_anchor_for_event(event),
                channel_prompt=event.channel_prompt,
                moa_config=getattr(event, "_moa_config", None),
                persist_user_message=persist_user_message,
                persist_user_timestamp=persist_user_timestamp,
                persist_user_display_kind=persist_user_display_kind,
                message_type=event.message_type,
                reply_to_message_id=getattr(event, "reply_to_message_id", None),
            )
'''


def apply(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if MARKER in text and "reply_to_message_id=getattr(event" in text:
        print(f"ALREADY_PATCHED={path}")
        return

    replacements = [
        (SIG_RESOLVE_OLD, SIG_RESOLVE_NEW, "sig_resolve"),
        (RESOLVE_OLD, RESOLVE_NEW, "resolve_body"),
        (SIG_RUN_AGENT_OLD, SIG_RUN_AGENT_NEW, "sig_run_agent"),
        (SIG_INNER_OLD, SIG_INNER_NEW, "sig_inner"),
        (PASS_OLD, PASS_NEW, "pass_through"),
        (INNER_TOOLSETS_OLD, INNER_TOOLSETS_NEW, "inner_toolsets"),
        (CALL_SITE_OLD, CALL_SITE_NEW, "call_site"),
    ]

    for old, new, label in replacements:
        count = text.count(old)
        if count == 0:
            # pass_through appears twice (multiplex on/off) — replace_all ok
            raise SystemExit(f"PATCH_MISS={label} path={path}")
        if label == "pass_through":
            if count < 2:
                raise SystemExit(f"PATCH_MISS={label} expected>=2 got={count}")
            text = text.replace(old, new)
        else:
            if count != 1:
                raise SystemExit(f"PATCH_AMBIGUOUS={label} count={count}")
            text = text.replace(old, new, 1)

    # Ensure finally clears envelope near end of successful toolsets binding —
    # wrap via try/finally is hard in this file; finance tools tolerate missing
    # envelope (fail-closed ACL). Still reset when token set at start of return paths
    # is complex; ContextVar is per-task so next turn rebinds. OK for asyncio.

    path.write_text(text, encoding="utf-8")
    print(f"PATCHED={path}")
    print(f"MARKER={MARKER}=YES")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: apply_finance_channel_gateway_patch.py <gateway/run.py>", file=sys.stderr)
        return 2
    apply(Path(sys.argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
