"""tests/unit/test_audit_repo_jsonb.py — Regressão JSONB em PostgresAuditWriter."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from cognitive.contracts.audit import AuditEvent, AuditOutcome
from cognitive.db.repositories.audit_repo import PostgresAuditWriter, _row_to_audit_event


def _make_event(**overrides) -> AuditEvent:
    defaults = {
        "tenant_id": str(uuid.uuid4()),
        "actor_id": "actor-test",
        "capability_id": "infra.inspect",
        "correlation_id": "corr-001",
        "policy_decision": "allow",
        "outcome": AuditOutcome.COMPLETED,
        "inputs_redacted": {"resource": "prosperfy-main"},
        "result_summary": {"tool_calls": 3},
        "duration_ms": 100,
    }
    defaults.update(overrides)
    return AuditEvent(**defaults)


@pytest.mark.asyncio
class TestPostgresAuditWriterSerialize:
    @pytest.mark.parametrize(
        "inputs_redacted,result_summary",
        [
            ({}, {}),
            ({"resource": "prosperfy-main"}, {"tool_calls": 3}),
            (
                {"resource": {"name": "prosperfy-main", "type": "server"}},
                {"items": [1, 2, 3]},
            ),
            ({"items": [1, 2, 3]}, {}),
            ({"allowed": True, "reason": None}, {"ok": False}),
            ({"message": "ação concluída"}, {"quote": 'say "hello"'}),
            (
                {"slash": "path/to/file", "backslash": "a\\b"},
                {"nested": {"x": 1}},
            ),
        ],
    )
    async def test_record_serializes_jsonb_params(
        self, inputs_redacted, result_summary
    ):
        writer = PostgresAuditWriter()
        event = _make_event(
            inputs_redacted=inputs_redacted,
            result_summary=result_summary,
        )
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        with patch(
            "cognitive.db.repositories.audit_repo.tenant_transaction"
        ) as mock_tx:
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__ = AsyncMock(return_value=False)
            await writer.record(event)

        args = mock_conn.execute.call_args[0][1:]
        inputs_arg = args[8]
        summary_arg = args[9]
        assert isinstance(inputs_arg, str)
        assert isinstance(summary_arg, str)
        assert json.loads(inputs_arg) == inputs_redacted
        assert json.loads(summary_arg) == result_summary


class TestAuditEventRowDeserialization:
    @pytest.mark.parametrize(
        "inputs_raw,summary_raw",
        [
            ("{}", "{}"),
            ('{"resource":"prosperfy-main"}', '{"tool_calls":3}'),
            (
                '{"resource":{"name":"prosperfy-main","type":"server"}}',
                '{"items":[1,2,3]}',
            ),
            ('{"allowed":true,"reason":null}', '{"ok":false}'),
            ('{"message":"ação concluída"}', '{"quote":"say \\"hello\\""}'),
        ],
    )
    def test_row_to_audit_event_from_json_string(self, inputs_raw, summary_raw):
        row = {
            "audit_id": uuid.uuid4(),
            "execution_id": uuid.uuid4(),
            "tenant_id": uuid.uuid4(),
            "actor_id": "actor",
            "capability_id": "infra.inspect",
            "correlation_id": "corr",
            "policy_decision": "allow",
            "outcome": "completed",
            "inputs_redacted": inputs_raw,
            "result_summary": summary_raw,
            "duration_ms": 10,
            "cost_estimate": 0.0,
            "created_at": datetime.now(timezone.utc),
        }
        event = _row_to_audit_event(row)
        assert event.inputs_redacted == json.loads(inputs_raw)
        assert event.result_summary == json.loads(summary_raw)

    def test_row_to_audit_event_from_python_dict(self):
        row = {
            "audit_id": uuid.uuid4(),
            "execution_id": uuid.uuid4(),
            "tenant_id": uuid.uuid4(),
            "actor_id": "actor",
            "capability_id": "infra.inspect",
            "correlation_id": "corr",
            "policy_decision": "allow",
            "outcome": "completed",
            "inputs_redacted": {"resource": "prosperfy-main"},
            "result_summary": {"tool_calls": 3},
            "duration_ms": 10,
            "cost_estimate": 0.0,
            "created_at": datetime.now(timezone.utc),
        }
        event = _row_to_audit_event(row)
        assert event.inputs_redacted == {"resource": "prosperfy-main"}
        assert event.result_summary == {"tool_calls": 3}
