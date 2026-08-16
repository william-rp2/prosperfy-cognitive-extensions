"""
tests/unit/test_audit_redaction.py — Testes de redação de campos sensíveis.

GATE: test_secrets_redacted_in_audit_payload
"""

from __future__ import annotations

from cognitive.audit.redaction import redact


def test_redact_api_key():
    data = {"resource": "prosperfy-main", "api_key": "super-secret-key"}
    result = redact(data)
    assert result["api_key"] == "***REDACTED***"
    assert result["resource"] == "prosperfy-main"


def test_redact_password():
    data = {"user": "william", "password": "hunter2"}
    result = redact(data)
    assert result["password"] == "***REDACTED***"
    assert result["user"] == "william"


def test_redact_token():
    data = {"action": "list", "token": "bearer-xyz"}
    result = redact(data)
    assert result["token"] == "***REDACTED***"


def test_redact_nested():
    data = {
        "config": {
            "host": "localhost",
            "credentials": {"secret": "my-secret", "user": "admin"},
        }
    }
    result = redact(data)
    assert result["config"]["credentials"]["secret"] == "***REDACTED***"
    assert result["config"]["credentials"]["user"] == "admin"
    assert result["config"]["host"] == "localhost"


def test_redact_extra_fields():
    data = {"ssn": "123-45-6789", "name": "William"}
    result = redact(data, extra_fields=["ssn"])
    assert result["ssn"] == "***REDACTED***"
    assert result["name"] == "William"


def test_redact_preserves_original():
    """Redact não deve modificar o dict original."""
    original = {"api_key": "secret", "resource": "prosperfy-main"}
    _ = redact(original)
    assert original["api_key"] == "secret"  # original intocado


def test_redact_empty():
    assert redact({}) == {}


def test_redact_list_in_value():
    data = {"items": [{"token": "abc"}, {"name": "test"}]}
    result = redact(data)
    assert result["items"][0]["token"] == "***REDACTED***"
    assert result["items"][1]["name"] == "test"
