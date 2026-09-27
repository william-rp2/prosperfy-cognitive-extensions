"""Contract tests for the QA browser worker. No live browser and no secrets."""
import importlib.util
from pathlib import Path


def _load():
    path = Path(__file__).with_name("worker.py")
    spec = importlib.util.spec_from_file_location("qa_browser_worker", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_allowlist_and_methods():
    mod = _load()
    assert mod.host_allowed("https://example.com") is False
    assert mod.host_allowed("https://homologacao.prospersend.com.br/app") is True
    denied = mod.action_api_read({"url": "https://example.com", "method": "GET"})
    assert denied["error"] == "url_not_allowed"
    posted = mod.action_api_read(
        {"url": "https://api-homologacao.prospersend.com.br/v1", "method": "POST"}
    )
    assert posted["error"] == "method_not_allowed"


def test_redaction():
    mod = _load()
    sample = '{"access_token":"secret-value","ok":true}'
    red = mod.redact_diagnostic(sample)
    assert "secret-value" not in red
    jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    assert "eyJ" not in mod.redact_diagnostic("token " + jwt)


def test_guard_job_urls():
    mod = _load()
    blocked = mod._guard_job_urls({"url": "https://example.com"})
    assert blocked["error"] == "url_not_allowed"
    assert mod._guard_job_urls({"url": ""}) is None


if __name__ == "__main__":
    test_allowlist_and_methods()
    test_redaction()
    test_guard_job_urls()
    print("QA_CONTRACT_UNIT=PASS")
