"""Target verification helpers for remote gate."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from ..config.db_target import (
    FORBIDDEN_PROJECT_REF,
    HOMOLOG_PROJECT_REF,
    project_ref_from_dsn,
    verify_homolog_admin_dsn,
)


@dataclass(frozen=True)
class VerifyTargetReport:
    admin_available: bool
    project_ref: str
    connect_user: str
    expected_homolog: str
    forbidden_production: str
    forbidden_match: bool
    homolog_match: bool
    verified: bool
    reason: str

    def exit_code(self) -> int:
        return 0 if self.verified else 1


def verify_target(admin_dsn: str | None) -> VerifyTargetReport:
    if not admin_dsn:
        return VerifyTargetReport(
            admin_available=False,
            project_ref="unknown",
            connect_user="unknown",
            expected_homolog=HOMOLOG_PROJECT_REF,
            forbidden_production=FORBIDDEN_PROJECT_REF,
            forbidden_match=False,
            homolog_match=False,
            verified=False,
            reason="COGNITIVE_DB_ADMIN_URL not configured",
        )

    parsed = urlparse(admin_dsn)
    if parsed.scheme not in ("postgresql", "postgres"):
        return VerifyTargetReport(
            admin_available=True,
            project_ref="unknown",
            connect_user=parsed.username or "unknown",
            expected_homolog=HOMOLOG_PROJECT_REF,
            forbidden_production=FORBIDDEN_PROJECT_REF,
            forbidden_match=False,
            homolog_match=False,
            verified=False,
            reason="invalid DSN scheme",
        )

    ref = project_ref_from_dsn(admin_dsn) or "unknown"
    ok, reason = verify_homolog_admin_dsn(admin_dsn)
    user = parsed.username or "unknown"

    return VerifyTargetReport(
        admin_available=True,
        project_ref=ref,
        connect_user=user,
        expected_homolog=HOMOLOG_PROJECT_REF,
        forbidden_production=FORBIDDEN_PROJECT_REF,
        forbidden_match=ref == FORBIDDEN_PROJECT_REF,
        homolog_match=ref == HOMOLOG_PROJECT_REF,
        verified=ok,
        reason=reason,
    )


def print_verify_target_report(report: VerifyTargetReport) -> None:
    status = "AVAILABLE" if report.admin_available else "NOT_AVAILABLE"
    print(f"COGNITIVE_DB_ADMIN_URL={status}")
    print(f"project_ref={report.project_ref}")
    print(f"expected_homolog={report.expected_homolog}")
    print(f"forbidden_production={report.forbidden_production}")
    print(f"forbidden_match={report.forbidden_match}")
    print(f"homolog_match={report.homolog_match}")
    print(f"connect_user={report.connect_user}")
    print(f"verified={'YES' if report.verified else 'NO'}")
    print(f"reason={report.reason}")
