"""Static scan for forbidden credential patterns in versioned migrations."""

from __future__ import annotations

import re
from pathlib import Path

FORBIDDEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("CREATE ROLE ... PASSWORD literal", re.compile(r"CREATE\s+ROLE\s+\w+\s+[^;]*PASSWORD\s+'", re.I)),
    ("ALTER ROLE ... PASSWORD literal", re.compile(r"ALTER\s+ROLE\s+\w+\s+PASSWORD\s+'", re.I)),
    ("postgresql:// connection string", re.compile(r"postgresql://[^\s'\"]+", re.I)),
    ("hardcoded app-dev-secret", re.compile(r"app-dev-secret", re.I)),
    ("hardcoded worker-dev-secret", re.compile(r"worker-dev-secret", re.I)),
    ("API key assignment", re.compile(r"(api[_-]?key|service[_-]?role)\s*=\s*['\"][^'\"]+['\"]", re.I)),
]


def scan_migration_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    violations: list[str] = []
    for label, pattern in FORBIDDEN_PATTERNS:
        if pattern.search(text):
            violations.append(f"{path.name}: {label}")
    return violations


def scan_migrations_dir(migrations_dir: Path) -> list[str]:
    violations: list[str] = []
    for sql_file in sorted(migrations_dir.glob("[0-9]*.sql")):
        violations.extend(scan_migration_file(sql_file))
    return violations
