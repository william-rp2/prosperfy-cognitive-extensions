"""
tests/unit/test_credential_redaction.py — FIX Sprint 0.3 RETURN_TO_DEV (Item B).

Cobre o vazamento de segredo em exceções do transporte MCP + validação CRLF:

  Origem real do incidente: um secret com `\r` fazia o transporte rejeitar o
  header (Illegal header value) e a MENSAGEM da exceção expunha prefixos do
  Bearer real (ex.: `Illegal header value b'Bearer 55a0ccf2...\r'`).

Camadas do fix verificadas aqui:
  1. sanitize_secrets/sanitize_exception — scrub genérico de Bearer /
     Authorization / DSN em qualquer string (defense-in-depth).
  2. validate_credential_no_control — rejeição fail-closed de CR/LF/controle
     com mensagem estática (nunca ecoa o valor, nem parcial).
  3. ProsperfySkillsAdapter — valida na construção e re-valida em _build_client
     (fastmcp nunca é chamado com header quebrado).
  4. Caminho de transporte — exceção com canário embutido nunca aparece em
     exception/log/response/audit.
  5. Orquestrador — erro do adapter sanitizado em response/audit/telemetry.

Contrato adversarial: credencial canária fictícia — nem canário COMPLETO nem
PARCIAL (prefixo) pode aparecer em exception string, logs, response, audit ou
telemetry.
"""

from __future__ import annotations

import logging

import fastmcp
import pytest

from cognitive.adapters.prosperfy_skills.client import ProsperfySkillsAdapter
from cognitive.audit.redaction import redact
from cognitive.audit.writer import InMemoryAuditWriter
from cognitive.contracts.tenancy import ActorContext, CapabilityGrant
from cognitive.execution.orchestrator import ExecutionOrchestrator
from cognitive.execution.resource_resolver import InMemoryResourceResolver
from cognitive.gate.redaction import (
    redact_dsn,
    sanitize_exception,
    sanitize_secrets,
    validate_credential_no_control,
)
from cognitive.policy.engine import PolicyEngine
from cognitive.registry.registry import InMemoryCapabilityRegistry
from cognitive.telemetry.recorder import InMemoryTelemetryRecorder

CANARY = "55a0ccf2" + "f" * 40
CANARY_PREFIX = CANARY[:8]

HEADER_ERR_FULL = f"Illegal header value b'Bearer {CANARY}\\r'"
HEADER_ERR_PREFIX = f"Illegal header value b'Bearer {CANARY_PREFIX}...\\r'"


# ─── sanitize_secrets / sanitize_exception ────────────────────────────────

class TestSanitizeSecrets:
    def test_full_canary_in_header_error_removed(self):
        out = sanitize_secrets(HEADER_ERR_FULL)
        assert CANARY not in out
        assert CANARY_PREFIX not in out

    def test_partial_prefix_leak_removed(self):
        out = sanitize_secrets(HEADER_ERR_PREFIX)
        assert CANARY_PREFIX not in out

    def test_authorization_header_value_removed(self):
        out = sanitize_secrets("Authorization: Bearer " + CANARY)
        assert CANARY not in out
        assert "***" in out

    def test_bearer_literal_value_removed(self):
        out = sanitize_secrets(f"auth bearer {CANARY} rest")
        assert CANARY not in out

    def test_dsn_still_redacted(self):
        out = sanitize_secrets("connect to postgresql://user:s3cret@db.example/postgres failed")
        assert "s3cret" not in out
        assert "postgresql://***:***@***" in out

    def test_empty_and_none_handled(self):
        assert sanitize_secrets("") == ""
        assert sanitize_secrets("plain text") == "plain text"

    def test_redact_dsn_unaffected(self):
        assert "s3cret" not in redact_dsn("postgresql://user:s3cret@h/pg")


class TestSanitizeException:
    def test_runtime_error_message_scrubbed(self):
        exc = RuntimeError(HEADER_ERR_FULL)
        out = sanitize_exception(exc)
        assert CANARY not in out
        assert CANARY_PREFIX not in out

    def test_nested_wrapping_still_scrubbed(self):
        inner = RuntimeError(HEADER_ERR_FULL)
        outer = RuntimeError(f"wrapped: {inner}")
        out = sanitize_exception(outer)
        assert CANARY not in out
        assert CANARY_PREFIX not in out


# ─── validate_credential_no_control (CRLF/controle) ──────────────────────

