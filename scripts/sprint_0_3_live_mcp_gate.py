#!/usr/bin/env python3
"""
Sprint 0.3 — Live MCP E2E Gate Runner (Homolog).

Proves the FULL Cognitive Core V2 chain end-to-end against a REAL deployed
Homolog API:

    Identity -> Registry -> ResourceResolver -> Policy -> Adapter -> live
    ProsperfySkill MCP -> Result -> Audit -> Telemetry

...plus the negative path (boundary-guard / read-only enforcement) and the
idempotency-key behavior, by driving the real HTTP contract exposed by
`core/cognitive/cognitive/gateway/routes/capabilities.py`:

    POST {api_base_url}/v1/capabilities/{capability_id}/execute
    body: {"params": {...}, "idempotency_key": "<optional>"}
    headers: Authorization: Bearer <credential>
             X-Tenant-Id: <tenant_id>
             X-Actor-Id: <actor_id>
             X-Correlation-Id: <optional>

This script makes NO assumptions beyond what is verifiable by reading:
  - gateway/routes/capabilities.py + gateway/deps.py (header contract)
  - contracts/gateway.py (CapabilityExecuteRequest/Response, GatewayStatus)
  - adapters/prosperfy_skills/guard.py (FORBIDDEN_ARG_KEYS)
  - execution/orchestrator.py (boundary guard -> FAILED before adapter/MCP;
    idempotency cache; deterministic tool sequence, zero LLM calls)
  - registry/capabilities/infra.inspect.yaml (resource param, 3 composed tools)

Credential file contract (produced by the parallel `dev/sprint-0.3-e2e-context`
workstream's `scripts/sprint_0_3_synthetic_context.py bootstrap-homolog-context`
command — consumed here ONLY as a documented JSON shape, never imported):

    {
      "tenant_id": "<uuid>",
      "actor_id": "homolog-e2e-actor",
      "credential": "<raw synthetic credential>",
      "resource_key": "homolog-synthetic-vps",
      "capability_id": "infra.inspect"
    }

SAFETY (fail-closed, mirrors COGNITIVE_DB_TEST_MODE=remote_homolog philosophy):
  - COGNITIVE_LIVE_MCP=1 must be set, or every subcommand refuses.
  - --environment homolog must be passed EXPLICITLY on every subcommand, or
    every subcommand refuses. There is no automatic way to prove an arbitrary
    HTTPS URL is not Production, so this script requires a positive, explicit
    operator declaration instead (same "explicit declaration, fail closed on
    absence or mismatch" pattern as tests/db/conftest.py's
    resolve_db_test_mode()/db_test_mode fixture and
    cognitive/gate/remote_safety_guard.py).
  - Never prints the raw credential value, Authorization header, or full
    response bodies unless --verbose is passed on run-positive.

Usage:
    python scripts/sprint_0_3_live_mcp_gate.py verify-preconditions \\
        --environment homolog --credential-file /path/to/cred.json \\
        --api-base-url https://api-cognitive-homolog.prosperfy.com.br

    python scripts/sprint_0_3_live_mcp_gate.py run-full \\
        --environment homolog --credential-file /path/to/cred.json \\
        --api-base-url https://api-cognitive-homolog.prosperfy.com.br
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
COGNITIVE_DIR = REPO_ROOT / "core" / "cognitive"
sys.path.insert(0, str(COGNITIVE_DIR))

# Reused directly from the real contracts (never duplicated/hardcoded) so this
# runner can never silently drift from what the codebase actually enforces.
from cognitive.adapters.prosperfy_skills.guard import FORBIDDEN_ARG_KEYS  # noqa: E402
from cognitive.contracts.gateway import GatewayStatus  # noqa: E402

REQUIRED_ENVIRONMENT_VALUE = "homolog"
REQUIRED_CREDENTIAL_KEYS = (
    "tenant_id",
    "actor_id",
    "credential",
    "resource_key",
    "capability_id",
)
DEFAULT_HTTP_TIMEOUT = 45.0

# NOTE (flag for Lead Dev): infra.inspect.yaml's `output_schema` documents
# result keys as panorama/containers/services/ports, but
# execution/orchestrator.py._run_capability_tools() actually keys
# `response.data` by the raw MCP *tool name* (results[tool_name] = ...), with
# no schema-aliasing step anywhere in the codebase. Confirmed by reading
# orchestrator.py end-to-end. This runner checks for presence of the real
# tool-name keys below, not the YAML's output_schema aliases — verify this
# assumption still holds when the parallel workstreams land.
EXPECTED_TOOL_RESULT_KEYS = (
    "prosperfy_vps_panorama",
    "prosperfy_vps_listar_containers",
    "prosperfy_vps_verificar_portas",
)


# ─── Errors ──────────────────────────────────────────────────────────────

class CredentialFileError(Exception):
    """Credential file missing, unreadable, malformed JSON, or missing/invalid keys.

    Never lets a raw KeyError/JSONDecodeError/OSError escape to the caller.
    """


class EnvironmentGateError(Exception):
    """--environment homolog (or COGNITIVE_LIVE_MCP=1) was not explicitly declared."""


# ─── Credential file (contract with dev/sprint-0.3-e2e-context) ──────────

@dataclass
class CredentialFile:
    tenant_id: str
    actor_id: str
    credential: str
    resource_key: str
    capability_id: str
    path: Path


def load_credential_file(path: str | Path) -> CredentialFile:
    """Parses the bootstrap-homolog-context JSON credential file.

    Fails with a clear CredentialFileError (never a raw traceback) if the
    file is missing, unreadable, not valid JSON, not a JSON object, missing
    any required key, or has a non-string/empty value for a required key.
    """
    p = Path(path)
    if not p.exists():
        raise CredentialFileError(f"credential file not found: {p}")
    if not p.is_file():
        raise CredentialFileError(f"credential file path is not a file: {p}")

    try:
        raw_text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise CredentialFileError(f"credential file unreadable: {p} ({exc})") from exc

    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise CredentialFileError(
            f"credential file is not valid JSON: {p} (line {exc.lineno}, col {exc.colno})"
        ) from exc

    if not isinstance(raw, dict):
        raise CredentialFileError(
            f"credential file must contain a JSON object at the top level: {p}"
        )

    missing = [k for k in REQUIRED_CREDENTIAL_KEYS if k not in raw]
    if missing:
        raise CredentialFileError(
            f"credential file missing required key(s) {missing}: {p} "
            f"(expected schema keys: {list(REQUIRED_CREDENTIAL_KEYS)})"
        )

    invalid = [
        k for k in REQUIRED_CREDENTIAL_KEYS
        if not isinstance(raw.get(k), str) or not raw[k].strip()
    ]
    if invalid:
        raise CredentialFileError(
            f"credential file has empty or non-string value(s) for key(s) {invalid}: {p}"
        )

    return CredentialFile(
        tenant_id=raw["tenant_id"],
        actor_id=raw["actor_id"],
        credential=raw["credential"],
        resource_key=raw["resource_key"],
        capability_id=raw["capability_id"],
        path=p,
    )


# ─── Environment / preconditions gate ─────────────────────────────────────

def check_environment_flag(environment: str | None) -> None:
    """Fail-closed: refuses unless --environment homolog was passed EXACTLY.

    Mirrors tests/db/conftest.py's resolve_db_test_mode()/db_test_mode and
    cognitive/gate/remote_safety_guard.py's COGNITIVE_DB_TEST_MODE=remote_homolog
    pattern: explicit positive declaration required, absence or mismatch both
    fail closed. There is no automatic "is this Production" check for an
    arbitrary HTTPS API URL (unlike verify_homolog_admin_dsn for a Postgres
    DSN with a known project ref) — so the operator must say so explicitly.
    """
    if environment != REQUIRED_ENVIRONMENT_VALUE:
        raise EnvironmentGateError(
            "SAFETY: --environment homolog must be passed explicitly to run "
            f"any live MCP gate command (got {environment!r}). Refusing to "
            "proceed — no HTTP call was attempted."
        )


def check_live_mcp_flag() -> None:
    """Fail-closed: refuses unless COGNITIVE_LIVE_MCP=1 is set in the environment."""
    value = os.getenv("COGNITIVE_LIVE_MCP", "")
    if value != "1":
        raise EnvironmentGateError(
            "SAFETY: COGNITIVE_LIVE_MCP=1 must be set to run against the real "
            f"ProsperfySkill MCP (got COGNITIVE_LIVE_MCP={value or '<unset>'!r}). "
            "Refusing to proceed — no HTTP call was attempted."
        )


def resolve_api_base_url(cli_value: str | None) -> str | None:
    """--api-base-url wins; falls back to COGNITIVE_HOMOLOG_API_URL."""
    if cli_value:
        return cli_value
    env_value = os.getenv("COGNITIVE_HOMOLOG_API_URL", "").strip()
    return env_value or None


def looks_homolog_shaped(url: str) -> bool:
    """Heuristic only — NOT a security boundary by itself.

    There is no definitive "is this Production" check for an arbitrary HTTPS
    URL (unlike a Postgres DSN's project ref). This just catches an obvious
    mismatch (e.g. operator pasted the Production URL by accident); the real
    fail-closed gate is the explicit --environment homolog flag.
    """
    return "homolog" in url.lower()


@dataclass
class PreconditionsReport:
    ok: bool
    checks: dict[str, bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    credential: CredentialFile | None = None
    api_base_url: str | None = None


def run_preconditions(
    environment: str | None,
    credential_file_path: str,
    api_base_url_cli: str | None,
) -> PreconditionsReport:
    """Runs every precondition check WITHOUT making any real capability call."""
    checks: dict[str, bool] = {}
    errors: list[str] = []

    checks["environment_declared_homolog"] = environment == REQUIRED_ENVIRONMENT_VALUE
    if not checks["environment_declared_homolog"]:
        errors.append(f"--environment homolog required (got {environment!r})")

    live_mcp = os.getenv("COGNITIVE_LIVE_MCP", "")
    checks["live_mcp_enabled"] = live_mcp == "1"
    if not checks["live_mcp_enabled"]:
        errors.append(f"COGNITIVE_LIVE_MCP=1 required (got {live_mcp or '<unset>'!r})")

    credential: CredentialFile | None = None
    try:
        credential = load_credential_file(credential_file_path)
        checks["credential_file_ok"] = True
    except CredentialFileError as exc:
        checks["credential_file_ok"] = False
        errors.append(str(exc))

    api_base_url = resolve_api_base_url(api_base_url_cli)
    checks["api_base_url_provided"] = api_base_url is not None
    if api_base_url is None:
        errors.append(
            "--api-base-url or COGNITIVE_HOMOLOG_API_URL is required"
        )

    homolog_shaped = bool(api_base_url) and looks_homolog_shaped(api_base_url)
    checks["api_base_url_homolog_shaped"] = homolog_shaped
    if api_base_url and not homolog_shaped:
        errors.append(
            f"--api-base-url {api_base_url!r} does not look Homolog-shaped "
            "(expected 'homolog' in the URL) — this is only a heuristic "
            "sanity check, refusing anyway to avoid an accidental "
            "Production-looking target"
        )

    ok = not errors
    return PreconditionsReport(
        ok=ok, checks=checks, errors=errors, credential=credential, api_base_url=api_base_url,
    )


def _common_gate(args: argparse.Namespace) -> tuple[CredentialFile, str] | None:
    """Shared fail-closed gate for every capability-calling subcommand.

    Checks --environment homolog + COGNITIVE_LIVE_MCP=1 + credential file +
    api_base_url resolution. Does NOT re-run the homolog-shaped URL heuristic
    (that lives in verify-preconditions / run_preconditions only, per the
    documented split of responsibilities). Prints a clear reason and returns
    None on any failure — never raises past this point.
    """
    try:
        check_environment_flag(args.environment)
        check_live_mcp_flag()
    except EnvironmentGateError as exc:
        print(f"GATE_REFUSED: {exc}")
        return None

    try:
        credential = load_credential_file(args.credential_file)
    except CredentialFileError as exc:
        print(f"GATE_REFUSED: {exc}")
        return None

    api_base_url = resolve_api_base_url(args.api_base_url)
    if api_base_url is None:
        print(
            "GATE_REFUSED: --api-base-url or COGNITIVE_HOMOLOG_API_URL is required"
        )
        return None

    return credential, api_base_url


# ─── HTTP request building (public, documented contract) ─────────────────

def build_execute_url(api_base_url: str, capability_id: str) -> str:
    return f"{api_base_url.rstrip('/')}/v1/capabilities/{capability_id}/execute"


def build_headers(cred: CredentialFile, correlation_id: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {cred.credential}",
        "X-Tenant-Id": cred.tenant_id,
        "X-Actor-Id": cred.actor_id,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if correlation_id:
        headers["X-Correlation-Id"] = correlation_id
    return headers


def build_positive_body(resource_key: str, idempotency_key: str | None) -> dict[str, Any]:
    body: dict[str, Any] = {"params": {"resource": resource_key}}
    if idempotency_key:
        body["idempotency_key"] = idempotency_key
    return body


def build_negative_body(
    resource_key: str, forbidden_key: str, idempotency_key: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "params": {"resource": resource_key, forbidden_key: "whatever"},
    }
    if idempotency_key:
        body["idempotency_key"] = idempotency_key
    return body


def generate_idempotency_key() -> str:
    return f"e2e-gate-{uuid.uuid4()}"


def _sanitize(text: str, cred: CredentialFile | None = None) -> str:
    """Strips the raw credential value out of anything printed/raised, best-effort."""
    if cred and cred.credential and cred.credential in text:
        text = text.replace(cred.credential, "***")
    return text


# ─── HTTP call ─────────────────────────────────────────────────────────────

async def call_execute(
    api_base_url: str,
    capability_id: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: float = DEFAULT_HTTP_TIMEOUT,
) -> httpx.Response:
    url = build_execute_url(api_base_url, capability_id)
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.post(url, headers=headers, json=body)


# ─── verify-preconditions ─────────────────────────────────────────────────

def cmd_verify_preconditions(args: argparse.Namespace) -> int:
    report = run_preconditions(args.environment, args.credential_file, args.api_base_url)
    for name, passed in report.checks.items():
        print(f"{name}={'PASS' if passed else 'FAIL'}")
    if report.credential is not None:
        print(f"credential_tenant_id={report.credential.tenant_id}")
        print(f"credential_capability_id={report.credential.capability_id}")
        print(f"credential_resource_key={report.credential.resource_key}")
    if report.api_base_url is not None:
        print(f"api_base_url={report.api_base_url}")
    for err in report.errors:
        print(f"error={err}")
    print(f"PRECONDITIONS_RESULT={'PASS' if report.ok else 'FAIL'}")
    return 0 if report.ok else 1


# ─── run-positive ──────────────────────────────────────────────────────────

async def _run_positive_async(
    cred: CredentialFile, api_base_url: str, verbose: bool,
) -> tuple[int, dict[str, Any] | None]:
    idempotency_key = generate_idempotency_key()
    print(f"idempotency_key={idempotency_key}")

    headers = build_headers(cred)
    body = build_positive_body(cred.resource_key, idempotency_key)

    try:
        response = await call_execute(api_base_url, cred.capability_id, headers, body)
    except httpx.HTTPError as exc:
        print(f"error=HTTP transport error: {_sanitize(str(exc), cred)}")
        return 1, None

    try:
        payload = response.json()
    except ValueError:
        print(f"error=non-JSON response (http_status={response.status_code})")
        return 1, None

    execution_id = payload.get("execution_id")
    correlation_id = payload.get("correlation_id")
    audit_id = payload.get("audit_id")
    status = payload.get("status")
    data = payload.get("data") or {}
    error = payload.get("error")

    print(f"http_status={response.status_code}")
    print(f"execution_id={execution_id}")
    print(f"correlation_id={correlation_id}")
    print(f"audit_id={audit_id}")
    print(f"status={status}")
    if error:
        print(f"error={error}")

    present_keys = [k for k in EXPECTED_TOOL_RESULT_KEYS if k in data]
    missing_keys = [k for k in EXPECTED_TOOL_RESULT_KEYS if k not in data]
    print(f"tool_result_keys_present={present_keys}")
    if missing_keys:
        print(f"tool_result_keys_missing={missing_keys}")

    if verbose:
        print(f"raw_response={json.dumps(payload, default=str)}")

    ok = (
        response.status_code == 200
        and status == GatewayStatus.COMPLETED.value
        and not missing_keys
    )
    print(f"RUN_POSITIVE_RESULT={'PASS' if ok else 'FAIL'}")
    result = {
        "execution_id": execution_id,
        "correlation_id": correlation_id,
        "audit_id": audit_id,
        "status": status,
        "data": data,
    }
    return (0 if ok else 1), result


def cmd_run_positive(args: argparse.Namespace) -> int:
    gate = _common_gate(args)
    if gate is None:
        return 1
    cred, api_base_url = gate

    exit_code, result = asyncio.run(_run_positive_async(cred, api_base_url, args.verbose))

    correlation_id_out = getattr(args, "correlation_id_out", None)
    if correlation_id_out and result and result.get("correlation_id"):
        out_path = Path(correlation_id_out)
        out_path.write_text(str(result["correlation_id"]), encoding="utf-8")
        print(f"correlation_id_out={out_path}")

    return exit_code


# ─── run-negative ──────────────────────────────────────────────────────────

async def _run_negative_async(cred: CredentialFile, api_base_url: str) -> int:
    headers = build_headers(cred)
    all_ok = True

    for forbidden_key in sorted(FORBIDDEN_ARG_KEYS):
        body = build_negative_body(cred.resource_key, forbidden_key)
        try:
            response = await call_execute(api_base_url, cred.capability_id, headers, body)
        except httpx.HTTPError as exc:
            print(f"{forbidden_key}: FAIL (transport error: {_sanitize(str(exc), cred)})")
            all_ok = False
            continue

        try:
            payload = response.json()
        except ValueError:
            print(f"{forbidden_key}: FAIL (non-JSON response, http_status={response.status_code})")
            all_ok = False
            continue

        status = payload.get("status")
        rejected = status == GatewayStatus.FAILED.value
        print(f"{forbidden_key}: {'PASS' if rejected else 'FAIL'} (status={status})")
        if not rejected:
            all_ok = False

    print(f"RUN_NEGATIVE_RESULT={'PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


def cmd_run_negative(args: argparse.Namespace) -> int:
    gate = _common_gate(args)
    if gate is None:
        return 1
    cred, api_base_url = gate
    return asyncio.run(_run_negative_async(cred, api_base_url))


# ─── run-idempotency ────────────────────────────────────────────────────────

async def _run_idempotency_async(cred: CredentialFile, api_base_url: str) -> int:
    print(
        "NOTE: idempotency is in-process only — does not survive restart or "
        "span multiple app instances (Sprint 0.3 known limitation, not "
        "addressed here)."
    )

    headers = build_headers(cred)
    key_a = generate_idempotency_key()
    key_b = generate_idempotency_key()

    async def _call(idempotency_key: str | None) -> dict[str, Any] | None:
        body = build_positive_body(cred.resource_key, idempotency_key)
        try:
            response = await call_execute(api_base_url, cred.capability_id, headers, body)
        except httpx.HTTPError as exc:
            print(f"error=HTTP transport error: {_sanitize(str(exc), cred)}")
            return None
        try:
            return response.json()
        except ValueError:
            print(f"error=non-JSON response (http_status={response.status_code})")
            return None

    # Call 1: first request with key_a — expect a fresh COMPLETED execution.
    resp1 = await _call(key_a)
    print(f"call_1(key={key_a}) execution_id={resp1.get('execution_id') if resp1 else None}")

    # Call 2: SAME key_a — expect the orchestrator's in-process cache to
    # return the identical execution_id (cache hit, no second real MCP call).
    resp2 = await _call(key_a)
    print(f"call_2(key={key_a}) execution_id={resp2.get('execution_id') if resp2 else None}")

    # Call 3: DIFFERENT key (key_b) — expect a genuinely new execution_id.
    resp3 = await _call(key_b)
    print(f"call_3(key={key_b}) execution_id={resp3.get('execution_id') if resp3 else None}")

    # Call 4: NO idempotency key at all — expect normal (non-cached) behavior.
    resp4 = await _call(None)
    print(f"call_4(key=None) execution_id={resp4.get('execution_id') if resp4 else None}")

    if not all([resp1, resp2, resp3, resp4]):
        print("RUN_IDEMPOTENCY_RESULT=FAIL (one or more calls failed transport/parse)")
        return 1

    cache_hit_ok = resp1["execution_id"] == resp2["execution_id"]
    new_execution_ok = resp3["execution_id"] != resp1["execution_id"]
    no_key_distinct_ok = resp4["execution_id"] not in (
        resp1["execution_id"], resp3["execution_id"],
    )

    print(f"cache_hit_same_execution_id={'PASS' if cache_hit_ok else 'FAIL'}")
    print(f"different_key_new_execution_id={'PASS' if new_execution_ok else 'FAIL'}")
    print(f"no_key_is_distinct_execution={'PASS' if no_key_distinct_ok else 'FAIL'}")

    ok = cache_hit_ok and new_execution_ok and no_key_distinct_ok
    print(f"RUN_IDEMPOTENCY_RESULT={'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def cmd_run_idempotency(args: argparse.Namespace) -> int:
    gate = _common_gate(args)
    if gate is None:
        return 1
    cred, api_base_url = gate
    return asyncio.run(_run_idempotency_async(cred, api_base_url))


# ─── run-performance ────────────────────────────────────────────────────────

async def _run_performance_async(cred: CredentialFile, api_base_url: str) -> int:
    idempotency_key = generate_idempotency_key()  # fresh key: avoid cache hit
    headers = build_headers(cred)
    body = build_positive_body(cred.resource_key, idempotency_key)

    start = time.perf_counter()
    try:
        response = await call_execute(api_base_url, cred.capability_id, headers, body)
    except httpx.HTTPError as exc:
        print(f"error=HTTP transport error: {_sanitize(str(exc), cred)}")
        return 1
    total_duration_ms = (time.perf_counter() - start) * 1000.0

    try:
        payload = response.json()
    except ValueError:
        print(f"error=non-JSON response (http_status={response.status_code})")
        return 1

    status = payload.get("status")
    data = payload.get("data") or {}

    print(f"total_wallclock_duration_ms={total_duration_ms:.1f}")
    print(
        "NOTE: total_wallclock_duration_ms is this runner's OWN measurement "
        "of the full HTTP round trip — CapabilityExecuteResponse "
        "(contracts/gateway.py) has no duration_ms/timing-breakdown field of "
        "its own, so an adapter/MCP-only sub-duration cannot be reported from "
        "the HTTP response alone. audit_events.duration_ms exists in the DB "
        "(see execution/orchestrator.py) but is not returned over HTTP — see "
        "test_live_mcp_e2e_audit_telemetry.py for a DB-side check of that value."
    )

    tool_calls = len(data) if isinstance(data, dict) else 0
    print(f"tool_calls={tool_calls}")
    print(
        "NOTE: tool_calls is INFERRED as len(response.data) — "
        "CapabilityExecuteResponse has no dedicated tool_calls field either; "
        "this assumes every tool that ran wrote one key into `data` "
        "(matches execution/orchestrator.py._run_capability_tools, which is "
        "true as of Sprint 0.3 but not schema-guaranteed)."
    )

    print("llm_calls=0")
    print(
        "NOTE: llm_calls=0 is a fact about the code, not something the "
        "response reports — execution/orchestrator.py._run_capability_tools "
        "only calls self._adapter.invoke_tool(...) in a deterministic "
        "sequence; there is no LLM call anywhere in this pipeline."
    )

    print(f"status={status}")
    ok = response.status_code == 200 and status == GatewayStatus.COMPLETED.value
    print(f"RUN_PERFORMANCE_RESULT={'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def cmd_run_performance(args: argparse.Namespace) -> int:
    gate = _common_gate(args)
    if gate is None:
        return 1
    cred, api_base_url = gate
    return asyncio.run(_run_performance_async(cred, api_base_url))


# ─── run-full ──────────────────────────────────────────────────────────────

def cmd_run_full(args: argparse.Namespace) -> int:
    steps: list[tuple[str, Any]] = [
        ("verify-preconditions", cmd_verify_preconditions),
        ("run-positive", cmd_run_positive),
        ("run-negative", cmd_run_negative),
        ("run-idempotency", cmd_run_idempotency),
        ("run-performance", cmd_run_performance),
    ]
    for name, fn in steps:
        print(f"\n=== STEP: {name} ===")
        rc = fn(args)
        if rc != 0:
            print(f"\nGATE_RESULT=FAILED at step={name}")
            return rc
    print("\nGATE_RESULT=PASS")
    return 0


# ─── CLI ─────────────────────────────────────────────────────────────────

def _add_common_args(sub: argparse.ArgumentParser) -> None:
    sub.add_argument(
        "--environment",
        required=True,
        help=(
            "Must be exactly 'homolog'. Explicit positive confirmation required "
            "on every subcommand — fail-closed, no default."
        ),
    )
    sub.add_argument(
        "--credential-file",
        required=True,
        help=(
            "Path to the JSON credential file written by "
            "'sprint_0_3_synthetic_context.py bootstrap-homolog-context' "
            "(tenant_id/actor_id/credential/resource_key/capability_id)."
        ),
    )
    sub.add_argument(
        "--api-base-url",
        default=None,
        help="Homolog API base URL. Falls back to COGNITIVE_HOMOLOG_API_URL.",
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Sprint 0.3 — Live MCP E2E Gate Runner. Proves the full "
            "Identity -> Registry -> ResourceResolver -> Policy -> Adapter -> "
            "live MCP -> Result -> Audit -> Telemetry chain against a real "
            "deployed Homolog API. Refuses to run against anything not "
            "explicitly declared --environment homolog."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_pre = sub.add_parser(
        "verify-preconditions",
        help="Check env/credential/URL preconditions WITHOUT calling the API.",
    )
    _add_common_args(p_pre)

    p_pos = sub.add_parser(
        "run-positive",
        help="Execute ONE infra.inspect call against the real Homolog API.",
    )
    _add_common_args(p_pos)
    p_pos.add_argument(
        "--verbose", action="store_true",
        help="Also print the full raw response body (may contain infra details).",
    )
    p_pos.add_argument(
        "--correlation-id-out", default=None,
        help="Write the response correlation_id to this file (for DB-side follow-up tests).",
    )

    p_neg = sub.add_parser(
        "run-negative",
        help="Send one request per FORBIDDEN_ARG_KEYS entry, assert all are rejected.",
    )
    _add_common_args(p_neg)

    p_idem = sub.add_parser(
        "run-idempotency",
        help="Prove the in-process idempotency cache behavior (4 calls).",
    )
    _add_common_args(p_idem)

    p_perf = sub.add_parser(
        "run-performance",
        help="Time the positive flow; report only fields the response actually exposes.",
    )
    _add_common_args(p_perf)

    p_full = sub.add_parser(
        "run-full",
        help="Run all steps in sequence, stop at first failure.",
    )
    _add_common_args(p_full)
    p_full.add_argument("--verbose", action="store_true")
    p_full.add_argument("--correlation-id-out", default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    handlers = {
        "verify-preconditions": cmd_verify_preconditions,
        "run-positive": cmd_run_positive,
        "run-negative": cmd_run_negative,
        "run-idempotency": cmd_run_idempotency,
        "run-performance": cmd_run_performance,
        "run-full": cmd_run_full,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
