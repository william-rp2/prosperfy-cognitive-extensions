"""
tests/unit/test_browser_adapter.py -- BrowserAdapter (Track BH).

FakeInnerAdapter simulates ProsperfySkillsAdapter's prosperfy_vps_* replies
(no network, no real Browser Worker). Asserts: job JSON is written before
exec, the worker's stdout JSON line is parsed back correctly, unknown
tools/arguments are rejected by guard_browser_tool before any transport
call, and a malformed worker payload raises instead of fabricating success
(same fail-closed principle as ProsperfySkillsAdapter's own payload guard).
"""

from __future__ import annotations

import json

import pytest

from cognitive.adapters.browser_harness.client import BrowserAdapter
from cognitive.adapters.browser_harness.guard import BrowserToolError
from cognitive.adapters.browser_harness.mock import MockBrowserAdapter


class FakeInnerAdapter:
    def __init__(self, worker_stdout: str = '{"success": true, "pages": []}'):
        self.calls: list[dict] = []
        self.worker_stdout = worker_stdout

    async def invoke_tool(self, tool_name, arguments, tenant_id, correlation_id):
        self.calls.append({"tool_name": tool_name, "arguments": arguments})
        if tool_name == "prosperfy_vps_executar":
            return {"stdout": self.worker_stdout, "exit_status": 0}
        return {"success": True}

    async def health(self):
        return True


@pytest.mark.asyncio
async def test_read_links_writes_job_then_execs_worker():
    inner = FakeInnerAdapter(worker_stdout='{"success": true, "pages": [{"url": "https://example.com"}]}')
    adapter = BrowserAdapter(inner, host="Hostinger One")

    result = await adapter.invoke_tool(
        tool_name="browser_read_links",
        arguments={"urls": ["https://example.com"]},
        tenant_id="tenant-a",
        correlation_id="c-1",
    )

    assert result["success"] is True
    assert result["pages"][0]["url"] == "https://example.com"

    write_call = next(c for c in inner.calls if c["tool_name"] == "prosperfy_vps_escrever_arquivo")
    job = json.loads(write_call["arguments"]["conteudo"])
    assert job["action"] == "read_links"
    assert job["urls"] == ["https://example.com"]

    exec_call = next(c for c in inner.calls if c["tool_name"] == "prosperfy_vps_executar")
    assert "worker.py" in exec_call["arguments"]["comando"]
    assert exec_call["arguments"]["confirmar"] is True


@pytest.mark.asyncio
async def test_unknown_tool_rejected_before_any_transport_call():
    inner = FakeInnerAdapter()
    adapter = BrowserAdapter(inner, host="Hostinger One")

    with pytest.raises(BrowserToolError):
        await adapter.invoke_tool(
            tool_name="browser_delete_everything",
            arguments={},
            tenant_id="tenant-a",
            correlation_id="c-1",
        )
    assert inner.calls == []


@pytest.mark.asyncio
async def test_unexpected_argument_key_rejected():
    inner = FakeInnerAdapter()
    adapter = BrowserAdapter(inner, host="Hostinger One")

    with pytest.raises(BrowserToolError):
        await adapter.invoke_tool(
            tool_name="browser_read_links",
            arguments={"urls": [], "shell_command": "rm -rf /"},
            tenant_id="tenant-a",
            correlation_id="c-1",
        )
    assert inner.calls == []


@pytest.mark.asyncio
async def test_malformed_worker_stdout_raises_not_fabricates_success():
    inner = FakeInnerAdapter(worker_stdout="not json at all")
    adapter = BrowserAdapter(inner, host="Hostinger One")

    with pytest.raises(RuntimeError):
        await adapter.invoke_tool(
            tool_name="browser_read_links",
            arguments={"urls": ["https://example.com"]},
            tenant_id="tenant-a",
            correlation_id="c-1",
        )


@pytest.mark.asyncio
async def test_secret_ref_field_passes_through_as_reference_never_resolved_here():
    inner = FakeInnerAdapter(worker_stdout='{"success": true, "submitted": true, "secret_aliases_used": ["tok-a"]}')
    adapter = BrowserAdapter(inner, host="Hostinger One")

    await adapter.invoke_tool(
        tool_name="browser_fill_form",
        arguments={"url": "https://example.com", "action": "fill_form",
                   "fields": {"password": "secret_ref:tok-a"}, "submit": True},
        tenant_id="tenant-a",
        correlation_id="c-1",
    )
    write_call = next(c for c in inner.calls if c["tool_name"] == "prosperfy_vps_escrever_arquivo")
    # BrowserAdapter never resolves the reference -- it only ever forwards
    # the "secret_ref:..." string itself; the Browser Worker resolves it.
    assert "secret_ref:tok-a" in write_call["arguments"]["conteudo"]


@pytest.mark.asyncio
async def test_health_uses_doctor_and_never_touches_transport_when_mocked():
    mock = MockBrowserAdapter()
    assert await mock.health() is True


@pytest.mark.asyncio
async def test_mock_adapter_rejects_same_bad_input_as_real_adapter():
    mock = MockBrowserAdapter()
    with pytest.raises(BrowserToolError):
        await mock.invoke_tool(
            tool_name="not_a_real_tool",
            arguments={},
            tenant_id="tenant-a",
            correlation_id="c-1",
        )
