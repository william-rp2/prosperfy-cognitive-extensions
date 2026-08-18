# Sprint 0.3 — Live MCP E2E Gate (Homolog)

Operational runbook for `scripts/sprint_0_3_live_mcp_gate.py` — the official
runner that proves the full Cognitive Core V2 chain end-to-end against the
**real deployed Homolog API**:

```
Identity -> Registry -> ResourceResolver -> Policy -> Adapter -> live MCP
-> Result -> Audit -> Telemetry
```

...plus the negative path (boundary-guard / read-only enforcement) and
idempotency-key behavior, exercising `infra.inspect`
(`core/cognitive/cognitive/registry/capabilities/infra.inspect.yaml`), which
composes three real ProsperfySkill MCP tools in sequence:
`prosperfy_vps_panorama`, `prosperfy_vps_listar_containers`,
`prosperfy_vps_verificar_portas`.

This script makes **no writes** to production data — `infra.inspect` is
read-only (`default_policy: allow`), and the negative-path tests are
specifically designed to prove destructive/arbitrary-command params are
rejected before the adapter or MCP is ever called.

## Where this runs

**On the VPS / wherever Homolog credentials and network access actually
exist** — never from a developer sandbox without those credentials. This
script refuses to run without an explicit `--environment homolog` flag AND
`COGNITIVE_LIVE_MCP=1` (see Safety section below); it will not silently do
anything against Production, and it does not touch the database directly
(it only talks HTTP to the deployed API).

## Prerequisites

1. **Synthetic Homolog context bootstrapped.** Run the parallel
   `dev/sprint-0.3-e2e-context` workstream's script to produce the credential
   file this runner consumes:

   ```bash
   python scripts/sprint_0_3_synthetic_context.py bootstrap-homolog-context
   ```

   This prints a file **path** to stdout (never the credential itself), at
   `0600` permissions, containing exactly:

   ```json
   {
     "tenant_id": "<uuid>",
     "actor_id": "homolog-e2e-actor",
     "credential": "<raw synthetic credential>",
     "resource_key": "homolog-synthetic-vps",
     "capability_id": "infra.inspect"
   }
   ```

   `sprint_0_3_live_mcp_gate.py` treats this JSON shape as a documented
   public contract — it never imports anything from that script's module.

2. **`MCP_PROSPERFYSKILLS_API_KEY` provisioned** on the API host — this is
   read by `ProsperfySkillsAdapter` (`adapters/prosperfy_skills/client.py`),
   not by this script. Without it, `run-positive`/`run-negative`/etc. will
   get back a `failed` status from the API (the adapter raises
   `RuntimeError("MCP_PROSPERFYSKILLS_API_KEY não configurada")` server-side).

