"""
tests/unit/test_manage_service_identity_cli.py

Sprint 0.4: unit tests for core/cognitive/scripts/manage_service_identity.py,
the operator CLI wrapping ServiceIdentityRepository.register()/deactivate()/
rotate(). No DB, no Docker, no Testcontainers — ServiceIdentityRepository is
mocked entirely via a FakeRepo; these must run in plain `pytest` locally.

Covers:
  - argument parsing (required flags per mode)
  - one-time-credential-display discipline (printed once on stdout, never
    logged)
  - the --rotate AttributeError guard (repo without rotate() yet, matching
    today's identity_repo.py before dev/sprint-0.4-db-identity merges)
  - generated credential entropy/length
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = REPO_ROOT / "core" / "cognitive" / "scripts" / "manage_service_identity.py"

_spec = importlib.util.spec_from_file_location("manage_service_identity_cli", SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


# ─── Fakes ──────────────────────────────────────────────────────────────


@dataclass
class FakeRow:
    id: str = "id-1"
    tenant_id: str = "11111111-1111-1111-1111-111111111111"
    actor_id: str = "actor-1"
    profile: str = "owner-core"
    active: bool = True


class FakeRepoNoRotate:
    """Mirrors today's ServiceIdentityRepository: no rotate() attribute."""

    def __init__(self, register_row: FakeRow | None = None, register_error: Exception | None = None,
                 deactivate_error: Exception | None = None):
        self._register_row = register_row or FakeRow()
        self._register_error = register_error
        self._deactivate_error = deactivate_error
        self.register_calls: list[dict] = []
        self.deactivate_calls: list[str] = []

    async def register(self, tenant_id, actor_id, credential, profile="owner-core"):
        self.register_calls.append(
            {"tenant_id": tenant_id, "actor_id": actor_id, "credential": credential, "profile": profile}
        )
        if self._register_error:
            raise self._register_error
        return self._register_row

    async def deactivate(self, credential):
        self.deactivate_calls.append(credential)
        if self._deactivate_error:
            raise self._deactivate_error


class FakeRepoWithRotate(FakeRepoNoRotate):
    def __init__(self, *args, rotate_row: FakeRow | None = None, rotate_error: Exception | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._rotate_row = rotate_row or FakeRow(id="id-2")
        self._rotate_error = rotate_error
        self.rotate_calls: list[tuple] = []

    async def rotate(self, old_credential, new_credential):
        self.rotate_calls.append((old_credential, new_credential))
        if self._rotate_error:
            raise self._rotate_error
        return self._rotate_row


def _args(**overrides) -> argparse.Namespace:
    base = dict(
        register=False, rotate=False, deactivate=False,
        tenant_id=None, actor_id=None, profile="owner-core",
        old_credential=None, credential=None,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


# ─── Argument parsing ───────────────────────────────────────────────────


class TestArgumentParsing:
    def test_register_requires_tenant_and_actor(self):
        parser = cli.build_parser()
        args = parser.parse_args(["--register"])
        with pytest.raises(SystemExit):
            cli.validate_args(parser, args)

    def test_register_requires_actor_even_with_tenant(self):
        parser = cli.build_parser()
        args = parser.parse_args(["--register", "--tenant-id", "t1"])
        with pytest.raises(SystemExit):
            cli.validate_args(parser, args)

    def test_register_with_all_required_flags_passes_validation(self):
        parser = cli.build_parser()
        args = parser.parse_args(
            ["--register", "--tenant-id", "t1", "--actor-id", "a1"]
        )
        cli.validate_args(parser, args)  # should not raise
        assert args.profile == "owner-core"

    def test_register_custom_profile(self):
        parser = cli.build_parser()
        args = parser.parse_args(
            ["--register", "--tenant-id", "t1", "--actor-id", "a1", "--profile", "worker"]
        )
        assert args.profile == "worker"

    def test_rotate_requires_old_credential(self):
        parser = cli.build_parser()
        args = parser.parse_args(["--rotate"])
        with pytest.raises(SystemExit):
            cli.validate_args(parser, args)

    def test_rotate_with_old_credential_passes_validation(self):
        parser = cli.build_parser()
        args = parser.parse_args(["--rotate", "--old-credential", "tok123"])
        cli.validate_args(parser, args)  # should not raise

    def test_deactivate_requires_credential(self):
        parser = cli.build_parser()
        args = parser.parse_args(["--deactivate"])
        with pytest.raises(SystemExit):
            cli.validate_args(parser, args)

    def test_deactivate_with_credential_passes_validation(self):
        parser = cli.build_parser()
        args = parser.parse_args(["--deactivate", "--credential", "tok123"])
        cli.validate_args(parser, args)  # should not raise

    def test_modes_are_mutually_exclusive(self):
        parser = cli.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--register", "--rotate"])

    def test_no_mode_flag_is_required(self):
        parser = cli.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])


