"""Gateway metadata — version and environment (no secrets)."""

from __future__ import annotations

import os


def api_version() -> str:
    return os.getenv("COGNITIVE_API_VERSION", "0.2.0")


def service_name() -> str:
    return "prosperfy-cognitive"


def deployment_environment() -> str:
    """
    homolog | production | development

    COGNITIVE_ENV explicit; defaults to development.
    """
    env = os.getenv("COGNITIVE_ENV", "development").strip().lower()
    if env in ("homolog", "staging", "production", "development"):
        return "homolog" if env == "staging" else env
    return "development"
