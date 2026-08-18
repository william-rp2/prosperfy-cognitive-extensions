"""
tests/db/test_live_mcp_e2e_audit_telemetry.py — DB-side proof that a real
`scripts/sprint_0_3_live_mcp_gate.py run-positive` execution against the live
Homolog API left the expected trail in Postgres.

These tests do NOT trigger an execution themselves (they have no HTTP/MCP
access) — they read a `correlation_id` (and `tenant_id`) that a prior
`run-positive --correlation-id-out <path>` run already produced, then verify
via `admin_conn` (bypassing HTTP entirely) that:

  1. An `audit_events` row exists for that (tenant_id, correlation_id) with
     the right actor_id/capability_id/outcome, and `inputs_redacted` carries
     no secret-shaped value.
  2. A `cost_telemetry` row *would* exist with the right shape — see the
     KNOWN GAP note below; as of Sprint 0.3 this assertion is conditional,
     not a hard requirement, because the wiring to make it true does not
     exist yet.

Same skip conventions as the rest of tests/db/ (`db_integration_available()` /
`skip_reason()` from conftest.py) — in this sandbox (no DB, no network) this
whole module SKIPS, it never ERRORs. `pytest.mark.safe_remote`: every query
here is a `SELECT` scoped to a single correlation_id/tenant_id already
supplied by the operator — no schema mutation, no cross-tenant read.

How to populate the two required inputs before running this file for real:

    python scripts/sprint_0_3_live_mcp_gate.py run-positive \\
        --environment homolog --credential-file /path/to/cred.json \\
        --api-base-url https://api-cognitive-homolog.prosperfy.com.br \\
        --correlation-id-out /path/to/correlation_id.txt

    export COGNITIVE_E2E_CORRELATION_ID_FILE=/path/to/correlation_id.txt
    export COGNITIVE_E2E_TENANT_ID=<tenant_id from the credential file>

    COGNITIVE_DB_ADMIN_URL=... COGNITIVE_DB_TEST_MODE=remote_homolog \\
        python -m pytest tests/db/test_live_mcp_e2e_audit_telemetry.py -v

KNOWN GAP (found while building this runner, NOT fixed here — gateway/app.py
is on the do-not-modify list for this workstream): `gateway/app.py`'s
`_build_services()` wires `telemetry_recorder = InMemoryTelemetryRecorder()`
UNCONDITIONALLY (line is outside the `if use_db:` branch) — even in
`COGNITIVE_MODE=database`, telemetry is never persisted to the `cost_telemetry`
table (migration 001 creates the table; nothing in the app ever writes to it,
there is no PostgresTelemetryRecorder/telemetry repo anywhere in
`cognitive/db/repositories/`). `audit_events` IS persisted for real
(`PostgresAuditWriter`, wired only when `use_db` is True). So today, a real
`run-positive` call against Homolog WILL produce a queryable `audit_events`
row, but will NOT produce any `cost_telemetry` row — that assertion is written
below as conditional/informational, not a hard failure, until that gap is
closed by whichever workstream owns `gateway/app.py`.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest

from .conftest import db_integration_available, skip_reason

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not db_integration_available(), reason=skip_reason()),
    pytest.mark.safe_remote,
]

EXPECTED_ACTOR_ID = "homolog-e2e-actor"
EXPECTED_CAPABILITY_ID = "infra.inspect"
_REDACTED_MARKER = "***REDACTED***"


def _read_correlation_id() -> str | None:
    file_path = os.getenv("COGNITIVE_E2E_CORRELATION_ID_FILE", "").strip()
    if file_path:
        p = Path(file_path)
        if p.exists():
            content = p.read_text(encoding="utf-8").strip()
            if content:
                return content
    direct = os.getenv("COGNITIVE_E2E_CORRELATION_ID", "").strip()
    return direct or None


def _read_tenant_id() -> str | None:
    return os.getenv("COGNITIVE_E2E_TENANT_ID", "").strip() or None


@pytest.fixture(scope="module")
def e2e_correlation_id() -> str:
    correlation_id = _read_correlation_id()
    if not correlation_id:
        pytest.skip(
            "no correlation_id available — run "
            "'python scripts/sprint_0_3_live_mcp_gate.py run-positive "
            "--correlation-id-out <path>' first, then set "
            "COGNITIVE_E2E_CORRELATION_ID_FILE=<path> "
            "(or COGNITIVE_E2E_CORRELATION_ID=<value> directly)"
        )
    return correlation_id


@pytest.fixture(scope="module")
def e2e_tenant_id() -> str:
    tenant_id = _read_tenant_id()
    if not tenant_id:
        pytest.skip(
            "no tenant_id available — set COGNITIVE_E2E_TENANT_ID to the "
            "tenant_id from the bootstrap-homolog-context credential file "
            "used for the run-positive call this test verifies"
        )
    return tenant_id


class TestAuditEventForE2ERun:
    """Proves the boundary: Result -> Audit for a real Homolog execution."""

    async def test_audit_event_exists_with_expected_fields(
        self, db_pools, admin_conn, e2e_correlation_id, e2e_tenant_id,
    ):
        row = await admin_conn.fetchrow(
            """
            SELECT tenant_id, actor_id, capability_id, correlation_id,
                   policy_decision, outcome, duration_ms
            FROM audit_events
            WHERE correlation_id = $1 AND tenant_id = $2
            ORDER BY created_at DESC
            LIMIT 1
            """,
            e2e_correlation_id,
            uuid.UUID(e2e_tenant_id),
        )
        assert row is not None, (
            f"no audit_events row for correlation_id={e2e_correlation_id!r} "
            f"tenant_id={e2e_tenant_id!r} — run run-positive against Homolog "
            "first, then re-run this test with the resulting correlation_id"
        )
        assert row["actor_id"] == EXPECTED_ACTOR_ID
        assert row["capability_id"] == EXPECTED_CAPABILITY_ID
        assert row["outcome"] == "completed"
        assert row["policy_decision"] == "allow"
        assert row["duration_ms"] >= 0

    async def test_audit_event_inputs_redacted_has_no_secret_shaped_value(
        self, db_pools, admin_conn, e2e_correlation_id, e2e_tenant_id,
    ):
        row = await admin_conn.fetchrow(
            """
            SELECT inputs_redacted
            FROM audit_events
            WHERE correlation_id = $1 AND tenant_id = $2
            ORDER BY created_at DESC
            LIMIT 1
            """,
            e2e_correlation_id,
            uuid.UUID(e2e_tenant_id),
        )
        assert row is not None

        from cognitive.db.jsonb_codec import deserialize_jsonb_object

        inputs = deserialize_jsonb_object(row["inputs_redacted"])
        serialized = json.dumps(inputs)

        # redact() (audit/redaction.py) always masks password/secret/token/
        # api_key/credential/bearer fields as "***REDACTED***" — the raw
        # synthetic credential value itself must never appear here, and any
        # field that legitimately fell under redaction_rules must show the
        # marker rather than a plaintext value.
        credential = os.getenv("COGNITIVE_E2E_CREDENTIAL_VALUE", "").strip()
        if credential:
            assert credential not in serialized

        for key, value in inputs.items():
            if key.lower() in {"api_key", "password", "token", "secret", "credential", "bearer"}:
                assert value == _REDACTED_MARKER, (
                    f"field {key!r} in inputs_redacted was not masked: {value!r}"
                )


class TestCostTelemetryForE2ERun:
    """Result -> Telemetry — CONDITIONAL, see KNOWN GAP note at module top.

    gateway/app.py wires telemetry_recorder = InMemoryTelemetryRecorder()
    unconditionally (never PostgresTelemetryRecorder, which does not exist
    anywhere in cognitive/db/repositories/), so a real run-positive call does
    NOT currently produce a cost_telemetry row. This test does not assert
    the row must exist (that would be a guaranteed false failure against
    today's code) — it reports what it finds and only enforces field shape
    when a row is actually present, so it stays a truthful signal both today
    (gap open) and after whichever workstream closes it.
    """

    async def test_cost_telemetry_row_if_present_has_expected_shape(
        self, db_pools, admin_conn, e2e_correlation_id, e2e_tenant_id,
    ):
        row = await admin_conn.fetchrow(
            """
            SELECT tenant_id, actor_id, capability_id, correlation_id,
                   latency_ms, tool_calls
            FROM cost_telemetry
            WHERE correlation_id = $1 AND tenant_id = $2
            ORDER BY recorded_at DESC
            LIMIT 1
            """,
            e2e_correlation_id,
            uuid.UUID(e2e_tenant_id),
        )
        if row is None:
            pytest.skip(
                "KNOWN GAP (Sprint 0.3): no cost_telemetry row for "
                f"correlation_id={e2e_correlation_id!r} — gateway/app.py wires "
                "InMemoryTelemetryRecorder unconditionally, telemetry is never "
                "persisted to Postgres yet. See module docstring. Not a bug in "
                "this test — the wiring to make this assertion meaningful does "
                "not exist as of this commit."
            )
        assert row["actor_id"] == EXPECTED_ACTOR_ID
        assert row["capability_id"] == EXPECTED_CAPABILITY_ID
        assert row["latency_ms"] >= 0
        assert row["tool_calls"] >= 0
