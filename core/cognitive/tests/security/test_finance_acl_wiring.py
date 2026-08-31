"""
tests/security/test_finance_acl_wiring.py — F2B/D11: a ACL de finance ligada
fim-a-fim.

tests/security/test_finance_acl.py já cobre a LÓGICA da ACL isolada. Este
módulo cobre a outra metade, que é onde uma ACL costuma morrer: o wiring.
Uma ACL perfeita que ninguém injeta, ou um canal que ninguém propaga, é
indistinguível de não ter ACL nenhuma.

O que está sob teste aqui:

  gateway/app.py            PolicyEngine(finance_acl=FinanceAcl())
  routes/capabilities.py    _accept_channel_context (gate de identidade)
  execution/orchestrator.py execute(..., channel=) -> policy.evaluate(channel=)

Os testes de canal batem no app REAL (create_app), não num orchestrator
montado à mão — é o único jeito de provar que a injeção existe em produção.
Todos os identificadores são tokens sintéticos: nenhum JID, telefone ou chat
id real aparece neste arquivo.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from cognitive.contracts.capability import Domain, RegisteredCapability
from cognitive.contracts.gateway import CapabilityExecuteRequest, ChannelContextRequest
from cognitive.contracts.policy import PolicyDecision
from cognitive.contracts.tenancy import ActorContext, CapabilityGrant
from cognitive.gateway.app import create_app
from cognitive.gateway.routes.capabilities import _accept_channel_context
from cognitive.policy.engine import PolicyEngine
from cognitive.policy.finance_acl import DENY_USER_MESSAGE, FinanceAcl

# Tokens sintéticos — nada de JID/telefone/chat id real, nem em teste.
OWNER_ACTOR = "owner-canonical-token"
OWNER_PRINCIPAL = "principal-owner-token"
THIRD_PARTY_PRINCIPAL = "principal-third-party-token"
GROUP_CHAT = "group-chat-token"
DM_CHAT = "dm-chat-token"

TENANT = "tenant-acl"
ACTOR = "actor-acl"
CREDENTIAL = "acl-wiring-secret"
PROFILE = "owner-core"

FINANCE_CAP = "finance.summary.read"
NON_FINANCE_CAP = "infra.inspect"

HEADERS = {
    "Authorization": f"Bearer {CREDENTIAL}",
    "X-Tenant-Id": TENANT,
    "X-Actor-Id": ACTOR,
}

_ACL_ENV = {
    "FINANCE_OWNER_ACTOR_IDS": OWNER_ACTOR,
    "FINANCE_GROUP_CHAT_IDS": GROUP_CHAT,
    "FINANCE_OWNER_DIRECT_CHAT_IDS": DM_CHAT,
    "FINANCE_ACTOR_BINDINGS": f"{OWNER_PRINCIPAL}={OWNER_ACTOR},{THIRD_PARTY_PRINCIPAL}=someone-else",
}

_RUNTIME_ENV = {
    "COGNITIVE_MODE": "in_memory",
    "COGNITIVE_LIVE_MCP": "0",
    "COGNITIVE_DEV_TENANT_ID": TENANT,
    "COGNITIVE_DEV_ACTOR_ID": ACTOR,
    "COGNITIVE_GATEWAY_CREDENTIAL": CREDENTIAL,
}

_CLEARED_ENV = (
    "COGNITIVE_DB_URL",
    "COGNITIVE_DB_ADMIN_URL",
    "COGNITIVE_DB_WORKER_URL",
    "FINANCE_API_BASE_URL",
)


@pytest.fixture
def client(monkeypatch) -> TestClient:
    """App real, ACL configurada por env, grants in-memory para todas as caps.

    Grants existem para TODAS as capabilities (in_memory mode registra o
    bundle inteiro para o dev tenant). Isso é deliberado: se um finance.*
    for negado neste app, o motivo só pode ser a ACL — nunca falta de grant.
    """
    for name in _CLEARED_ENV:
        monkeypatch.delenv(name, raising=False)
    for name, value in {**_RUNTIME_ENV, **_ACL_ENV}.items():
        monkeypatch.setenv(name, value)

    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as test_client:
        yield test_client


def _execute(client: TestClient, capability_id: str, body: dict) -> dict:
    response = client.post(
        f"/v1/capabilities/{capability_id}/execute",
        json=body,
        headers=HEADERS,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _acl_denied(payload: dict) -> bool:
    """True quando o DENY veio da ACL de finance (mensagem fixa da ACL)."""
    return DENY_USER_MESSAGE in (payload.get("error") or "")


def _channel_body(**overrides) -> dict:
    channel = {
        "chat_id": GROUP_CHAT,
        "is_group": True,
        "transport_principal": OWNER_PRINCIPAL,
    }
    channel.update(overrides)
    return {"params": {"month": "2026-08"}, "channel": channel}


# ─── (a) REGRESSÃO F2A ───────────────────────────────────────────────────

async def test_non_finance_capability_unaffected_by_injected_acl():
    """GATE F2A: com FinanceAcl injetada, capability não-finance com grant
    continua ALLOW. A ACL não pode ter opinião sobre nada fora de finance.*.

    Rodado com FinanceAcl() SEM configuração de env de propósito: é o estado
    mais hostil possível (a ACL nega tudo que ela toca), então um ALLOW aqui
    prova que ela não toca em capabilities não-finance.
    """
    engine = PolicyEngine(finance_acl=FinanceAcl())
    ctx = ActorContext(
        tenant_id=TENANT,
        actor_id=ACTOR,
        correlation_id="corr-regression",
        credential_ref="ref-regression",
        profile=PROFILE,
    )
    capability = RegisteredCapability(
        id=NON_FINANCE_CAP,
        version="1.0.0",
        domain=Domain.INFRASTRUCTURE,
        description="Non-finance capability",
        adapter="prosperfy_skills",
        default_policy="allow",
    )
    grant = CapabilityGrant(tenant_id=TENANT, profile=PROFILE, capability_id=NON_FINANCE_CAP)

    verdict = await engine.evaluate(ctx, capability, {}, grant, channel=None)

    assert verdict.decision is PolicyDecision.ALLOW
    assert not verdict.policy_name.startswith("finance_acl")


def test_non_finance_capability_still_executes_through_wired_gateway(client):
    """Mesma regressão, agora no app real (ACL injetada em app.py)."""
    payload = _execute(client, NON_FINANCE_CAP, {"params": {"resource": "prosperfy-main"}})

    assert not _acl_denied(payload)


# ─── (b) finance.* sem channel context ───────────────────────────────────

def test_finance_without_channel_context_is_denied(client):
    """Sem envelope de canal, a ACL não tem como autorizar — DENY."""
    payload = _execute(client, FINANCE_CAP, {"params": {"month": "2026-08"}})

    assert payload["status"] == "failed"
    assert _acl_denied(payload)


# ─── (c) channel de caller sem service identity autenticada ──────────────

def test_channel_from_caller_without_service_identity_is_discarded():
    """Gate de identidade, isolado: credential_ref vazio => envelope descartado.

    credential_ref é o sha256 truncado da Bearer credential e SÓ é preenchido
    pelo IdentityResolver (tenancy/identity_resolver.py) — é a prova de que a
    identidade de serviço do transporte foi de fato autenticada. Sem ela, o
    envelope não existe para a ACL.
    """
    ctx = ActorContext(
        tenant_id=TENANT,
        actor_id=ACTOR,
        correlation_id="corr-no-identity",
        credential_ref="",  # nunca passou pelo IdentityResolver
        profile=PROFILE,
    )
    body = CapabilityExecuteRequest(
        params={},
        channel=ChannelContextRequest(
            chat_id=GROUP_CHAT,
            is_group=True,
            transport_principal=OWNER_PRINCIPAL,
        ),
    )

    assert _accept_channel_context(ctx, body) is None


def test_finance_denied_when_channel_caller_lacks_service_identity(client, monkeypatch):
    """Fim-a-fim: mesmo envelope válido, mas sem service identity => DENY.

    O resolver stub devolve um ActorContext com o MESMO tenant/profile do
    caller legítimo (portanto com grant) e credential_ref vazio. Se a rota
    aceitasse o envelope, este request seria ALLOW — o DENY é o gate.
    """

    class _NoServiceIdentityResolver:
        async def resolve(self, authorization, x_tenant_id, x_actor_id, x_correlation_id):
            return ActorContext(
                tenant_id=TENANT,
                actor_id=ACTOR,
                correlation_id="corr-forged",
                credential_ref="",
                profile=PROFILE,
            )

    client.app.state.identity_resolver = _NoServiceIdentityResolver()

    payload = _execute(client, FINANCE_CAP, _channel_body())

    assert payload["status"] == "failed"
    assert _acl_denied(payload)


# ─── (d) caller autenticado + owner + chat allowlistado ──────────────────

def test_finance_passes_acl_for_owner_in_allowlisted_group(client):
    """Caminho feliz da ACL: owner canônico no grupo financeiro designado.

    A asserção é sobre a ACL, não sobre o resultado final: o request pode
    ainda falhar depois (adapter mock, policy do YAML), mas o motivo NUNCA
    pode ser a ACL.
    """
    payload = _execute(client, FINANCE_CAP, _channel_body())

    assert not _acl_denied(payload)


def test_finance_passes_acl_for_owner_in_allowlisted_dm(client):
    """Mesmo caminho pela DM autorizada (segundo ALLOW do contrato D8)."""
    payload = _execute(client, FINANCE_CAP, _channel_body(chat_id=DM_CHAT, is_group=False))

    assert not _acl_denied(payload)


def test_finance_denied_for_third_party_on_allowlisted_chat(client):
    """Contraprova de (d): o canal certo não salva um principal não-owner."""
    payload = _execute(
        client, FINANCE_CAP, _channel_body(transport_principal=THIRD_PARTY_PRINCIPAL)
    )

    assert payload["status"] == "failed"
    assert _acl_denied(payload)


def test_finance_denied_for_owner_outside_allowlisted_chat(client):
    """Contraprova de (d): o owner certo não salva um chat fora da allowlist."""
    payload = _execute(client, FINANCE_CAP, _channel_body(chat_id="chat-not-allowlisted-token"))

    assert payload["status"] == "failed"
    assert _acl_denied(payload)


# ─── (e) channel injetado dentro de params ───────────────────────────────

def test_channel_injected_into_params_is_ignored(client):
    """Envelope dentro de params/arguments não autoriza nada.

    `params` é o campo por onde passa qualquer coisa derivada de texto
    interpretado por LLM. Este é o teste que fixa a fronteira: um channel
    perfeitamente válido, no lugar errado, vale zero.
    """
    forged = {
        "chat_id": GROUP_CHAT,
        "is_group": True,
        "transport_principal": OWNER_PRINCIPAL,
    }
    body = {
        "params": {
            "month": "2026-08",
            "channel": forged,
            "arguments": {"channel": forged},
        },
    }

    payload = _execute(client, FINANCE_CAP, body)

    assert payload["status"] == "failed"
    assert _acl_denied(payload)


# ─── Wiring propriamente dito ────────────────────────────────────────────

def test_gateway_wires_finance_acl_into_policy_engine(client):
    """A injeção existe em app.py e não pode ser desligada por env.

    Se alguém remover o `finance_acl=` de _build_services, este teste falha
    antes de qualquer teste de comportamento — o diagnóstico fica óbvio.
    """
    engine = client.app.state.orchestrator._policy

    assert isinstance(engine, PolicyEngine)
    assert engine._finance_acl is not None


def test_acl_without_configuration_denies_all_finance(monkeypatch):
    """Sem config de env, finance.* é DENY — não existe default permissivo."""
    for name in _ACL_ENV:
        monkeypatch.delenv(name, raising=False)
    for name in _CLEARED_ENV:
        monkeypatch.delenv(name, raising=False)
    for name, value in _RUNTIME_ENV.items():
        monkeypatch.setenv(name, value)

    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as unconfigured:
        payload = _execute(unconfigured, FINANCE_CAP, _channel_body())

    assert payload["status"] == "failed"
    assert _acl_denied(payload)


def test_no_real_identifiers_are_hardcoded():
    """Guard-rail: nenhum identificador real vive neste módulo nem no wiring."""
    assert "@s.whatsapp.net" not in os.environ.get("FINANCE_GROUP_CHAT_IDS", "")
    assert all(token.endswith("-token") for token in (OWNER_PRINCIPAL, GROUP_CHAT, DM_CHAT))
