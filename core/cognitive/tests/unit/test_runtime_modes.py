"""tests/unit/test_runtime_modes.py — COGNITIVE_MODE e fail-closed."""

from __future__ import annotations

import os

import pytest

from cognitive.config.runtime import (
    cognitive_mode,
    is_database_mode,
    is_in_memory_mode,
    require_database_config,
)
from cognitive.tenancy.identity_resolver import IdentityResolver


class TestCognitiveMode:
    def test_default_in_memory_without_db_url(self, monkeypatch):
        monkeypatch.delenv("COGNITIVE_MODE", raising=False)
        monkeypatch.delenv("COGNITIVE_DB_URL", raising=False)
        assert cognitive_mode() == "in_memory"
        assert is_in_memory_mode()

    def test_explicit_database_mode(self, monkeypatch):
        monkeypatch.setenv("COGNITIVE_MODE", "database")
        monkeypatch.setenv("COGNITIVE_DB_URL", "postgresql://app:x@db.esvjfkknrzzziafovwrv.supabase.co:5432/postgres")
        monkeypatch.setenv("COGNITIVE_DB_ADMIN_URL", "postgresql://postgres:x@db.esvjfkknrzzziafovwrv.supabase.co:5432/postgres")
        assert is_database_mode()

    def test_database_mode_requires_admin_url(self, monkeypatch):
        monkeypatch.setenv("COGNITIVE_MODE", "database")
        monkeypatch.setenv("COGNITIVE_DB_URL", "postgresql://app:x@db.esvjfkknrzzziafovwrv.supabase.co:5432/postgres")
        monkeypatch.delenv("COGNITIVE_DB_ADMIN_URL", raising=False)
        with pytest.raises(RuntimeError, match="COGNITIVE_DB_ADMIN_URL"):
            require_database_config()


class TestIdentityResolverFailClosed:
    @pytest.mark.asyncio
    async def test_database_mode_no_static_fallback(self):
        resolver = IdentityResolver(identity_repo=None, database_mode=True)
        with pytest.raises(ValueError, match="Credencial inválida"):
            await resolver.resolve(
                "Bearer unknown",
                "tenant-a",
                "actor-a",
                None,
            )

    @pytest.mark.asyncio
    async def test_in_memory_mode_uses_static(self):
        resolver = IdentityResolver(identity_repo=None, database_mode=False)
        resolver.register_static("secret-a", "tenant-a", "actor-a", "owner-core")
        ctx = await resolver.resolve(
            "Bearer secret-a",
            "tenant-a",
            "actor-a",
            "corr",
        )
        assert ctx.tenant_id == "tenant-a"