3. **`COGNITIVE_LIVE_MCP=1`** set on the API host so the Gateway wires the
   real `ProsperfySkillsAdapter` instead of `MockSkillsAdapter`
   (`gateway/app.py`'s `_build_services()`). This env var must be set where
   the API process runs — this script also independently *requires*
   `COGNITIVE_LIVE_MCP=1` to be set in **its own** environment before it will
   attempt any HTTP call, as an extra fail-closed signal that the operator
   knows they're targeting the real MCP path.

4. **The Homolog API is reachable** at a known base URL — confirmed live per
   the Homolog Gate report: `https://api-cognitive-homolog.prosperfy.com.br`.

5. **Migrations 000/001/002 applied and healthy** on the Homolog database —
   already confirmed by the Homolog Gate (see `core/migrations/README.md`).

## Command sequence

All commands require `--environment homolog` explicitly — this is a
**positive confirmation flag**, not a default. There is no automatic way to
prove an arbitrary HTTPS URL is not Production (unlike a Postgres DSN, which
has a known project ref this codebase can verify against). Omitting the flag,
or passing anything other than exactly `homolog`, refuses immediately with no
HTTP call attempted.

```bash
export COGNITIVE_LIVE_MCP=1
export COGNITIVE_HOMOLOG_API_URL=https://api-cognitive-homolog.prosperfy.com.br
CRED_FILE=$(python scripts/sprint_0_3_synthetic_context.py bootstrap-homolog-context)

# 1. Preconditions only — no HTTP call yet.
python scripts/sprint_0_3_live_mcp_gate.py verify-preconditions \
    --environment homolog --credential-file "$CRED_FILE"

# 2. One real infra.inspect call.
python scripts/sprint_0_3_live_mcp_gate.py run-positive \
    --environment homolog --credential-file "$CRED_FILE" \
    --correlation-id-out /tmp/e2e_correlation_id.txt

# 3. Negative path — 11 forbidden-key rejections.
python scripts/sprint_0_3_live_mcp_gate.py run-negative \
    --environment homolog --credential-file "$CRED_FILE"

# 4. Idempotency-key behavior (4 calls).
python scripts/sprint_0_3_live_mcp_gate.py run-idempotency \
    --environment homolog --credential-file "$CRED_FILE"

# 5. Timing / performance (only fields the response actually exposes).
python scripts/sprint_0_3_live_mcp_gate.py run-performance \
    --environment homolog --credential-file "$CRED_FILE"

# ...or run everything in sequence, stop at first failure:
python scripts/sprint_0_3_live_mcp_gate.py run-full \
    --environment homolog --credential-file "$CRED_FILE" \
    --correlation-id-out /tmp/e2e_correlation_id.txt
```

`--api-base-url` may be passed explicitly instead of relying on
`COGNITIVE_HOMOLOG_API_URL`; the CLI flag wins when both are present.

## What PASS/FAIL looks like

### `verify-preconditions`

Prints one `<check_name>=PASS|FAIL` line per check
(`environment_declared_homolog`, `live_mcp_enabled`, `credential_file_ok`,
`api_base_url_provided`, `api_base_url_homolog_shaped`), any `error=...`
lines explaining a failure, and a final line:

```
PRECONDITIONS_RESULT=PASS
```

or `PRECONDITIONS_RESULT=FAIL` with exit code 1.

### `run-positive`

Prints `idempotency_key`, `http_status`, `execution_id`, `correlation_id`,
`audit_id`, `status`, `tool_result_keys_present` (the three MCP tool result
keys found in the response `data`), and:

```
RUN_POSITIVE_RESULT=PASS
```

PASS requires HTTP 200, `status=completed`, and all three tool result keys
present. Never prints the full response body unless `--verbose` is passed.
If `--correlation-id-out <path>` was given, the correlation_id is also
written to that file (plain text) for the DB-side follow-up test below.

### `run-negative`

One line per forbidden key (`bash: PASS (status=failed)`, etc.) covering all
11 keys in `adapters/prosperfy_skills/guard.py`'s `FORBIDDEN_ARG_KEYS`
(`command`, `cmd`, `comando`, `shell`, `bash`, `exec`, `execute`, `script`,
`sh`, `powershell`, `eval`), then:

```
RUN_NEGATIVE_RESULT=PASS
```

Exit code is non-zero if **any** of the 11 keys was not rejected as expected
(`status != failed`). Per `execution/orchestrator.py`'s Step 2.4 BOUNDARY
GUARD, a forbidden key is rejected before resource resolution, policy
evaluation, the adapter, or the MCP is ever reached.

### `run-idempotency`

Prints the note about in-process-only idempotency, then `execution_id` for
each of 4 calls (same key twice, a different key, no key at all), then:

```
cache_hit_same_execution_id=PASS
different_key_new_execution_id=PASS
no_key_is_distinct_execution=PASS
RUN_IDEMPOTENCY_RESULT=PASS
```

This proves the orchestrator's in-process `self._idempotency_cache`
(`execution/orchestrator.py`) is exercised from outside the process. It does
**not** prove idempotency survives a restart or spans multiple app
instances — that is explicitly out of scope for Sprint 0.3 (no persistent
idempotency store exists).

### `run-performance`

Prints `total_wallclock_duration_ms` (this runner's own measurement of the
full HTTP round trip — `CapabilityExecuteResponse` has no `duration_ms` field
of its own), `tool_calls` (inferred from `len(response.data)`, with a note
explaining why it's an inference rather than a dedicated field), and
`llm_calls=0` (a fact about the code — `_run_capability_tools` never calls an
LLM — not something the response reports). Then:

```
RUN_PERFORMANCE_RESULT=PASS
```

### `run-full`

Runs all five steps above in sequence, printing `=== STEP: <name> ===`
before each, stopping at the first failure with:

```
GATE_RESULT=FAILED at step=<name>
```

or, if every step passes:

```
GATE_RESULT=PASS
```

## Verifying the DB-side trail

`core/cognitive/tests/db/test_live_mcp_e2e_audit_telemetry.py` verifies
(via `admin_conn`, bypassing HTTP) that a `run-positive` call actually left
an `audit_events` row with the right `tenant_id`/`actor_id`/`capability_id`/
`correlation_id`/`outcome`, and no secret-shaped value in `inputs_redacted`.
It is marked `@pytest.mark.safe_remote` (pure `SELECT`s scoped to one
correlation_id/tenant_id) and follows the same `db_integration_available()` /
`skip_reason()` skip convention as the rest of `tests/db/`.

```bash
python scripts/sprint_0_3_live_mcp_gate.py run-positive \
    --environment homolog --credential-file "$CRED_FILE" \
    --correlation-id-out /tmp/e2e_correlation_id.txt

export COGNITIVE_E2E_CORRELATION_ID_FILE=/tmp/e2e_correlation_id.txt
export COGNITIVE_E2E_TENANT_ID=<tenant_id from the credential file>
export COGNITIVE_DB_ADMIN_URL=<homolog admin DSN>
export COGNITIVE_DB_TEST_MODE=remote_homolog

cd core/cognitive
python -m pytest tests/db/test_live_mcp_e2e_audit_telemetry.py -v
```

**Known gap (found while building this runner, not fixed here):**
`gateway/app.py`'s `_build_services()` wires
`telemetry_recorder = InMemoryTelemetryRecorder()` **unconditionally**, even
in `COGNITIVE_MODE=database` — there is no `PostgresTelemetryRecorder`
anywhere in `cognitive/db/repositories/`. The `cost_telemetry` table exists
(migration 001) but nothing in the running app ever writes to it. The
`TestCostTelemetryForE2ERun` test in the file above reflects this honestly:
if no `cost_telemetry` row is found for the correlation_id, it **skips**
with a `KNOWN GAP` message rather than failing — `gateway/app.py` is outside
this workstream's scope (owned by another workstream / on the
do-not-modify list for this branch). Whoever owns telemetry persistence
should wire a `PostgresTelemetryRecorder` and this test will start asserting
the row's shape for real, with no changes needed here.

## Cleanup

After a `run-full` (or any subset of these commands) against Homolog:

1. **Delete the credential file.** It contains a raw synthetic credential at
   `0600` permissions — do not leave it on disk longer than needed:

   ```bash
   rm -f "$CRED_FILE" /tmp/e2e_correlation_id.txt
   ```

2. **Tear down the synthetic Homolog context** using the parallel
   `dev/sprint-0.3-e2e-context` workstream's script (referenced by name only
   — its teardown logic is not duplicated here):

   ```bash
   python scripts/sprint_0_3_synthetic_context.py teardown-homolog-context
   ```

