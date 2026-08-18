"""
remote_safety_guard.py — Preflight the VPS Gate runs BEFORE the SAFE_REMOTE
pytest suite (`pytest tests/db -m safe_remote`) against Homolog.

Combines two independent checks and refuses to proceed unless BOTH pass:
  1. verify_target() (cognitive.gate.verify_target) — the admin DSN resolves
     to the expected Homolog project ref, not the forbidden production ref.
  2. COGNITIVE_DB_TEST_MODE is explicitly declared as 'remote_homolog'.

This mirrors the fail-closed decision in tests/db/conftest.py's
resolve_db_test_mode()/db_test_mode fixture. It is intentionally NOT imported
from there: tests/ is not part of the installed `cognitive` package, so
production code under cognitive/gate/ cannot depend on it. The check here is
a handful of lines and is exercised directly by
tests/unit/test_db_test_mode_safety.py to keep both copies honest.

Prints EXACTLY 3 lines, never a DSN, never a secret:
    target_verified=YES
    test_mode=remote_homolog
    destructive_tests=DISABLED

Callable as:
    python -m cognitive.gate.remote_safety_guard

Exits non-zero on any failure (forbidden project ref, DSN not verified,
COGNITIVE_DB_TEST_MODE missing/wrong/invalid, etc.).

NOTE: this script is a convenience preflight gate for the VPS Gate runner —
it is NOT the actual safety mechanism. The real, unconditional guarantee
lives in tests/db/conftest.py's allow_destructive_migrations fixture, which
can only be True when COGNITIVE_DB_TEST_MODE=ephemeral is explicitly set and
no real remote DSN triplet is configured. This script existing (or failing
to run, or being skipped by mistake) cannot itself cause destructive tests
to run against Homolog — it only decides whether the SAFE_REMOTE suite is
allowed to start.
"""

from __future__ import annotations

import os

from .verify_target import verify_target

_VALID_DECLARED_MODES = ("remote_homolog", "ephemeral")


class InvalidDbTestMode(Exception):
    """COGNITIVE_DB_TEST_MODE is set to something other than a recognized value."""


def resolve_db_test_mode() -> str:
    """Returns 'remote_homolog', 'ephemeral', or 'unset'. Raises
    InvalidDbTestMode if the env var is set to anything else."""
    raw = os.getenv("COGNITIVE_DB_TEST_MODE", "").strip().lower()
    if raw and raw not in _VALID_DECLARED_MODES:
        raise InvalidDbTestMode(
            f"COGNITIVE_DB_TEST_MODE inválido: {raw!r} — use 'remote_homolog' ou 'ephemeral'"
        )
    return raw or "unset"


def check_remote_safety() -> tuple[bool, str, str]:
    """Returns (ok, test_mode_value, destructive_tests_value) for the 3-line
    report. Never returns or touches the DSN itself."""
    report = verify_target(os.getenv("COGNITIVE_DB_ADMIN_URL"))

    try:
        declared = resolve_db_test_mode()
    except InvalidDbTestMode:
        return False, "INVALID", "UNKNOWN"

    if not report.verified:
        return False, declared, "UNKNOWN"

    if declared != "remote_homolog":
        return False, declared, "UNKNOWN"

    return True, "remote_homolog", "DISABLED"


def print_remote_safety_report(ok: bool, test_mode: str, destructive_tests: str) -> None:
    print(f"target_verified={'YES' if ok else 'NO'}")
    print(f"test_mode={test_mode}")
    print(f"destructive_tests={destructive_tests}")


def main() -> int:
    ok, test_mode, destructive_tests = check_remote_safety()
    print_remote_safety_report(ok, test_mode, destructive_tests)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