# ─── Credential generation ──────────────────────────────────────────────


class TestCredentialGeneration:
    def test_uses_secrets_module_not_random(self):
        import inspect
        source = inspect.getsource(cli.generate_credential)
        assert "secrets.token_urlsafe" in source
        assert "random." not in source

    def test_sufficient_length_and_charset(self):
        cred = cli.generate_credential()
        # 32 bytes urlsafe-base64 -> ~43 chars, well above any reasonable
        # brute-force floor.
        assert len(cred) >= 40
        assert re.fullmatch(r"[A-Za-z0-9_\-]+", cred)

    def test_credentials_are_unique(self):
        creds = {cli.generate_credential() for _ in range(50)}
        assert len(creds) == 50


# ─── --register ─────────────────────────────────────────────────────────


class TestCmdRegister:
    @pytest.mark.asyncio
    async def test_success_prints_credential_exactly_once(self, capsys):
        repo = FakeRepoNoRotate()
        args = _args(register=True, tenant_id="t1", actor_id="a1", profile="owner-core")

        rc = await cli.cmd_register(args, repo)

        assert rc == 0
        out = capsys.readouterr().out
        credential = repo.register_calls[0]["credential"]
        assert out.count(credential) == 1
        assert "SHOWN EXACTLY ONCE" in out

    @pytest.mark.asyncio
    async def test_passes_generated_credential_to_repo(self):
        repo = FakeRepoNoRotate()
        args = _args(register=True, tenant_id="t1", actor_id="a1")

        await cli.cmd_register(args, repo)

        call = repo.register_calls[0]
        assert call["tenant_id"] == "t1"
        assert call["actor_id"] == "a1"
        assert call["profile"] == "owner-core"
        assert len(call["credential"]) >= 40

    @pytest.mark.asyncio
    async def test_never_logs_raw_credential(self, caplog):
        caplog.set_level(logging.DEBUG)
        repo = FakeRepoNoRotate()
        args = _args(register=True, tenant_id="t1", actor_id="a1")

        await cli.cmd_register(args, repo)

        credential = repo.register_calls[0]["credential"]
        for record in caplog.records:
            assert credential not in record.getMessage()

    @pytest.mark.asyncio
    async def test_logs_only_non_secret_fields(self, caplog):
        caplog.set_level(logging.INFO)
        repo = FakeRepoNoRotate(register_row=FakeRow(id="id-9", tenant_id="tenant-9", actor_id="actor-9"))
        args = _args(register=True, tenant_id="tenant-9", actor_id="actor-9")

        await cli.cmd_register(args, repo)

        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "id-9" in joined
        assert "tenant-9" in joined
        assert "actor-9" in joined

    @pytest.mark.asyncio
    async def test_repo_valueerror_returns_1_no_traceback(self, capsys):
        repo = FakeRepoNoRotate(register_error=ValueError("tenant not found"))
        args = _args(register=True, tenant_id="bad", actor_id="a1")

        rc = await cli.cmd_register(args, repo)

        assert rc == 1
        err = capsys.readouterr().err
        assert "tenant not found" in err
        assert "Traceback" not in err


# ─── --rotate ───────────────────────────────────────────────────────────