3. Confirm no stray `audit_events`/`cost_telemetry` rows are left dangling
   beyond what the teardown script already scopes and removes — this runner
   creates exactly one `audit_events` row per capability call it makes
   (`run-positive` = 1, `run-negative` = 11, `run-idempotency` = 4,
   `run-performance` = 1; `run-full` = 17 total), all scoped to the synthetic
   tenant/actor the bootstrap step created.

## Design notes / assumptions flagged for Lead Dev review

These are the places this runner's design had to make a judgment call
because the contract file didn't spell it out directly — worth a second look
when the parallel `dev/sprint-0.3-e2e-context` workstream lands:

- **`response.data` keys are the raw MCP tool names**
  (`prosperfy_vps_panorama`, `prosperfy_vps_listar_containers`,
  `prosperfy_vps_verificar_portas`), **not** `infra.inspect.yaml`'s
  `output_schema` aliases (`panorama`/`containers`/`ports`). Confirmed by
  reading `execution/orchestrator.py._run_capability_tools()` end-to-end —
  `results[tool_name] = tool_result` with no aliasing step anywhere. This
  runner checks for the real tool-name keys.
- **`tool_calls` count is inferred** as `len(response.data)` in
  `run-performance` — `CapabilityExecuteResponse` (`contracts/gateway.py`)
  has no dedicated `tool_calls` field. This assumption holds as of Sprint
  0.3 but is not schema-guaranteed.
- **No per-adapter/MCP duration breakdown is available from the HTTP
  response** — only `audit_events.duration_ms` in the DB captures that,
  and it isn't returned over HTTP. `run-performance` reports only its own
  wall-clock measurement of the full round trip and says so explicitly.
- **`cost_telemetry` persistence gap** — see "Known gap" above.

None of these are guesses about the request contract itself (headers, body
shape, `GatewayStatus` values) — those were confirmed directly by reading
`gateway/routes/capabilities.py`, `gateway/deps.py`, and
`contracts/gateway.py`, and this runner imports `GatewayStatus` and
`FORBIDDEN_ARG_KEYS` directly from the real modules rather than duplicating
them, so it cannot silently drift from what the codebase actually enforces.
