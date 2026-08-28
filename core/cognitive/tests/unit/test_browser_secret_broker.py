"""
tests/unit/test_browser_secret_broker.py -- EnvironmentFileSecretBroker
(Track BH, doc 00 Sec.6.1).

Uses a FakeSkillsAdapter (no network) that records every invoke_tool call,
so these tests assert the SecretBroker never puts the raw value anywhere
except the single write call's `conteudo` -- and never returns it to the
caller.
"""

from __future__ import annotations

import pytest

from cognitive.secrets.broker import EnvironmentFileSecretBroker, SecretAliasError, SecretRef


class FakeSkillsAdapter:
    def __init__(self):
        self.calls: list[dict] = []
        self.exec_response: dict = {"stdout": "SECRET_MISSING", "exit_status": 0}

    async def invoke_tool(self, tool_name, arguments, tenant_id, correlation_id):
        self.calls.append({"tool_name": tool_name, "arguments": arguments, "tenant_id": tenant_id})
        if tool_name == "prosperfy_vps_executar":
            return dict(self.exec_response)
        return {"success": True}

    async def health(self):
        return True


@pytest.mark.asyncio
async def test_generate_returns_only_metadata():
    fake = FakeSkillsAdapter()
    broker = EnvironmentFileSecretBroker(fake, host="Hostinger One")

    ref = await broker.generate("signup-token-01", tenant_id="tenant-a", correlation_id="c-1")

    assert isinstance(ref, SecretRef)
    assert ref.alias == "signup-token-01"
    assert ref.path == "~/.hermes/secrets/browser/signup-token-01.env"
    # SecretRef never carries a 'value' field at all -- structural guarantee.
    assert not hasattr(ref, "value")


@pytest.mark.asyncio
async def test_generate_writes_env_file_and_chmods_600():
    fake = FakeSkillsAdapter()
    broker = EnvironmentFileSecretBroker(fake, host="Hostinger One")

    await broker.generate("tok-a", tenant_id="tenant-a", correlation_id="c-1")

    write_calls = [c for c in fake.calls if c["tool_name"] == "prosperfy_vps_escrever_arquivo"]
    chmod_calls = [c for c in fake.calls if c["tool_name"] == "prosperfy_vps_executar"]
    assert len(write_calls) == 1
    assert write_calls[0]["arguments"]["caminho"] == "~/.hermes/secrets/browser/tok-a.env"
    assert write_calls[0]["arguments"]["conteudo"].startswith("SECRET_VALUE=")
    assert write_calls[0]["arguments"]["confirmar"] is True
    assert len(chmod_calls) == 1
    assert "chmod 600" in chmod_calls[0]["arguments"]["comando"]


@pytest.mark.asyncio
async def test_generate_never_returns_the_written_value():
    fake = FakeSkillsAdapter()
    broker = EnvironmentFileSecretBroker(fake, host="Hostinger One")

    ref = await broker.generate("tok-b", tenant_id="tenant-a", correlation_id="c-1")

    written_content = fake.calls[0]["arguments"]["conteudo"]
    written_value = written_content.strip().split("=", 1)[1]
    assert len(written_value) > 20  # CSPRNG token_urlsafe(24) is a real value
    # The only place the raw value appears across the whole call is the
    # single write payload -- nothing on the returned SecretRef matches it.
    assert written_value not in repr(ref)


@pytest.mark.asyncio
async def test_reference_missing_alias_returns_none():
    fake = FakeSkillsAdapter()
    fake.exec_response = {"stdout": "SECRET_MISSING"}
    broker = EnvironmentFileSecretBroker(fake, host="Hostinger One")

    ref = await broker.reference("does-not-exist", tenant_id="tenant-a", correlation_id="c-1")
    assert ref is None


@pytest.mark.asyncio
async def test_reference_existing_alias_returns_metadata():
    fake = FakeSkillsAdapter()
    fake.exec_response = {"stdout": "SECRET_EXISTS"}
    broker = EnvironmentFileSecretBroker(fake, host="Hostinger One")

    ref = await broker.reference("tok-a", tenant_id="tenant-a", correlation_id="c-1")
    assert ref is not None
    assert ref.alias == "tok-a"


@pytest.mark.asyncio
async def test_invalid_alias_rejected_before_any_call():
    fake = FakeSkillsAdapter()
    broker = EnvironmentFileSecretBroker(fake, host="Hostinger One")

    with pytest.raises(SecretAliasError):
        await broker.generate("../etc/passwd", tenant_id="tenant-a", correlation_id="c-1")
    assert fake.calls == []  # rejected before any transport call


@pytest.mark.asyncio
async def test_transport_failure_never_leaks_value_in_message():
    class FailingAdapter(FakeSkillsAdapter):
        async def invoke_tool(self, tool_name, arguments, tenant_id, correlation_id):
            await super().invoke_tool(tool_name, arguments, tenant_id, correlation_id)
            raise RuntimeError("transport exploded")

    fake = FailingAdapter()
    broker = EnvironmentFileSecretBroker(fake, host="Hostinger One")

    with pytest.raises(RuntimeError) as exc_info:
        await broker.generate("tok-c", tenant_id="tenant-a", correlation_id="c-1")
    assert "tok-c" in str(exc_info.value)  # alias is fine to show
    written_value = fake.calls[0]["arguments"]["conteudo"].strip().split("=", 1)[1]
    assert written_value not in str(exc_info.value)