class TestValidateCredentialNoControl:
    def test_rejects_cr(self):
        with pytest.raises(RuntimeError) as exc_info:
            validate_credential_no_control(f"{CANARY}\r", "MCP_PROSPERFYSKILLS_API_KEY")
        message = str(exc_info.value)
        assert "MCP_PROSPERFYSKILLS_API_KEY" in message
        assert CANARY not in message
        assert CANARY_PREFIX not in message

    def test_rejects_lf(self):
        with pytest.raises(RuntimeError):
            validate_credential_no_control(f"{CANARY}\n")

    def test_rejects_control_char(self):
        with pytest.raises(RuntimeError):
            validate_credential_no_control(f"{CANARY}\x07")

    def test_rejects_del_char(self):
        with pytest.raises(RuntimeError):
            validate_credential_no_control(f"{CANARY}\x7f")

    def test_accepts_clean_hex_key(self):
        assert validate_credential_no_control(CANARY) == CANARY

    def test_accepts_empty(self):
        assert validate_credential_no_control("") == ""

    def test_never_echoes_value_on_reject(self):
        with pytest.raises(RuntimeError) as exc_info:
            validate_credential_no_control(f"{CANARY}\r")
        assert CANARY not in str(exc_info.value)
        assert CANARY_PREFIX not in str(exc_info.value)


# ─── ProsperfySkillsAdapter — CRLF rejection at boundary ──────────────────

class TestAdapterCrlfRejection:
    def test_init_rejects_crlf_secret_static_message(self):
        with pytest.raises(RuntimeError) as exc_info:
            ProsperfySkillsAdapter(api_key=f"{CANARY}\r", host="skills.invalid.test")
        message = str(exc_info.value)
        assert "MCP_PROSPERFYSKILLS_API_KEY" in message
        assert CANARY not in message
        assert CANARY_PREFIX not in message

    def test_init_accepts_clean_key(self):
        adapter = ProsperfySkillsAdapter(api_key=CANARY, host="skills.invalid.test")
        assert adapter._api_key == CANARY

    def test_build_client_revalidates_before_fastmcp(self, monkeypatch):
        """Se a env mudar após init (sem restart), fastmcp NUNCA é chamado com
        um header quebrado — validação roda antes da construção do client."""
        adapter = ProsperfySkillsAdapter(api_key="clean-key", host="skills.invalid.test")
        adapter._api_key = f"{CANARY}\n"
        instantiated = []

        class _ExplodingClient:
            def __init__(self, *args, **kwargs):
                instantiated.append(True)

        monkeypatch.setattr(fastmcp, "Client", _ExplodingClient)
        with pytest.raises(RuntimeError) as exc_info:
            adapter._build_client()
        assert instantiated == []
        assert CANARY not in str(exc_info.value)
        assert CANARY_PREFIX not in str(exc_info.value)


# ─── Transport-error path: canário embutido nunca vaza ───────────────────

