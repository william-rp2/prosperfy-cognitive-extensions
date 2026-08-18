"""
tests/unit/test_identity_repo_events.py

Sprint 0.4: register()/deactivate()/rotate() em ServiceIdentityRepository
devem gravar uma linha em identity_events na MESMA transação
admin_connection() que escreve service_identities — nunca dois round trips
que poderiam divergir. Este arquivo prova o contrato de controle de fluxo
Python (ordem de statements, uso de UMA transação, propagação de
ValueError em rotate()) — não o comportamento real de commit/rollback do
Postgres, que só pode ser provado contra um banco de verdade (ver
tests/db/test_identity_lifecycle_audit.py, skip local, roda no Gate).

Mocka admin_connection()/conn — sem DB real necessário. Segue o padrão de
FakeConn de tests/unit/test_identity_repo_least_privilege.py e o padrão de
FakeTransaction (log de BEGIN/COMMIT/ROLLBACK) de
tests/unit/test_runner_atomicity.py.
"""

from __future__ import annotations

import contextlib
import uuid

import pytest

from cognitive.db.repositories import identity_repo as identity_repo_module
from cognitive.db.repositories.identity_repo import ServiceIdentityRepository, hash_credential

TENANT_ID = "11111111-1111-1111-1111-111111111111"


class FakeTransaction:
    """Mocka `async with conn.transaction():` — registra BEGIN/COMMIT/
    ROLLBACK, igual ao FakeTransaction de test_runner_atomicity.py."""

    def __init__(self, log: list[str]):
        self._log = log

    async def __aenter__(self):
        self._log.append("BEGIN")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._log.append("ROLLBACK" if exc_type else "COMMIT")
        return False  # nunca engole a exceção


class FakeConn:
    """Conexão fake que roteia fetchrow por conteúdo da query (INSERT em
    service_identities vs UPDATE em service_identities) — precisa disso
    porque register()/deactivate()/rotate() agora fazem múltiplos
    fetchrow/execute na mesma conexão, em ordens diferentes."""

    def __init__(self, *, register_row: dict | None = None, deactivate_row: dict | None = None):
        self.log: list[str] = []
        self.fetchrow_calls: list[tuple[str, tuple]] = []
        self.execute_calls: list[tuple[str, tuple]] = []
        self._register_row = register_row
        self._deactivate_row = deactivate_row

    def transaction(self):
        return FakeTransaction(self.log)

    async def fetchrow(self, query, *args):
        self.fetchrow_calls.append((query, args))
        self.log.append(f"FETCHROW[{len(self.fetchrow_calls)}]")
        if "INSERT INTO service_identities" in query:
            return self._register_row
        if "UPDATE service_identities" in query:
            return self._deactivate_row
        raise AssertionError(f"unexpected fetchrow query: {query}")

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))
        self.log.append(f"EXEC[{len(self.execute_calls)}]")


@contextlib.asynccontextmanager
async def _fake_ctx(conn):
    yield conn


def _service_identity_row(*, credential: str, actor_id: str = "actor-1", profile: str = "owner-core"):
    return {
        "id": uuid.uuid4(),
        "tenant_id": uuid.UUID(TENANT_ID),
        "actor_id": actor_id,
        "credential_hash": hash_credential(credential),
        "profile": profile,
        "active": True,
    }


