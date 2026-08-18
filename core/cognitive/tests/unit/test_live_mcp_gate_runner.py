"""
Unit tests for scripts/sprint_0_3_live_mcp_gate.py (Sprint 0.3 Live MCP E2E
Gate Runner).

No network, no DB. `httpx.AsyncClient` is mocked wherever an HTTP call would
otherwise happen. Covers:
  - credential-file parsing (valid / malformed JSON / missing keys / empty values)
  - --environment homolog fail-closed gate (+ COGNITIVE_LIVE_MCP=1 gate)
  - request-building (headers/body shape matches the documented contract)
  - idempotency-key generation/comparison logic in isolation
"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = REPO_ROOT / "scripts" / "sprint_0_3_live_mcp_gate.py"


def _load_gate_module():
    spec = importlib.util.spec_from_file_location("sprint_0_3_live_mcp_gate", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    # Dataclass decoration needs the module registered in sys.modules first
    # (dataclasses._is_type looks it up via cls.__module__) — without this,
    # module load raises AttributeError: 'NoneType' object has no '__dict__'.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _load_gate_module()


VALID_CREDENTIAL = {
    "tenant_id": "11111111-1111-1111-1111-111111111111",
    "actor_id": "homolog-e2e-actor",
    "credential": "synthetic-raw-credential-value",
    "resource_key": "homolog-synthetic-vps",
    "capability_id": "infra.inspect",
}


def _write_credential_file(tmp_path: Path, payload) -> Path:
    p = tmp_path / "cred.json"
    if isinstance(payload, str):
        p.write_text(payload, encoding="utf-8")
    else:
        p.write_text(json.dumps(payload), encoding="utf-8")
    return p


class TestScriptExists:
    def test_script_file_exists(self):
        assert SCRIPT_PATH.exists()


class TestLoadCredentialFile:
    def test_valid_credential_file_parses(self, tmp_path):
        p = _write_credential_file(tmp_path, VALID_CREDENTIAL)
        cred = gate.load_credential_file(p)
        assert cred.tenant_id == VALID_CREDENTIAL["tenant_id"]
        assert cred.actor_id == VALID_CREDENTIAL["actor_id"]
        assert cred.credential == VALID_CREDENTIAL["credential"]
        assert cred.resource_key == VALID_CREDENTIAL["resource_key"]
        assert cred.capability_id == VALID_CREDENTIAL["capability_id"]

    def test_missing_file_raises_clear_error_not_raw_exception(self, tmp_path):
        missing = tmp_path / "does-not-exist.json"
        with pytest.raises(gate.CredentialFileError, match="not found"):
            gate.load_credential_file(missing)

    def test_malformed_json_raises_clear_error_not_json_decode_error(self, tmp_path):
        p = _write_credential_file(tmp_path, "{not valid json,,,")
        with pytest.raises(gate.CredentialFileError, match="not valid JSON"):
            gate.load_credential_file(p)

    def test_json_array_instead_of_object_raises_clear_error(self, tmp_path):
        p = _write_credential_file(tmp_path, "[1, 2, 3]")
        with pytest.raises(gate.CredentialFileError, match="JSON object"):
            gate.load_credential_file(p)

    def test_missing_required_key_raises_clear_error_not_keyerror(self, tmp_path):
        payload = dict(VALID_CREDENTIAL)
        del payload["credential"]
        p = _write_credential_file(tmp_path, payload)
        with pytest.raises(gate.CredentialFileError, match="credential"):
            gate.load_credential_file(p)

    def test_multiple_missing_keys_all_reported(self, tmp_path):
        payload = {"tenant_id": "x"}
        p = _write_credential_file(tmp_path, payload)
        with pytest.raises(gate.CredentialFileError) as exc_info:
            gate.load_credential_file(p)
        msg = str(exc_info.value)
        assert "actor_id" in msg
        assert "credential" in msg
        assert "resource_key" in msg
        assert "capability_id" in msg

    def test_empty_string_value_raises_clear_error(self, tmp_path):
        payload = dict(VALID_CREDENTIAL)
        payload["actor_id"] = "   "
        p = _write_credential_file(tmp_path, payload)
        with pytest.raises(gate.CredentialFileError, match="empty or non-string"):
            gate.load_credential_file(p)

    def test_non_string_value_raises_clear_error(self, tmp_path):
        payload = dict(VALID_CREDENTIAL)
        payload["tenant_id"] = 12345
        p = _write_credential_file(tmp_path, payload)
        with pytest.raises(gate.CredentialFileError, match="empty or non-string"):
            gate.load_credential_file(p)

    def test_directory_instead_of_file_raises_clear_error(self, tmp_path):
        d = tmp_path / "a_directory.json"
        d.mkdir()
        with pytest.raises(gate.CredentialFileError, match="not a file"):
            gate.load_credential_file(d)

    def test_never_raises_raw_json_decode_error_or_keyerror(self, tmp_path):
        # Malformed file must never let json.JSONDecodeError/KeyError escape.
        p = _write_credential_file(tmp_path, "{{{")
        try:
            gate.load_credential_file(p)
        except gate.CredentialFileError:
            pass
        except (json.JSONDecodeError, KeyError):
            pytest.fail("raw JSONDecodeError/KeyError leaked past load_credential_file")


class TestEnvironmentGate:
    def test_environment_homolog_passes(self):
        gate.check_environment_flag("homolog")  # must not raise

    def test_environment_missing_fails_closed(self):
        with pytest.raises(gate.EnvironmentGateError, match="homolog"):
            gate.check_environment_flag(None)

    def test_environment_wrong_value_fails_closed(self):
        with pytest.raises(gate.EnvironmentGateError):
            gate.check_environment_flag("production")

    def test_environment_case_sensitive(self):
        with pytest.raises(gate.EnvironmentGateError):
            gate.check_environment_flag("Homolog")

    def test_live_mcp_flag_required(self, monkeypatch):
        monkeypatch.delenv("COGNITIVE_LIVE_MCP", raising=False)
        with pytest.raises(gate.EnvironmentGateError, match="COGNITIVE_LIVE_MCP"):
            gate.check_live_mcp_flag()

    def test_live_mcp_flag_wrong_value_fails_closed(self, monkeypatch):
        monkeypatch.setenv("COGNITIVE_LIVE_MCP", "true")
        with pytest.raises(gate.EnvironmentGateError):
            gate.check_live_mcp_flag()

    def test_live_mcp_flag_exactly_1_passes(self, monkeypatch):
        monkeypatch.setenv("COGNITIVE_LIVE_MCP", "1")
        gate.check_live_mcp_flag()  # must not raise


class TestApiBaseUrlResolution:
    def test_cli_value_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("COGNITIVE_HOMOLOG_API_URL", "https://env-value.example.com")
        result = gate.resolve_api_base_url("https://cli-value.example.com")
        assert result == "https://cli-value.example.com"

    def test_falls_back_to_env_var(self, monkeypatch):
        monkeypatch.setenv("COGNITIVE_HOMOLOG_API_URL", "https://env-value.example.com")
        result = gate.resolve_api_base_url(None)
        assert result == "https://env-value.example.com"

    def test_none_when_neither_provided(self, monkeypatch):
        monkeypatch.delenv("COGNITIVE_HOMOLOG_API_URL", raising=False)
        assert gate.resolve_api_base_url(None) is None

    def test_blank_env_var_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv("COGNITIVE_HOMOLOG_API_URL", "   ")
        assert gate.resolve_api_base_url(None) is None


class TestLooksHomologShaped:
    def test_real_homolog_url_matches(self):
        assert gate.looks_homolog_shaped("https://api-cognitive-homolog.prosperfy.com.br")

    def test_production_shaped_url_does_not_match(self):
        assert not gate.looks_homolog_shaped("https://api-cognitive.prosperfy.com.br")

    def test_case_insensitive(self):
        assert gate.looks_homolog_shaped("https://API-COGNITIVE-HOMOLOG.prosperfy.com.br")


class TestRunPreconditions:
    def test_all_pass(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COGNITIVE_LIVE_MCP", "1")
        p = _write_credential_file(tmp_path, VALID_CREDENTIAL)
        report = gate.run_preconditions(
            "homolog", str(p), "https://api-cognitive-homolog.prosperfy.com.br",
        )
        assert report.ok is True
        assert report.errors == []
        assert report.credential is not None
        assert report.api_base_url == "https://api-cognitive-homolog.prosperfy.com.br"

    def test_missing_environment_fails(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COGNITIVE_LIVE_MCP", "1")
        p = _write_credential_file(tmp_path, VALID_CREDENTIAL)
        report = gate.run_preconditions(
            None, str(p), "https://api-cognitive-homolog.prosperfy.com.br",
        )
        assert report.ok is False
        assert report.checks["environment_declared_homolog"] is False

    def test_missing_live_mcp_fails(self, tmp_path, monkeypatch):
        monkeypatch.delenv("COGNITIVE_LIVE_MCP", raising=False)
        p = _write_credential_file(tmp_path, VALID_CREDENTIAL)
        report = gate.run_preconditions(
            "homolog", str(p), "https://api-cognitive-homolog.prosperfy.com.br",
        )
        assert report.ok is False
        assert report.checks["live_mcp_enabled"] is False

    def test_malformed_credential_file_fails_without_raising(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COGNITIVE_LIVE_MCP", "1")
        p = _write_credential_file(tmp_path, "not json")
        report = gate.run_preconditions(
            "homolog", str(p), "https://api-cognitive-homolog.prosperfy.com.br",
        )
        assert report.ok is False
        assert report.checks["credential_file_ok"] is False
        assert any("not valid JSON" in e for e in report.errors)

    def test_non_homolog_shaped_url_fails(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COGNITIVE_LIVE_MCP", "1")
        p = _write_credential_file(tmp_path, VALID_CREDENTIAL)
        report = gate.run_preconditions(
            "homolog", str(p), "https://api-cognitive-production.prosperfy.com.br",
        )
        assert report.ok is False
        assert report.checks["api_base_url_homolog_shaped"] is False

    def test_missing_api_base_url_fails(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COGNITIVE_LIVE_MCP", "1")
        monkeypatch.delenv("COGNITIVE_HOMOLOG_API_URL", raising=False)
        p = _write_credential_file(tmp_path, VALID_CREDENTIAL)
        report = gate.run_preconditions("homolog", str(p), None)
        assert report.ok is False
        assert report.checks["api_base_url_provided"] is False


class TestCommonGate:
    def _args(self, tmp_path, environment="homolog", api_base_url="https://api-cognitive-homolog.prosperfy.com.br"):
        p = _write_credential_file(tmp_path, VALID_CREDENTIAL)
        ns = type("Args", (), {})()
        ns.environment = environment
        ns.credential_file = str(p)
        ns.api_base_url = api_base_url
        return ns

    def test_returns_credential_and_url_when_gated_ok(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COGNITIVE_LIVE_MCP", "1")
        result = gate._common_gate(self._args(tmp_path))
        assert result is not None
        cred, api_base_url = result
        assert cred.tenant_id == VALID_CREDENTIAL["tenant_id"]
        assert api_base_url == "https://api-cognitive-homolog.prosperfy.com.br"

    def test_refuses_without_environment_flag(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("COGNITIVE_LIVE_MCP", "1")
        result = gate._common_gate(self._args(tmp_path, environment=None))
        assert result is None
        assert "GATE_REFUSED" in capsys.readouterr().out

    def test_refuses_with_wrong_environment_value(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("COGNITIVE_LIVE_MCP", "1")
        result = gate._common_gate(self._args(tmp_path, environment="production"))
        assert result is None
        assert "GATE_REFUSED" in capsys.readouterr().out

    def test_refuses_without_live_mcp_flag(self, tmp_path, monkeypatch, capsys):
        monkeypatch.delenv("COGNITIVE_LIVE_MCP", raising=False)
        result = gate._common_gate(self._args(tmp_path))
        assert result is None
        assert "GATE_REFUSED" in capsys.readouterr().out

    def test_refuses_with_malformed_credential_file(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("COGNITIVE_LIVE_MCP", "1")
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        ns = self._args(tmp_path)
        ns.credential_file = str(bad)
        result = gate._common_gate(ns)
        assert result is None
        assert "GATE_REFUSED" in capsys.readouterr().out

    def test_refuses_without_api_base_url(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("COGNITIVE_LIVE_MCP", "1")
        monkeypatch.delenv("COGNITIVE_HOMOLOG_API_URL", raising=False)
        result = gate._common_gate(self._args(tmp_path, api_base_url=None))
        assert result is None
        assert "GATE_REFUSED" in capsys.readouterr().out

    def test_never_calls_http_when_gate_refuses(self, tmp_path, monkeypatch):
        """No HTTP call must be attempted when the gate refuses."""
        monkeypatch.delenv("COGNITIVE_LIVE_MCP", raising=False)
        with patch("httpx.AsyncClient") as mock_client_cls:
            result = gate._common_gate(self._args(tmp_path))
            assert result is None
            mock_client_cls.assert_not_called()


class TestRequestBuilding:
    def test_build_execute_url_matches_documented_contract(self):
        url = gate.build_execute_url("https://api-cognitive-homolog.prosperfy.com.br", "infra.inspect")
        assert url == "https://api-cognitive-homolog.prosperfy.com.br/v1/capabilities/infra.inspect/execute"

    def test_build_execute_url_strips_trailing_slash(self):
        url = gate.build_execute_url("https://api-cognitive-homolog.prosperfy.com.br/", "infra.inspect")
        assert url == "https://api-cognitive-homolog.prosperfy.com.br/v1/capabilities/infra.inspect/execute"

    def test_build_headers_matches_documented_contract(self):
        cred = gate.CredentialFile(
            tenant_id="tenant-x", actor_id="actor-x", credential="secret-x",
            resource_key="res-x", capability_id="infra.inspect", path=Path("x"),
        )
        headers = gate.build_headers(cred)
        assert headers["Authorization"] == "Bearer secret-x"
        assert headers["X-Tenant-Id"] == "tenant-x"
        assert headers["X-Actor-Id"] == "actor-x"
        assert "X-Correlation-Id" not in headers

    def test_build_headers_includes_correlation_id_when_given(self):
        cred = gate.CredentialFile(
            tenant_id="tenant-x", actor_id="actor-x", credential="secret-x",
            resource_key="res-x", capability_id="infra.inspect", path=Path("x"),
        )
        headers = gate.build_headers(cred, correlation_id="corr-123")
        assert headers["X-Correlation-Id"] == "corr-123"

    def test_build_positive_body_shape(self):
        body = gate.build_positive_body("prosperfy-main", "idem-key-1")
        assert body == {"params": {"resource": "prosperfy-main"}, "idempotency_key": "idem-key-1"}

    def test_build_positive_body_without_idempotency_key(self):
        body = gate.build_positive_body("prosperfy-main", None)
        assert body == {"params": {"resource": "prosperfy-main"}}
        assert "idempotency_key" not in body

    def test_build_negative_body_injects_forbidden_key(self):
        body = gate.build_negative_body("prosperfy-main", "command")
        assert body["params"]["resource"] == "prosperfy-main"
        assert body["params"]["command"] == "whatever"

    @pytest.mark.parametrize("forbidden_key", sorted(gate.FORBIDDEN_ARG_KEYS))
    def test_build_negative_body_covers_every_forbidden_key(self, forbidden_key):
        body = gate.build_negative_body("prosperfy-main", forbidden_key)
        assert forbidden_key in body["params"]

    def test_forbidden_arg_keys_matches_guard_module_exactly(self):
        from cognitive.adapters.prosperfy_skills.guard import FORBIDDEN_ARG_KEYS as REAL_KEYS
        assert gate.FORBIDDEN_ARG_KEYS == REAL_KEYS
        assert len(gate.FORBIDDEN_ARG_KEYS) == 11


class TestIdempotencyKeyGeneration:
    def test_generates_unique_keys(self):
        keys = {gate.generate_idempotency_key() for _ in range(100)}
        assert len(keys) == 100

    def test_key_is_string_and_parseable_suffix(self):
        key = gate.generate_idempotency_key()
        assert isinstance(key, str)
        assert key.startswith("e2e-gate-")
        suffix = key.removeprefix("e2e-gate-")
        uuid.UUID(suffix)  # must not raise

    def test_same_key_reused_across_calls_is_equal(self):
        key = gate.generate_idempotency_key()
        body1 = gate.build_positive_body("res", key)
        body2 = gate.build_positive_body("res", key)
        assert body1["idempotency_key"] == body2["idempotency_key"]


class TestSanitize:
    def test_strips_raw_credential_from_error_text(self):
        cred = gate.CredentialFile(
            tenant_id="t", actor_id="a", credential="super-secret-value",
            resource_key="r", capability_id="infra.inspect", path=Path("x"),
        )
        text = "connection failed: Authorization: Bearer super-secret-value"
        sanitized = gate._sanitize(text, cred)
        assert "super-secret-value" not in sanitized

    def test_noop_without_credential(self):
        text = "some error text"
        assert gate._sanitize(text, None) == text


class TestGatewayStatusReuse:
    def test_uses_real_gateway_status_enum_not_hardcoded_strings(self):
        from cognitive.contracts.gateway import GatewayStatus as RealGatewayStatus
        assert gate.GatewayStatus is RealGatewayStatus
        assert gate.GatewayStatus.COMPLETED.value == "completed"
        assert gate.GatewayStatus.FAILED.value == "failed"
        assert gate.GatewayStatus.PENDING_CONFIRMATION.value == "pending_confirmation"


class TestCallExecuteMocked:
    """Confirms call_execute() hits the documented URL/method with httpx.AsyncClient
    fully mocked — no real network I/O happens in this test."""

    @pytest.mark.asyncio
    async def test_call_execute_posts_to_documented_url(self):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: {
            "execution_id": "exec-1",
            "correlation_id": "corr-1",
            "status": "completed",
            "data": {},
            "audit_id": "audit-1",
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            response = await gate.call_execute(
                "https://api-cognitive-homolog.prosperfy.com.br",
                "infra.inspect",
                {"Authorization": "Bearer x"},
                {"params": {"resource": "y"}},
            )

        mock_client.post.assert_called_once()
        called_url = mock_client.post.call_args.args[0]
        assert called_url == "https://api-cognitive-homolog.prosperfy.com.br/v1/capabilities/infra.inspect/execute"
        assert response.json()["status"] == "completed"