class _RaisingTransportClient:
    """fastmcp.Client fake: falha no __aenter__ com mensagem que embute o
    canário (mesmo formato do incidente real)."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        raise RuntimeError(HEADER_ERR_FULL)

    async def __exit__(self, *args):
        return False


class TestTransportErrorRedaction:
    @pytest.mark.asyncio
    async def test_invoke_tool_transport_error_never_leaks_canary(self, monkeypatch, caplog):
        adapter = ProsperfySkillsAdapter(api_key=CANARY, host="skills.invalid.test")
        monkeypatch.setattr(fastmcp, "Client", _RaisingTransportClient)
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(RuntimeError) as exc_info:
                await adapter.invoke_tool(
                    tool_name="prosperfy_vps_panorama",
                    arguments={"resource": "prosperfy-main"},
                    tenant_id="tenant-a",
                    correlation_id="corr-1",
                )
        assert "erro de transporte" in str(exc_info.value)
        assert CANARY not in str(exc_info.value)
        assert CANARY_PREFIX not in str(exc_info.value)
        for record in caplog.records:
            assert CANARY not in record.getMessage()
            assert CANARY_PREFIX not in record.getMessage()

    @pytest.mark.asyncio
    async def test_health_false_but_never_leaks_canary(self, monkeypatch, caplog):
        adapter = ProsperfySkillsAdapter(api_key=CANARY, host="skills.invalid.test")
        monkeypatch.setattr(fastmcp, "Client", _RaisingTransportClient)
        with caplog.at_level(logging.DEBUG):
            assert await adapter.health() is False
        for record in caplog.records:
            assert CANARY not in record.getMessage()
            assert CANARY_PREFIX not in record.getMessage()


# ─── Audit redaction string scrub (defense-in-depth) ─────────────────────

class TestAuditRedactionStringScrub:
    def test_error_string_with_embedded_canary_scrubbed(self):
        data = {"result_summary": {"error": HEADER_ERR_FULL}}
        out = redact(data)
        dumped = repr(out)
        assert CANARY not in dumped
        assert CANARY_PREFIX not in dumped

    def test_nested_string_scrubbed(self):
        data = {"deep": {"error": HEADER_ERR_PREFIX}}
        out = redact(data)
        assert CANARY_PREFIX not in repr(out)

    def test_non_secret_strings_untouched(self):
        data = {"message": "tudo ok com resource prosperfy-main"}
        assert redact(data)["message"] == "tudo ok com resource prosperfy-main"


# ─── Orquestrador: response + audit + telemetry nunca contêm canário ──────

class LeakyAdapter:
    """Adapter que 'vaza' o canário na exceção — simula um transporte
    recusando o header com a mensagem do incidente real."""

    async def invoke_tool(self, tool_name, arguments, tenant_id, correlation_id):
        raise RuntimeError(HEADER_ERR_FULL)

    async def health(self) -> bool:
        return True


def _ctx(tenant="tenant-x", profile="owner-core"):
    return ActorContext(
        tenant_id=tenant,
        actor_id="actor-x",
        correlation_id="corr-x",
        credential_ref="ref-x",
        profile=profile,
    )


def _build_raising_orchestrator(adapter):
    registry = InMemoryCapabilityRegistry()
    registry.load_from_yaml()
    registry.register_grant(CapabilityGrant(
        tenant_id="tenant-x",
        profile="owner-core",
        capability_id="infra.inspect",
    ))
    resource_resolver = InMemoryResourceResolver()
    resource_resolver.register("tenant-x", "prosperfy-main", {"host": "mock-vps.test", "type": "vps"})
    audit_writer = InMemoryAuditWriter()
    telemetry_recorder = InMemoryTelemetryRecorder()
    orchestrator = ExecutionOrchestrator(
        registry=registry,
        policy_engine=PolicyEngine(),
        skills_adapter=adapter,
        audit_writer=audit_writer,
        telemetry_recorder=telemetry_recorder,
        resource_resolver=resource_resolver,
    )
    return orchestrator, audit_writer, telemetry_recorder


class TestOrchestratorNeverLeaksCanary:
    @pytest.mark.asyncio
    async def test_response_audit_telemetry_clean(self, caplog):
        orchestrator, audit_writer, telemetry_recorder = _build_raising_orchestrator(LeakyAdapter())
        with caplog.at_level(logging.DEBUG):
            result = await orchestrator.execute(
                ctx=_ctx(),
                capability_id="infra.inspect",
                params={"resource": "prosperfy-main"},
            )

        # response
        assert result.status.value == "failed"
        assert CANARY not in (result.error or "")
        assert CANARY_PREFIX not in (result.error or "")

        # audit
        events = audit_writer.get_all_for_tenant("tenant-x")
        assert events, "pelo menos um evento de audit deve existir"
        for event in events:
            dumped = str(event.result_summary)
            assert CANARY not in dumped
            assert CANARY_PREFIX not in dumped

        # telemetry
        for record in telemetry_recorder.get_all_for_tenant("tenant-x"):
            dumped = repr(record)
            assert CANARY not in dumped
            assert CANARY_PREFIX not in dumped

        # logs — msg E exc_text (logger.exception) scrubbed, não só getMessage
        for record in caplog.records:
            emitted = record.getMessage() + (record.exc_text or "")
            assert CANARY not in emitted
            assert CANARY_PREFIX not in emitted


# ─── SecretScrubbingFilter (loggers do SDK: mcp/fastmcp/httpcore/httpx) ────

class TestSecretScrubbingFilter:
    """Defense-in-depth: filtro anexado aos loggers de terceiros neutraliza
    msg pré-interpolada E traceback (exc_text) com o canário embutido."""

    def _format_record(self, record: logging.LogRecord) -> str:
        formatter = logging.Formatter("%(message)s")
        return formatter.format(record)

    def test_message_with_args_canary_scrubbed(self):
        from cognitive.gate.redaction import SecretScrubbingFilter

        record = logging.LogRecord(
            name="mcp.client.streamable_http",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="Error in post_writer: %s",
            args=(f"Illegal header value b'Bearer {CANARY}\\r'",),
            exc_info=None,
        )
        assert SecretScrubbingFilter().filter(record)
        out = self._format_record(record)
        assert CANARY not in out
        assert CANARY_PREFIX not in out

    def test_exc_info_traceback_canary_scrubbed(self):
        import sys

        from cognitive.gate.redaction import SecretScrubbingFilter

        try:
            raise RuntimeError(f"Illegal header value b'Bearer {CANARY}\\r'")
        except RuntimeError:
            exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="httpcore._async.http11",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="exception=%s",
            args=("stream error",),
            exc_info=exc_info,
        )
        assert SecretScrubbingFilter().filter(record)
        out = self._format_record(record)
        assert CANARY not in out
        assert CANARY_PREFIX not in out
        assert record.exc_text is not None  # traceback preservado, mas sanitizado