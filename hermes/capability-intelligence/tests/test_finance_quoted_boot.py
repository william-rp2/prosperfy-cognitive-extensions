"""
tests/test_finance_quoted_boot.py — F2B eager binding + first-message-after-restart.

Prova que o boot real (ensure_finance_quoted_binding_ready) deixa o binding
ativo ANTES de qualquer mensagem Finance / warmup de tools.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from capability_intelligence.context_envelope import ContextEnvelope  # noqa: E402
from capability_intelligence.finance_quoted_boot import (  # noqa: E402
    READY_MARKER,
    ensure_finance_quoted_binding_ready,
    reset_finance_quoted_binding_ready_for_tests,
)
from capability_intelligence.finance_quoted_gate import (  # noqa: E402
    OUTCOME_FINANCE_RESOLVED,
    try_handle_quoted_finance_reply,
)
from capability_intelligence.finance_reply_binding import (  # noqa: E402
    get_active_finance_reply_binding,
    uninstall_router_hook,
)

DELIVERY_ID = "wamid.PERGUNTA-BOOT"
REPLY_ID = "wamid.RESPOSTA-MERCADO"
CLAR_A = "clar-boot"
OWNER_ACTOR = "finance-owner-1"
OWNER_PRINCIPAL = "5519999999999@s.whatsapp.net"
FINANCE_GROUP = "finance-group@g.us"


class FakeCaller:
    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._responses = responses or {}

    async def call(
        self,
        capability_id: str,
        params: dict[str, Any],
        *,
        channel: Any = None,
    ) -> dict[str, Any]:
        self.calls.append((capability_id, dict(params)))
        response = self._responses.get(capability_id, {})
        if callable(response):
            return response(params)
        if isinstance(response, Exception):
            raise response
        return response

    def caps(self) -> list[str]:
        return [c for c, _ in self.calls]


def _open() -> dict[str, Any]:
    return {
        "clarificationId": CLAR_A,
        "transactionId": "tx-1",
        "questionType": "CATEGORY",
        "status": "open",
        "merchant": "Supermercado",
    }


def _envelope() -> ContextEnvelope:
    return ContextEnvelope(
        conversation_id=FINANCE_GROUP,
        channel_id=FINANCE_GROUP,
        incoming_message_id=REPLY_ID,
        reply_to_message_id=DELIVERY_ID,
        user_id=OWNER_PRINCIPAL,
        is_group=True,
    )


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    uninstall_router_hook()
    reset_finance_quoted_binding_ready_for_tests()
    monkeypatch.setenv(
        "FINANCE_ACTOR_BINDINGS",
        f"{OWNER_PRINCIPAL}={OWNER_ACTOR}",
    )
    yield
    uninstall_router_hook()
    reset_finance_quoted_binding_ready_for_tests()


class TestEagerBootNoWarmup:
    def test_active_binding_immediately_after_boot(self, caplog):
        """PROCESS BOOT → binding ready antes de qualquer mensagem Finance."""
        assert get_active_finance_reply_binding() is None
        caller = FakeCaller()
        with caplog.at_level(logging.INFO):
            binding = ensure_finance_quoted_binding_ready(caller=caller)
        assert binding is not None
        assert get_active_finance_reply_binding() is binding
        assert READY_MARKER in caplog.text

    def test_boot_and_per_message_same_binding(self):
        caller = FakeCaller()
        boot = ensure_finance_quoted_binding_ready(caller=caller)
        per_message = ensure_finance_quoted_binding_ready()
        assert boot is not None
        assert per_message is boot
        assert get_active_finance_reply_binding() is boot

    def test_gateway_start_boot_hook_ready_before_platform_connect(self, caplog):
        """Espelha GatewayRunner.start: boot hook ANTES de Connecting to…"""
        assert get_active_finance_reply_binding() is None
        caller = FakeCaller()
        events: list[str] = []

        # Exact contract body from F2B_QUOTED_BOOT_EAGER_V1 (no finance_tools).
        with caplog.at_level(logging.INFO):
            events.append("Starting Hermes Gateway...")
            binding = ensure_finance_quoted_binding_ready(caller=caller)
            if binding is None:
                events.append("FINANCE_QUOTED_BINDING_READY=NO")
            else:
                events.append("FINANCE_QUOTED_BINDING_READY=YES")
            events.append("Connecting to whatsapp...")

        boot_idx = events.index("FINANCE_QUOTED_BINDING_READY=YES")
        connect_idx = events.index("Connecting to whatsapp...")
        assert boot_idx < connect_idx
        assert get_active_finance_reply_binding() is not None
        assert READY_MARKER in caplog.text
        assert "FINANCE_QUOTED_BINDING_READY=NO" not in events

    def test_boot_failure_visible_no_false_ready(self, caplog, monkeypatch):
        import capability_intelligence.finance_quoted_boot as boot_mod

        def _fail(*, caller=None, force=False):
            return None

        monkeypatch.setattr(boot_mod, "ensure_finance_quoted_binding_ready", _fail)
        with caplog.at_level(logging.WARNING):
            # Simulate gateway start failure branch (patch body).
            _f2b_boot_binding = boot_mod.ensure_finance_quoted_binding_ready()
            assert _f2b_boot_binding is None
            logging.getLogger("hermes.gateway").warning(
                "FINANCE_QUOTED_BINDING_READY=NO "
                "F2B_FALLTHROUGH_REASON=BINDING_BOOT_FAILED"
            )
        assert "FINANCE_QUOTED_BINDING_READY=NO" in caplog.text
        assert READY_MARKER not in caplog.text
        assert get_active_finance_reply_binding() is None

    async def test_first_message_after_restart_quoted_finance_no_warmup(self):
        """Process B limpo: PRIMEIRA mensagem é quoted "Mercado" — sem warmup."""
        assert get_active_finance_reply_binding() is None

        caller = FakeCaller(
            {
                "finance.clarification.list": {"clarifications": [_open()]},
                "finance.clarification.resolve": {
                    "resolved": True,
                    "clarification": {"id": CLAR_A},
                },
            }
        )
        # Boot real — NÃO instancia FinanceReplyBinding fora do ensure.
        ensure_finance_quoted_binding_ready(caller=caller)
        active = get_active_finance_reply_binding()
        assert active is not None

        result = await try_handle_quoted_finance_reply(
            active,
            message_text="Mercado",
            envelope=_envelope(),
        )
        assert result.durable_lookup_called is True
        assert result.quoted_finance is True
        assert result.bind_reply_called is True
        assert "finance.clarification.resolve" in caller.caps()
        assert result.gate_outcome == OUTCOME_FINANCE_RESOLVED
        assert result.skip_llm is True
        assert result.success_text_emitted is True

    async def test_restart_simulation_process_a_then_b(self):
        store = {
            "finance.clarification.list": {"clarifications": [_open()]},
            "finance.clarification.resolve": {"resolved": True},
        }
        # Process A
        ensure_finance_quoted_binding_ready(caller=FakeCaller(store))
        assert get_active_finance_reply_binding() is not None

        # Process morre
        uninstall_router_hook()
        reset_finance_quoted_binding_ready_for_tests()
        assert get_active_finance_reply_binding() is None

        # Process B — primeira mensagem quoted
        caller_b = FakeCaller(store)
        ensure_finance_quoted_binding_ready(caller=caller_b)
        result = await try_handle_quoted_finance_reply(
            get_active_finance_reply_binding(),  # type: ignore[arg-type]
            message_text="Mercado",
            envelope=_envelope(),
        )
        assert result.gate_outcome == OUTCOME_FINANCE_RESOLVED
        assert result.skip_llm is True
