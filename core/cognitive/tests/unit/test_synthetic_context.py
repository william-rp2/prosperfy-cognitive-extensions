"""
tests/unit/test_synthetic_context.py — scripts/sprint_0_3_synthetic_context.py.

NO real DB. Every DB interaction is mocked at the module boundary
(create_pools/admin_connection/close_pools, ServiceIdentityRepository,
TenantResourceRepository) using a FakeConn that records every executed
query so tests can assert exactly what SQL would have run.

This script is operator-run tooling for the Homolog Gate; it must never be
exercised against a real database in CI or in this session (DG-001 — no
DB access here).
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = REPO_ROOT / "scripts" / "sprint_0_3_synthetic_context.py"

from cognitive.config.db_target import FORBIDDEN_PROJECT_REF, HOMOLOG_PROJECT_REF  # noqa: E402


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        "sprint_0_3_synthetic_context", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sctx = _load_script_module()

HOMOLOG_DSN = f"postgresql://postgres:secret@db.{HOMOLOG_PROJECT_REF}.supabase.co:5432/postgres"
FORBIDDEN_DSN = f"postgresql://postgres:secret@db.{FORBIDDEN_PROJECT_REF}.supabase.co:5432/postgres"


class FakeConn:
    """Records every executed query so tests can assert exact SQL shape."""

    def __init__(self, fetchrow_results=None, fetchval_results=None, execute_results=None):
        self.calls: list[tuple[str, str, tuple]] = []
        self._fetchrow_results = list(fetchrow_results or [])
        self._fetchval_results = list(fetchval_results or [])
        self._execute_results = list(execute_results or [])

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self._fetchrow_results.pop(0) if self._fetchrow_results else None

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, args))
        return self._fetchval_results.pop(0) if self._fetchval_results else None

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return self._execute_results.pop(0) if self._execute_results else "DELETE 0"


def _mock_admin_connection(conn: FakeConn) -> MagicMock:
    """A mock for `admin_connection` — an async-context-manager factory."""

    def _factory():
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=conn)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    return MagicMock(side_effect=_factory)


def _patch_pool_lifecycle(monkeypatch, conn: FakeConn):
    monkeypatch.setattr(sctx, "create_pools", AsyncMock())
    monkeypatch.setattr(sctx, "close_pools", AsyncMock())
    monkeypatch.setattr(sctx, "admin_connection", _mock_admin_connection(conn))


def _patch_repos(monkeypatch, register_result=None, upsert_result=None):
    identity_cls = MagicMock()
    identity_cls.return_value.register = AsyncMock(return_value=register_result)
    monkeypatch.setattr(sctx, "ServiceIdentityRepository", identity_cls)

    resource_cls = MagicMock()
    resource_cls.return_value.upsert = AsyncMock(return_value=upsert_result)
    monkeypatch.setattr(sctx, "TenantResourceRepository", resource_cls)

    return identity_cls, resource_cls


# ─── 1. bootstrap refuses when target verification fails — zero writes ────


class TestBootstrapRefusesOnVerificationFailure:
    @pytest.mark.asyncio
    async def test_refuses_and_makes_zero_write_calls(self, monkeypatch):
        create_pools_mock = AsyncMock()
        admin_connection_mock = MagicMock()
        monkeypatch.setattr(sctx, "create_pools", create_pools_mock)
        monkeypatch.setattr(sctx, "close_pools", AsyncMock())
        monkeypatch.setattr(sctx, "admin_connection", admin_connection_mock)

        with pytest.raises(sctx.TargetVerificationError):
            await sctx.bootstrap_context("not-a-valid-dsn", None)

        create_pools_mock.assert_not_called()
        admin_connection_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_refuses_when_admin_dsn_missing(self, monkeypatch):
        create_pools_mock = AsyncMock()
        monkeypatch.setattr(sctx, "create_pools", create_pools_mock)
        monkeypatch.setattr(sctx, "close_pools", AsyncMock())

        with pytest.raises(sctx.TargetVerificationError):
            await sctx.bootstrap_context("", None)

        create_pools_mock.assert_not_called()


# ─── 2. explicit forbidden-ref rejection ───────────────────────────────────


class TestBootstrapRefusesForbiddenRef:
    @pytest.mark.asyncio
    async def test_refuses_forbidden_project_ref_specifically(self, monkeypatch):
        create_pools_mock = AsyncMock()
        monkeypatch.setattr(sctx, "create_pools", create_pools_mock)
        monkeypatch.setattr(sctx, "close_pools", AsyncMock())

        with pytest.raises(sctx.TargetVerificationError) as excinfo:
            await sctx.bootstrap_context(FORBIDDEN_DSN, None)

        assert "forbidden" in str(excinfo.value)
        create_pools_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_teardown_also_refuses_forbidden_ref(self, monkeypatch):
        create_pools_mock = AsyncMock()
        monkeypatch.setattr(sctx, "create_pools", create_pools_mock)
        monkeypatch.setattr(sctx, "close_pools", AsyncMock())

        with pytest.raises(sctx.TargetVerificationError) as excinfo:
            await sctx.teardown_context(FORBIDDEN_DSN)

        assert "forbidden" in str(excinfo.value)
        create_pools_mock.assert_not_called()


# ─── 3. credential entropy / uniqueness ────────────────────────────────────


class TestCredentialGeneration:
    def test_credential_has_sufficient_length(self):
        cred = sctx._generate_synthetic_credential()
        assert isinstance(cred, str)
        assert len(cred) >= 32

    def test_credential_never_repeats(self):
        creds = {sctx._generate_synthetic_credential() for _ in range(50)}
        assert len(creds) == 50

    def test_credential_uses_secrets_module(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        assert "secrets.token_urlsafe" in source
        assert "random.choice" not in source
        assert "random.random" not in source


# ─── 4. credential file permissions ────────────────────────────────────────


class TestCredentialFilePermissions:
    def test_os_chmod_called_with_0600(self, tmp_path, monkeypatch):
        chmod_calls = []
        real_chmod = sctx.os.chmod

        def _spy_chmod(path, mode):
            chmod_calls.append((str(path), mode))
            return real_chmod(path, mode)

        monkeypatch.setattr(sctx.os, "chmod", _spy_chmod)

        out = tmp_path / "cred.json"
        sctx._write_credential_file(str(out), {"tenant_id": "x", "credential": "y"})

        assert chmod_calls, "os.chmod was never called"
        assert any(mode == 0o600 for _, mode in chmod_calls)

    def test_file_content_round_trips(self, tmp_path):
        out = tmp_path / "cred.json"
        payload = {
            "tenant_id": "t-1",
            "actor_id": sctx.SYNTHETIC_ACTOR_ID,
            "credential": "raw-value",
            "resource_key": sctx.SYNTHETIC_RESOURCE_KEY,
            "capability_id": sctx.SYNTHETIC_CAPABILITY_ID,
        }
        sctx._write_credential_file(str(out), payload)
        assert json.loads(out.read_text(encoding="utf-8")) == payload

    # NOTE: os.chmod's mode bits don't map 1:1 onto Windows ACLs the way they
    # do on POSIX (documented in _write_credential_file's docstring). This
    # environment cannot verify the real-world POSIX guarantee — only that
    # the restrictive-mode call happens on the code path, which the test
    # above does verify regardless of host OS.


# ─── 5. credential never printed or logged ─────────────────────────────────


class TestCredentialNeverLeaked:
    @pytest.mark.asyncio
    async def test_bootstrap_context_never_prints_credential(
        self, monkeypatch, tmp_path, capsys, caplog
    ):
        conn = FakeConn(fetchrow_results=[{"id": uuid.uuid4()}])
        _patch_pool_lifecycle(monkeypatch, conn)
        _patch_repos(monkeypatch)

        caplog.set_level(logging.DEBUG)
        context = await sctx.bootstrap_context(
            HOMOLOG_DSN,
            {"host": "test.invalid", "type": "vps"},
            credential_out=str(tmp_path / "cred.json"),
        )

        out = capsys.readouterr().out
        assert context.credential not in out
        assert context.credential not in caplog.text

    def test_cli_bootstrap_handler_never_prints_credential(
        self, monkeypatch, tmp_path, capsys, caplog
    ):
        # NOTE: intentionally NOT an async test — cmd_bootstrap_homolog_context
        # drives its own event loop via asyncio.run() internally, which raises
        # if called from inside a loop pytest-asyncio already started for us.
        conn = FakeConn(fetchrow_results=[{"id": uuid.uuid4()}])
        _patch_pool_lifecycle(monkeypatch, conn)
        _patch_repos(monkeypatch)
        monkeypatch.setenv("COGNITIVE_DB_ADMIN_URL", HOMOLOG_DSN)

        captured_credential = {}
        original = sctx.bootstrap_context

        async def _spy(*args, **kwargs):
            result = await original(*args, **kwargs)
            captured_credential["value"] = result.credential
            return result

        monkeypatch.setattr(sctx, "bootstrap_context", _spy)

        args = argparse_namespace(
            resource_host="test.invalid", credential_out=str(tmp_path / "cred.json")
        )
        caplog.set_level(logging.DEBUG)
        rc = sctx.cmd_bootstrap_homolog_context(args)

        out = capsys.readouterr().out
        assert rc == 0
        assert captured_credential["value"] not in out
        assert captured_credential["value"] not in caplog.text
        assert "credential_file=" in out
        assert "WARNING" in out
        assert "NEVER commit" in out


def argparse_namespace(**kwargs):
    import argparse

    return argparse.Namespace(**kwargs)


# ─── 6. teardown graceful no-op ────────────────────────────────────────────


class TestTeardownNoOp:
    @pytest.mark.asyncio
    async def test_noop_when_tenant_absent(self, monkeypatch, capsys):
        conn = FakeConn(fetchval_results=[None])
        _patch_pool_lifecycle(monkeypatch, conn)

        result = await sctx.teardown_context(HOMOLOG_DSN)

        assert result == {}
        execute_calls = [c for c in conn.calls if c[0] == "execute"]
        assert execute_calls == []
        out = capsys.readouterr().out
        assert "already torn down, nothing to do" in out


# ─── 7. teardown SQL shape — only scoped DELETE/SELECT, never DROP/TRUNCATE ─


class TestTeardownSqlShape:
    @pytest.mark.asyncio
    async def test_every_query_is_scoped_never_drop_or_truncate(self, monkeypatch):
        fake_tenant_id = uuid.uuid4()
        conn = FakeConn(fetchval_results=[fake_tenant_id])
        _patch_pool_lifecycle(monkeypatch, conn)

        await sctx.teardown_context(HOMOLOG_DSN)

        assert conn.calls, "no queries were executed"
        for method, sql, args in conn.calls:
            upper = sql.upper()
            assert "DROP" not in upper
            assert "TRUNCATE" not in upper
            assert "WHERE" in upper
            if method == "fetchval":
                assert "WHERE SLUG = $1" in upper or "WHERE" in upper
                assert args == (sctx.SYNTHETIC_TENANT_SLUG,)
            else:
                assert "WHERE TENANT_ID = $1" in upper or "WHERE ID = $1" in upper
                assert args == (fake_tenant_id,)


# ─── 8. teardown covers every table, FK-safe order ─────────────────────────


class TestTeardownTableOrder:
    def test_expected_table_set_and_order(self):
        assert sctx.TEARDOWN_TABLES == (
            "audit_events",
            "execution_traces",
            "cost_telemetry",
            # identity_events (migration 003) referencia service_identities SEM
            # ON DELETE CASCADE — removido ANTES de service_identities (fix de
            # ordem de FK, mesmo padrão da Sprint 0.4 em tests/db/conftest.py).
            "identity_events",
            "service_identities",
            "tenant_resources",
            "capability_grants",
            "tenant_members",
            "credential_refs",
            "tenant_integrations",
        )

    @pytest.mark.asyncio
    async def test_deletes_every_table_then_tenants_last(self, monkeypatch):
        fake_tenant_id = uuid.uuid4()
        conn = FakeConn(fetchval_results=[fake_tenant_id])
        _patch_pool_lifecycle(monkeypatch, conn)

        counts = await sctx.teardown_context(HOMOLOG_DSN)

        execute_calls = [c for c in conn.calls if c[0] == "execute"]
        deleted_tables_in_order = []
        for _, sql, _args in execute_calls:
            # "DELETE FROM <table> WHERE ..."
            table = sql.split("FROM", 1)[1].strip().split()[0]
            deleted_tables_in_order.append(table)

        assert deleted_tables_in_order == list(sctx.TEARDOWN_TABLES) + ["tenants"]
        assert deleted_tables_in_order[-1] == "tenants"
        assert set(counts.keys()) == set(sctx.TEARDOWN_TABLES) | {"tenants"}


# ─── Idempotency of bootstrap steps (upsert patterns) ──────────────────────


class TestBootstrapIdempotentSql:
    @pytest.mark.asyncio
    async def test_tenant_upsert_uses_on_conflict_do_update(self, monkeypatch, tmp_path):
        conn = FakeConn(fetchrow_results=[{"id": uuid.uuid4()}])
        _patch_pool_lifecycle(monkeypatch, conn)
        _patch_repos(monkeypatch)

        await sctx.bootstrap_context(
            HOMOLOG_DSN,
            {"host": "test.invalid", "type": "vps"},
            credential_out=str(tmp_path / "cred.json"),
        )

        tenant_call = next(c for c in conn.calls if "INSERT INTO tenants" in c[1])
        assert "ON CONFLICT (slug) DO UPDATE" in tenant_call[1]
        assert tenant_call[2] == (sctx.SYNTHETIC_TENANT_SLUG, sctx.SYNTHETIC_TENANT_NAME)

    @pytest.mark.asyncio
    async def test_capability_grant_upsert_uses_on_conflict_do_nothing(
        self, monkeypatch, tmp_path
    ):
        conn = FakeConn(fetchrow_results=[{"id": uuid.uuid4()}])
        _patch_pool_lifecycle(monkeypatch, conn)
        _patch_repos(monkeypatch)

        await sctx.bootstrap_context(
            HOMOLOG_DSN,
            {"host": "test.invalid", "type": "vps"},
            credential_out=str(tmp_path / "cred.json"),
        )

        grant_call = next(c for c in conn.calls if "INSERT INTO capability_grants" in c[1])
        assert "ON CONFLICT (tenant_id, profile, capability_id) DO NOTHING" in grant_call[1]

    @pytest.mark.asyncio
    async def test_falls_back_to_placeholder_and_warns_when_no_resource_params(
        self, monkeypatch, tmp_path, capsys
    ):
        conn = FakeConn(fetchrow_results=[{"id": uuid.uuid4()}])
        _patch_pool_lifecycle(monkeypatch, conn)
        _, resource_cls = _patch_repos(monkeypatch)

        await sctx.bootstrap_context(
            HOMOLOG_DSN, None, credential_out=str(tmp_path / "cred.json")
        )

        out = capsys.readouterr().out
        assert "WARNING" in out
        assert "placeholder" in out.lower()
        upsert_args = resource_cls.return_value.upsert.call_args[0]
        assert upsert_args[3] == sctx.PLACEHOLDER_RESOURCE_PARAMS


# ─── Returned dataclass / JSON schema shape ────────────────────────────────


class TestSyntheticContextShape:
    @pytest.mark.asyncio
    async def test_returned_context_matches_expected_shape(self, monkeypatch, tmp_path):
        tenant_id = uuid.uuid4()
        conn = FakeConn(fetchrow_results=[{"id": tenant_id}])
        _patch_pool_lifecycle(monkeypatch, conn)
        _patch_repos(monkeypatch)

        cred_out = tmp_path / "cred.json"
        context = await sctx.bootstrap_context(
            HOMOLOG_DSN,
            {"host": "test.invalid", "type": "vps"},
            credential_out=str(cred_out),
        )

        assert context.tenant_id == str(tenant_id)
        assert context.actor_id == sctx.SYNTHETIC_ACTOR_ID
        assert context.resource_key == sctx.SYNTHETIC_RESOURCE_KEY
        assert context.capability_id == sctx.SYNTHETIC_CAPABILITY_ID
        assert context.credential_file_path == str(cred_out)

        written = json.loads(cred_out.read_text(encoding="utf-8"))
        assert written == {
            "tenant_id": str(tenant_id),
            "actor_id": sctx.SYNTHETIC_ACTOR_ID,
            "credential": context.credential,
            "resource_key": sctx.SYNTHETIC_RESOURCE_KEY,
            "capability_id": sctx.SYNTHETIC_CAPABILITY_ID,
        }

    def test_identity_constants_exact(self):
        assert sctx.SYNTHETIC_TENANT_SLUG == "homolog-synthetic-e2e"
        assert sctx.SYNTHETIC_TENANT_NAME == "Homolog Synthetic E2E"
        assert sctx.SYNTHETIC_ACTOR_ID == "homolog-e2e-actor"
        assert sctx.SYNTHETIC_PROFILE == "owner-core"
        assert sctx.SYNTHETIC_RESOURCE_KEY == "homolog-synthetic-vps"
        assert sctx.SYNTHETIC_RESOURCE_TYPE == "vps"
        assert sctx.SYNTHETIC_CAPABILITY_ID == "infra.inspect"


# ─── show-context never returns/prints the credential ──────────────────────


class TestShowContext:
    @pytest.mark.asyncio
    async def test_show_context_found(self, monkeypatch):
        tenant_id = uuid.uuid4()
        conn = FakeConn(fetchrow_results=[{"id": tenant_id}])
        _patch_pool_lifecycle(monkeypatch, conn)

        result = await sctx.show_context(HOMOLOG_DSN)

        assert result == {
            "tenant_id": str(tenant_id),
            "actor_id": sctx.SYNTHETIC_ACTOR_ID,
            "resource_key": sctx.SYNTHETIC_RESOURCE_KEY,
            "capability_id": sctx.SYNTHETIC_CAPABILITY_ID,
        }
        assert "credential" not in result

    @pytest.mark.asyncio
    async def test_show_context_not_found(self, monkeypatch):
        conn = FakeConn(fetchrow_results=[None])
        _patch_pool_lifecycle(monkeypatch, conn)

        result = await sctx.show_context(HOMOLOG_DSN)

        assert result is None

    @pytest.mark.asyncio
    async def test_show_context_refuses_forbidden_ref(self, monkeypatch):
        create_pools_mock = AsyncMock()
        monkeypatch.setattr(sctx, "create_pools", create_pools_mock)
        monkeypatch.setattr(sctx, "close_pools", AsyncMock())

        with pytest.raises(sctx.TargetVerificationError):
            await sctx.show_context(FORBIDDEN_DSN)

        create_pools_mock.assert_not_called()