class TestRegisterWritesEventInSameTransaction:
    @pytest.mark.asyncio
    async def test_register_inserts_identity_then_registered_event(self, monkeypatch):
        conn = FakeConn(register_row=_service_identity_row(credential="cred"))
        monkeypatch.setattr(identity_repo_module, "admin_connection", lambda: _fake_ctx(conn))

        repo = ServiceIdentityRepository()
        result = await repo.register(TENANT_ID, "actor-1", "cred")

        assert conn.log == ["BEGIN", "FETCHROW[1]", "EXEC[1]", "COMMIT"]
        assert len(conn.fetchrow_calls) == 1
        assert "INSERT INTO service_identities" in conn.fetchrow_calls[0][0]
        assert len(conn.execute_calls) == 1
        event_query, event_args = conn.execute_calls[0]
        assert "INSERT INTO identity_events" in event_query
        assert "'registered'" in event_query
        assert result.actor_id == "actor-1"

    @pytest.mark.asyncio
    async def test_register_event_carries_the_new_identity_id_and_tenant(self, monkeypatch):
        row = _service_identity_row(credential="cred")
        conn = FakeConn(register_row=row)
        monkeypatch.setattr(identity_repo_module, "admin_connection", lambda: _fake_ctx(conn))

        repo = ServiceIdentityRepository()
        await repo.register(TENANT_ID, "actor-1", "cred")

        _, event_args = conn.execute_calls[0]
        assert event_args[0] == row["id"]
        assert event_args[1] == row["tenant_id"]
        assert event_args[2] == row["actor_id"]
        assert event_args[3] == row["profile"]

    @pytest.mark.asyncio
    async def test_register_single_transaction_not_two_round_trips(self, monkeypatch):
        """A gravação de service_identities e de identity_events acontece
        dentro do MESMO BEGIN/COMMIT — nunca duas transações separadas que
        poderiam divergir se uma falhar."""
        conn = FakeConn(register_row=_service_identity_row(credential="cred"))
        monkeypatch.setattr(identity_repo_module, "admin_connection", lambda: _fake_ctx(conn))

        repo = ServiceIdentityRepository()
        await repo.register(TENANT_ID, "actor-1", "cred")

        assert conn.log.count("BEGIN") == 1
        assert conn.log.count("COMMIT") == 1
        assert "ROLLBACK" not in conn.log


class TestDeactivateWritesEventInSameTransaction:
    @pytest.mark.asyncio
    async def test_deactivate_updates_identity_then_deactivated_event(self, monkeypatch):
        conn = FakeConn(deactivate_row=_service_identity_row(credential="cred"))
        monkeypatch.setattr(identity_repo_module, "admin_connection", lambda: _fake_ctx(conn))

        repo = ServiceIdentityRepository()
        await repo.deactivate("cred")

        assert conn.log == ["BEGIN", "FETCHROW[1]", "EXEC[1]", "COMMIT"]
        assert "UPDATE service_identities" in conn.fetchrow_calls[0][0]
        event_query, _ = conn.execute_calls[0]
        assert "INSERT INTO identity_events" in event_query
        assert "'deactivated'" in event_query

    @pytest.mark.asyncio
    async def test_deactivate_of_missing_credential_writes_no_event(self, monkeypatch):
        """UPDATE ... RETURNING não bate nenhuma linha (não existe ou já
        estava inativa) — nenhum evento é gravado, sem erro levantado
        (deactivate() é silencioso por design; ver rotate() para o caso
        que levanta ValueError)."""
        conn = FakeConn(deactivate_row=None)
        monkeypatch.setattr(identity_repo_module, "admin_connection", lambda: _fake_ctx(conn))

        repo = ServiceIdentityRepository()
        await repo.deactivate("never-registered")

        assert conn.log == ["BEGIN", "FETCHROW[1]", "COMMIT"]
        assert conn.execute_calls == []


