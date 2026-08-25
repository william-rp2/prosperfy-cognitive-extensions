#!/usr/bin/env python3
"""
consolidate_memory_md.py — Fail-closed MEMORY.md consolidation (Sprint 0.7.8.4).

Replacement spec (JSON) — per entry key (1-based index string):

  {
    "7": {
      "expected_sha256": "<hex of exact current entry text>",
      "replacement_text": "..."
    },
    "9": {
      "expected_text": "exact current entry (alternative to sha256)",
      "replacement_text": "..."
    }
  }

All entries must validate before ANY write. On mismatch: ABORT ALL.
Entry 6 is never auto-removed (MANUAL_REVIEW_REQUIRED).

Usage:
  python scripts/consolidate_memory_md.py --replacements spec.json
  python scripts/consolidate_memory_md.py --apply --replacements spec.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENTRY_DELIMITER = "§"


def memory_path() -> Path:
    home = Path(os.getenv("HERMES_HOME", Path.home() / ".hermes"))
    return home / "memories" / "MEMORY.md"


def parse_entries(raw: str) -> list[str]:
    if not raw.strip():
        return []
    return [e.strip() for e in raw.split(ENTRY_DELIMITER) if e.strip()]


def join_entries(entries: list[str]) -> str:
    if not entries:
        return ""
    return ENTRY_DELIMITER.join(entries) + ENTRY_DELIMITER


def entry_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stats(entries: list[str]) -> dict[str, int]:
    joined = join_entries(entries)
    return {
        "MEMORY_ENTRY_COUNT": len(entries),
        "MEMORY_TOTAL_CHARS": len(joined),
    }


def validate_replacement_spec(
    entries: list[str], spec: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """Return (new_entries, log_lines). Raises ValueError on any mismatch."""
    new_entries = list(entries)
    logs: list[str] = []
    for key, rule in sorted(spec.items(), key=lambda kv: int(kv[0])):
        idx = int(key) - 1
        if idx < 0 or idx >= len(new_entries):
            raise ValueError(f"INVALID_INDEX={key} count={len(new_entries)}")
        if not isinstance(rule, dict):
            raise ValueError(f"INVALID_RULE={key} must be object")
        current = new_entries[idx]
        expected_sha = rule.get("expected_sha256")
        expected_text = rule.get("expected_text")
        replacement = rule.get("replacement_text")
        if replacement is None:
            raise ValueError(f"MISSING_REPLACEMENT_TEXT={key}")
        if expected_sha is not None:
            if entry_sha256(current) != str(expected_sha).lower():
                raise ValueError(
                    f"FINGERPRINT_MISMATCH={key} sha256={entry_sha256(current)}"
                )
        elif expected_text is not None:
            if current != str(expected_text):
                raise ValueError(f"TEXT_MISMATCH={key}")
        else:
            raise ValueError(f"MISSING_FINGERPRINT={key} need expected_sha256 or expected_text")
        if key == "6":
            raise ValueError("ENTRY6_AUTO_MODIFY_FORBIDDEN=MANUAL_REVIEW_REQUIRED")
        old_len = len(current)
        new_entries[idx] = str(replacement).strip()
        logs.append(
            f"ENTRY{key}_VALIDATED=YES old_chars={old_len} new_chars={len(new_entries[idx])}"
        )
    return new_entries, logs


def entry6_status(entries: list[str]) -> str:
    if len(entries) < 6:
        return "MISSING"
    low = entries[5].lower()
    if "hermeswork" in low or "venv" in low:
        return "MANUAL_REVIEW_REQUIRED"
    return "NO_HERMESWORK_VENV_REF"


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed MEMORY.md consolidation")
    parser.add_argument("--apply", action="store_true", help="Write after validation")
    parser.add_argument("--replacements", type=Path, required=True)
    args = parser.parse_args()

    path = memory_path()
    if not path.exists():
        print(f"MEMORY_FILE_MISSING={path}")
        return 1

    raw = path.read_text(encoding="utf-8-sig")
    entries = parse_entries(raw)
    before = stats(entries)
    print(f"MEMORY_CHARS_BEFORE={before['MEMORY_TOTAL_CHARS']}")
    print(f"MEMORY_ENTRY_COUNT_BEFORE={before['MEMORY_ENTRY_COUNT']}")
    print(f"ENTRY6_STATUS={entry6_status(entries)}")

    spec = json.loads(args.replacements.read_text(encoding="utf-8"))
    try:
        new_entries, logs = validate_replacement_spec(entries, spec)
    except ValueError as exc:
        print(f"CONSOLIDATION_ABORT={exc}")
        print("CONSOLIDATION_ATOMIC_OR_FAIL_CLOSED=YES")
        return 1

    for line in logs:
        print(line)

    after = stats(new_entries)
    print(f"MEMORY_CHARS_AFTER={after['MEMORY_TOTAL_CHARS']}")
    print(f"MEMORY_ENTRY_COUNT_AFTER={after['MEMORY_ENTRY_COUNT']}")
    print(f"CHARS_FREED={before['MEMORY_TOTAL_CHARS'] - after['MEMORY_TOTAL_CHARS']}")

    if not args.apply:
        print("DRY_RUN=YES (pass --apply to write)")
        print("CONSOLIDATION_ATOMIC_OR_FAIL_CLOSED=YES")
        return 0

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_suffix(f".md.bak-{ts}")
    shutil.copy2(path, backup)
    try:
        path.write_text(join_entries(new_entries), encoding="utf-8")
    except OSError as exc:
        print(f"WRITE_FAILED={exc}")
        print(f"RESTORE_FROM={backup}")
        return 1

    print(f"MEMORY_BACKUP_CREATED=YES path={backup}")
    print("CONSOLIDATION_ATOMIC_OR_FAIL_CLOSED=YES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