class TestCmdRotate:
    @pytest.mark.asyncio
    async def test_missing_rotate_method_guarded_with_helpful_message(self, capsys):
        """Today's ServiceIdentityRepository (identity_repo.py, unmodified by
        this branch) has no rotate() — this must be a clear stderr message
        and exit 1, never a raw AttributeError traceback."""
        repo = FakeRepoNoRotate()
        args = _args(rotate=True, old_credential="old-tok")

        rc = await cli.cmd_rotate(args, repo)

        assert rc == 1
        err = capsys.readouterr().err
        assert "rotate" in err.lower()
        assert "dev/sprint-0.4-db-identity" in err
        assert "Traceback" not in err

    @pytest.mark.asyncio
    async def test_guard_fires_against_the_real_repository_class(self, capsys):
        """Sanity check against the actual (unmodified) repository class,
        not just our fake — confirms the guard reflects real current state."""
        from cognitive.db.repositories.identity_repo import ServiceIdentityRepository

        repo = ServiceIdentityRepository()
        args = _args(rotate=True, old_credential="old-tok")

        rc = await cli.cmd_rotate(args, repo)

        assert rc == 1
        assert "rotate" in capsys.readouterr().err.lower()

    @pytest.mark.asyncio
    async def test_success_prints_new_credential_exactly_once(self, capsys):
        repo = FakeRepoWithRotate()
        args = _args(rotate=True, old_credential="old-tok")

        rc = await cli.cmd_rotate(args, repo)

        assert rc == 0
        out = capsys.readouterr().out
        new_credential = repo.rotate_calls[0][1]
        assert out.count(new_credential) == 1
        assert "old-tok" not in out  # old credential is never echoed either

    @pytest.mark.asyncio
    async def test_never_logs_old_or_new_credential(self, caplog):
        caplog.set_level(logging.DEBUG)
        repo = FakeRepoWithRotate()
        args = _args(rotate=True, old_credential="super-secret-old-tok")

        await cli.cmd_rotate(args, repo)

        new_credential = repo.rotate_calls[0][1]
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "super-secret-old-tok" not in joined
        assert new_credential not in joined

    @pytest.mark.asyncio
    async def test_repo_valueerror_returns_1(self, capsys):
        repo = FakeRepoWithRotate(rotate_error=ValueError("old credential not found or inactive"))
        args = _args(rotate=True, old_credential="stale-tok")

        rc = await cli.cmd_rotate(args, repo)

        assert rc == 1
        err = capsys.readouterr().err
        assert "old credential not found or inactive" in err
        assert "Traceback" not in err


# ─── --deactivate ───────────────────────────────────────────────────────


class TestCmdDeactivate:
    @pytest.mark.asyncio
    async def test_success_never_echoes_raw_token(self, capsys):
        repo = FakeRepoNoRotate()
        args = _args(deactivate=True, credential="raw-secret-token-value")

        rc = await cli.cmd_deactivate(args, repo)

        assert rc == 0
        out = capsys.readouterr().out
        assert "raw-secret-token-value" not in out
        assert repo.deactivate_calls == ["raw-secret-token-value"]

    @pytest.mark.asyncio
    async def test_shows_only_truncated_hash_prefix(self, capsys):
        from cognitive.db.repositories.identity_repo import hash_credential

        repo = FakeRepoNoRotate()
        token = "raw-secret-token-value"
        args = _args(deactivate=True, credential=token)

        await cli.cmd_deactivate(args, repo)

        out = capsys.readouterr().out
        expected_prefix = hash_credential(token)[:12]
        assert expected_prefix in out

    @pytest.mark.asyncio
    async def test_never_logs_raw_credential(self, caplog):
        caplog.set_level(logging.DEBUG)
        repo = FakeRepoNoRotate()
        args = _args(deactivate=True, credential="another-raw-secret")

        await cli.cmd_deactivate(args, repo)

        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "another-raw-secret" not in joined

    @pytest.mark.asyncio
    async def test_repo_valueerror_returns_1(self, capsys):
        repo = FakeRepoNoRotate(deactivate_error=ValueError("credential not found"))
        args = _args(deactivate=True, credential="tok")

        rc = await cli.cmd_deactivate(args, repo)

        assert rc == 1
        err = capsys.readouterr().err
        assert "credential not found" in err
        assert "Traceback" not in err