class TestRotateComposesDeactivateThenRegisterInOneTransaction:
    @pytest.mark.asyncio
    async def test_rotate_deactivates_old_then_registers_new_in_one_transaction(self, monkeypatch):
        old_row = _service_identity_row(credential="old-cred", actor_id="actor-1", profile="owner-core")
        new_row = _service_identity_row(credential="new-cred", actor_id="actor-1", profile="owner-core")
        conn = FakeConn(deactivate_row=old_row, register_row=new_row)
        monkeypatch.setattr(identity_repo_module, "admin_connection", lambda: _fake_ctx(conn))

        repo = ServiceIdentityRepository()
        result = await repo.rotate("old-cred", "new-cred")

        # Exactly one BEGIN/COMMIT — deactivate+register share the same tx.
        assert conn.log == ["BEGIN", "FETCHROW[1]", "EXEC[1]", "FETCHROW[2]", "EXEC[2]", "COMMIT"]
        assert conn.log.count("BEGIN") == 1
        assert conn.log.count("COMMIT") == 1

        # Two identity_events rows: one 'deactivated', one 'registered'.
        assert len(conn.execute_calls) == 2
        first_event_query, _ = conn.execute_calls[0]
        second_event_query, _ = conn.execute_calls[1]
        assert "'deactivated'" in first_event_query
        assert "'registered'" in second_event_query

        # Old credential UPDATE happens before new credential INSERT.
        assert "UPDATE service_identities" in conn.fetchrow_calls[0][0]
        assert "INSERT INTO service_identities" in conn.fetchrow_calls[1][0]

        assert result.actor_id == "actor-1"

    @pytest.mark.asyncio
    async def test_rotate_reuses_tenant_actor_profile_from_deactivated_identity(self, monkeypatch):
        old_row = _service_identity_row(
            credential="old-cred", actor_id="actor-special", profile="infra-read"
        )
        new_row = _service_identity_row(
            credential="new-cred", actor_id="actor-special", profile="infra-read"
        )
        conn = FakeConn(deactivate_row=old_row, register_row=new_row)
        monkeypatch.setattr(identity_repo_module, "admin_connection", lambda: _fake_ctx(conn))

        repo = ServiceIdentityRepository()
        await repo.rotate("old-cred", "new-cred")

        register_query, register_args = conn.fetchrow_calls[1]
        assert "INSERT INTO service_identities" in register_query
        # tenant_id, actor_id, credential_hash(new), profile — from the
        # deactivated row's tenant/actor/profile, not hardcoded.
        assert register_args[0] == old_row["tenant_id"]
        assert register_args[1] == "actor-special"
        assert register_args[3] == "infra-read"

    @pytest.mark.asyncio
    async def test_rotate_raises_value_error_when_old_credential_not_found(self, monkeypatch):
        conn = FakeConn(deactivate_row=None)
        monkeypatch.setattr(identity_repo_module, "admin_connection", lambda: _fake_ctx(conn))

        repo = ServiceIdentityRepository()
        with pytest.raises(ValueError, match="não encontrada ou já inativa"):
            await repo.rotate("never-registered", "new-cred")

        # Never reaches the register step — no INSERT into service_identities.
        assert conn.execute_calls == []
        assert len(conn.fetchrow_calls) == 1
        assert "UPDATE service_identities" in conn.fetchrow_calls[0][0]

    @pytest.mark.asyncio
    async def test_rotate_failure_rolls_back_the_shared_transaction(self, monkeypatch):
        """Se old_credential não existe/já está inativa, a transação sai
        por ROLLBACK (via propagação do ValueError através de `async with
        conn.transaction():`), nunca COMMIT — não fica sem estado
        parcialmente escrito."""
        conn = FakeConn(deactivate_row=None)
        monkeypatch.setattr(identity_repo_module, "admin_connection", lambda: _fake_ctx(conn))

        repo = ServiceIdentityRepository()
        with pytest.raises(ValueError):
            await repo.rotate("never-registered", "new-cred")

        assert conn.log == ["BEGIN", "FETCHROW[1]", "ROLLBACK"]
        assert "COMMIT" not in conn.log

    @pytest.mark.asyncio
    async def test_rotate_never_calls_public_register_or_deactivate_methods(self, monkeypatch):
        """rotate() deve reusar a lógica interna (_do_register/_do_deactivate),
        nunca os métodos públicos register()/deactivate() — chamar os
        públicos abriria uma segunda admin_connection()/transação cada,
        quebrando a atomicidade de UMA transação só."""
        old_row = _service_identity_row(credential="old-cred")
        new_row = _service_identity_row(credential="new-cred")
        conn = FakeConn(deactivate_row=old_row, register_row=new_row)
        monkeypatch.setattr(identity_repo_module, "admin_connection", lambda: _fake_ctx(conn))

        repo = ServiceIdentityRepository()

        async def _forbidden(*args, **kwargs):
            raise AssertionError("rotate() must not call the public register()/deactivate()")

        monkeypatch.setattr(repo, "register", _forbidden)
        monkeypatch.setattr(repo, "deactivate", _forbidden)

        # Should not raise AssertionError — proves rotate() never touches
        # the patched public methods.
        await repo.rotate("old-cred", "new-cred")
