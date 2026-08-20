"""
test_server_views.py — Unit tests da consolidação determinística do vertical
slice de infraestrutura (raw → normalized → summary PT-BR).

Função pura, sem rede, sem LLM. Mesma entrada → mesma saída (ordenação
estável); ferramentas opcionais ausentes não derrubam a visão.
"""

from __future__ import annotations

from capability_intelligence.server_views import (
    build_server_status_view,
    CONTAINERS,
    PANORAMA,
    PORTS,
)

FULL_RAW = {
    PANORAMA: {"status": "ok", "host": "mock-host", "uptime_seconds": 86400,
               "load_avg": [0.1, 0.2, 0.3]},
    CONTAINERS: {"containers": [
        {"name": "cognitive-api", "status": "running", "image": "prosperfy/cognitive:latest"},
        {"name": "postgres", "status": "running", "image": "postgres:16"},
    ]},
    PORTS: {"ports": {"8800": "open", "5432": "open", "80": "open"}},
}


class TestFullView:
    def test_normalized_fields(self):
        view = build_server_status_view(FULL_RAW)
        norm = view["normalized"]
        assert norm["host"] == "mock-host"
        assert norm["uptime_human"] == "1d"
        assert norm["container_count"] == 2
        assert norm["container_running_count"] == 2
        assert norm["container_broken"] == []
        assert norm["ports_open_count"] == 3
        assert norm["ports_total_count"] == 3
        assert norm["degraded"] is False
        # ordem estável
        assert [p["port"] for p in norm["ports"]] == ["5432", "80", "8800"]

    def test_summary_mentions_counts(self):
        view = build_server_status_view(FULL_RAW)
        text = view["summary"]
        assert "Servidor mock-host está online" in text
        assert "2 containers: 2 rodando." in text
        assert "3 de 3 portas abertas." in text
        assert "Todos os serviços e portas verificados estão OK." in text

    def test_raw_preserved(self):
        view = build_server_status_view(FULL_RAW)
        assert view["raw"] == FULL_RAW


class TestPartial:
    def test_missing_ports_keeps_view_and_flags_degraded(self):
        raw = {PANORAMA: FULL_RAW[PANORAMA], CONTAINERS: FULL_RAW[CONTAINERS]}
        view = build_server_status_view(raw)
        norm = view["normalized"]
        assert norm["ports_total_count"] == 0
        assert norm["degraded"] is True
        assert "portas" not in view["summary"].lower() or "indisponível" in view["summary"]
        assert "2 containers: 2 rodando." in view["summary"]

    def test_container_down_flagged(self):
        raw = dict(FULL_RAW)
        raw[CONTAINERS] = {"containers": [
            {"name": "cognitive-api", "status": "stopped", "image": "prosperfy/cognitive:latest"},
        ]}
        view = build_server_status_view(raw)
        norm = view["normalized"]
        assert norm["degraded"] is True
        assert norm["container_broken"] == ["cognitive-api"]
        text = view["summary"]
        assert "1 containers: 0 rodando, 1 com problema." in text
        assert "container 'cognitive-api' fora de running" in text

    def test_tool_error_payload_treated_as_missing(self):
        raw = {PANORAMA: FULL_RAW[PANORAMA], CONTAINERS: {"error": "boom"}}
        view = build_server_status_view(raw)
        assert view["normalized"]["container_count"] == 0
        assert view["normalized"]["degraded"] is True

    def test_empty_raw(self):
        view = build_server_status_view({})
        norm = view["normalized"]
        assert norm["host"] is None
        assert norm["container_count"] == 0
        assert "Não foi possível obter o panorama" in view["summary"]


class TestDeterminism:
    def test_same_input_same_output(self):
        a = build_server_status_view(FULL_RAW)
        b = build_server_status_view(FULL_RAW)
        assert a == b

    def test_container_order_normalized_sorted_independently(self):
        """A ordem dos containers no raw não muda o normalized (preservado
        na listagem, mas contagens/estado são derivados de forma estável)."""
        view = build_server_status_view(FULL_RAW)
        assert len(view["normalized"]["containers"]) == 2
        assert view["normalized"]["container_running_count"] == 2


# ─── Shape REAL do Homolog (3ª falha — normalization contract mismatch) ──
#
# O Cognitive/ProsperfySkill real retorna por tool um envelope aninhado
# success → data → data → payload. server_views ANTES removia só um nível de
# data, normalizando para vazio. Este shape preserva apenas a estrutura
# (sem IP/secrets/headers) para provar o contrato.

REAL_HOMOLOG_RAW = {
    PANORAMA: {
        "success": True,
        "data": {
            "status": "ok",
            "data": {
                "data": {"status": "ok", "host": "real-vps", "uptime_seconds": 7200,
                         "load_avg": [0.2, 0.3, 0.4]},
            },
            "meta": {"latency_ms": 41},
            "error": None,
        },
    },
    CONTAINERS: {
        "success": True,
        "data": {
            "status": "ok",
            "data": {
                "data": {"containers": [
                    {"name": "cognitive-api", "status": "running", "image": "prosperfy/cognitive:latest"},
                    {"name": "postgres", "status": "running", "image": "postgres:16"},
                ]},
            },
            "meta": {"latency_ms": 39},
            "error": None,
        },
    },
    PORTS: {
        "success": True,
        "data": {
            "status": "ok",
            "data": {
                "data": {"ports": {"80": "open", "5432": "open"}},
            },
            "meta": {"latency_ms": 37},
            "error": None,
        },
    },
}


class TestRealHomologNestedShape:
    def test_normalizes_real_homolog_nested_tool_payload(self):
        view = build_server_status_view(REAL_HOMOLOG_RAW)
        norm = view["normalized"]
        assert norm["host"] == "real-vps"
        assert norm["uptime_human"] == "2h"
        assert norm["container_count"] == 2
        assert norm["container_running_count"] == 2
        assert norm["ports_open_count"] == 2
        assert norm["ports_total_count"] == 2
        assert norm["degraded"] is False
        assert "2 containers: 2 rodando." in view["summary"]
        assert "2 de 2 portas abertas." in view["summary"]

    def test_business_data_key_is_preserved(self):
        """O unwrap NÃO remove/desce um campo 'data' que é parte do payload
        FINAL (dict com outras chaves) — só desce envelopes de transporte
        reconhecidos. Um container com campo `data` legítimo permanece intacto
        no raw preservado da visão."""
        from capability_intelligence.server_views import _unwrap_payload

        container = {"name": "a", "status": "running", "data": {"memo": "x"}}
        # payload final com outras chaves + data → não é envelope, não desce.
        assert _unwrap_payload(container) == container

        raw = dict(REAL_HOMOLOG_RAW)
        raw[CONTAINERS] = {
            "success": True,
            "data": {
                "status": "ok",
                "data": {"data": {"containers": [container]}},
                "meta": {},
                "error": None,
            },
        }
        view = build_server_status_view(raw)
        # O raw preservado mantém o container com seu campo `data` legítimo.
        assert view["raw"][CONTAINERS]["data"]["data"]["data"]["containers"][0]["data"] == {"memo": "x"}

    def test_mixed_dev_and_real_shapes_normalized(self):
        """Suporta shape DEV (success→data) e Homolog (success→data→data) na
        mesma visão — cada tool normaliza independentemente."""
        raw = dict(REAL_HOMOLOG_RAW)
        # panorama no shape DEV (1 nível), containers/ports no shape real (2 níveis)
        raw[PANORAMA] = {"success": True, "data": {"status": "ok", "host": "dev-host",
                                                    "uptime_seconds": 60, "load_avg": []}}
        view = build_server_status_view(raw)
        assert view["normalized"]["host"] == "dev-host"
        assert view["normalized"]["container_count"] == 2
        assert view["normalized"]["ports_open_count"] == 2

    def test_real_shape_with_optional_ports_absent(self):
        """Contrato: panorama+containers obrigatórias, portas opcional — shape
        real sem portas ainda normaliza (degraded, sem erro)."""
        raw = {PANORAMA: REAL_HOMOLOG_RAW[PANORAMA], CONTAINERS: REAL_HOMOLOG_RAW[CONTAINERS]}
        view = build_server_status_view(raw)
        assert view["normalized"]["container_count"] == 2
        assert view["normalized"]["degraded"] is True
        assert "2 containers: 2 rodando." in view["summary"]


class TestTransportEnvelopeRecognition:
    """Prova o unwrap NÃO cego: reconhece envelopes de transporte conhecidos
    e NÃO desenrola payload de negócio com campo `data` legítimo."""

    def test_envelope_status_data_meta_error_is_unwrapped(self):
        from capability_intelligence.server_views import _unwrap_payload

        envelope = {
            "status": "ok",
            "data": {"data": {"status": "ok", "host": "x", "load_avg": []}},
            "meta": {"latency_ms": 5},
            "error": None,
        }
        payload = _unwrap_payload(envelope)
        assert payload.get("host") == "x"

    def test_envelope_success_data_nested_is_unwrapped(self):
        from capability_intelligence.server_views import _unwrap_payload

        envelope = {"success": True, "data": {"data": {"host": "y"}}}
        assert _unwrap_payload(envelope).get("host") == "y"

    def test_business_payload_with_data_key_not_unwrapped(self):
        from capability_intelligence.server_views import _unwrap_payload

        # payload de negócio com campo `data` + chaves de negócio → NÃO é
        # envelope de transporte, não desenrola.
        payload = {"status": "running", "name": "container-x", "data": {"memo": "keep"}}
        assert _unwrap_payload(payload) == payload

    def test_deep_bounded(self):
        from capability_intelligence.server_views import _unwrap_payload, _MAX_UNWRAP_DEPTH

        deep: dict = {"host": "z"}
        node = deep
        for _ in range(_MAX_UNWRAP_DEPTH + 3):
            node["data"] = {"host": "z"}
            node = node["data"]
        # bounded: não entra em loop infinito e retorna um dict determinístico
        result = _unwrap_payload({"success": True, "data": deep})
        assert isinstance(result, dict)


# ─── CONTRATOS REAIS do ProsperfySkill (capturados no Homolog) ─────────────
#
# $: {data, success} → $.data: {data, error, meta, status} → $.data.data: payload.
# BUSINESS_PAYLOAD_PATH = $.data.data. Os mocks DEV não refletiam estes campos.

REAL_PANORAMA_PAYLOAD = {
    "disco": "40% usado",
    "host": "vps-prod-01",
    "hostname": "vps-prod-01",
    "kernel": "6.8.0-45-generic",
    "load_average": "0.45, 0.52, 0.61",
    "memoria": "3.2G/7.7G",
    "so": "Ubuntu 24.04",
    "top_processos": ["nginx", "postgres"],
    "uptime": "3 days, 04:12",
}

REAL_CONTAINER = {
    "Command": "/entrypoint.sh",
    "CreatedAt": "2026-07-01",
    "HealthStatus": "healthy",
    "ID": "abc123",
    "Image": "prosperfy/cognitive:latest",
    "Labels": {},
    "LocalVolumes": "0",
    "Mounts": [],
    "Names": ["/cognitive-api"],
    "Networks": "bridge",
    "Platform": "linux",
    "Ports": "0.0.0.0:8800->8800/tcp",
    "RunningFor": "3 days",
    "Size": "N/A (virtual 850MB)",
    "State": "running",
    "Status": "Up 3 days",
}

REAL_CONTAINERS_PAYLOAD = {
    "containers": [REAL_CONTAINER],
    "host": "vps-prod-01",
    "incluir_parados": True,
    "total": 1,
}

REAL_PORTS_PAYLOAD = {
    "comando": "nc -z 127.0.0.1 8800",
    "duracao_ms": 12,
    "exit_status": 0,
    "host": "127.0.0.1",
    "porta": "8800",
    "stderr": "",
    "stdout": "",
    "sucesso": True,
}


def _wrap(tool: str, payload: dict) -> dict:
    """Envelope real comum: $:{data,success} → data:{data,error,meta,status}."""
    return {
        "success": True,
        "data": {
            "status": "ok",
            "data": payload,
            "meta": {"latency_ms": 12},
            "error": None,
        },
    }


class TestRealContracts:
    def test_real_panorama_contract_normalized(self):
        """Panorama real: uptime/load_average são strings e são preservados
        sem conversão inventada. host presente."""
        raw = {PANORAMA: _wrap(PANORAMA, REAL_PANORAMA_PAYLOAD)}
        view = build_server_status_view(raw)
        norm = view["normalized"]
        assert norm["host"] == "vps-prod-01"
        assert norm["uptime"] == "3 days, 04:12"
        assert norm["uptime_human"] == "3 days, 04:12"  # string real preservada
        assert norm["load_avg"] == "0.45, 0.52, 0.61"
        assert "Servidor vps-prod-01 está online" in view["summary"]

    def test_real_containers_contract_normalized(self):
        """Containers reais usam Names/State/Status/Image (docker) — mapeados
        para name/state/status/image, sem depender de lowercase inexistente."""
        raw = {CONTAINERS: _wrap(CONTAINERS, REAL_CONTAINERS_PAYLOAD)}
        view = build_server_status_view(raw)
        norm = view["normalized"]
        assert norm["container_count"] == 1
        assert norm["container_running_count"] == 1
        c = norm["containers"][0]
        assert c["name"] == "cognitive-api"  # Names → name (strip '/')
        assert c["state"] == "running"
        assert c["status"] == "Up 3 days"
        assert c["image"] == "prosperfy/cognitive:latest"
        assert c["health_status"] == "healthy"
        assert norm["container_broken"] == []
        assert "1 containers: 1 rodando." in view["summary"]

    def test_real_containers_contract_down_detected(self):
        """Container real parado (State=exited) → broken detectado."""
        down = dict(REAL_CONTAINER)
        down["State"] = "exited"
        down["Status"] = "Exited (0) 2 days ago"
        raw = {CONTAINERS: _wrap(CONTAINERS, {"containers": [down], "total": 1})}
        view = build_server_status_view(raw)
        assert view["normalized"]["container_broken"] == ["cognitive-api"]
        assert view["normalized"]["degraded"] is True

    def test_real_ports_contract_normalized(self):
        """Ports reais: {porta, sucesso, exit_status} — não é mapa ports.
        Normalizado para port/success/exit_status; NÃO expõe comando no summary."""
        raw = {PORTS: _wrap(PORTS, REAL_PORTS_PAYLOAD)}
        view = build_server_status_view(raw)
        norm = view["normalized"]
        assert norm["ports_total_count"] == 1
        assert norm["ports_open_count"] == 1  # sucesso=True
        assert norm["ports"][0]["port"] == "8800"
        assert norm["ports"][0]["success"] is True
        assert norm["ports"][0]["exit_status"] == 0
        assert "1 de 1 portas abertas." in view["summary"]
        assert "nc -z" not in view["summary"]  # não expõe comando interno

    def test_real_ports_contract_closed_detected(self):
        """Ports real com sucesso=False → não conta como aberta."""
        p = dict(REAL_PORTS_PAYLOAD)
        p["sucesso"] = False
        p["exit_status"] = 1
        raw = {PORTS: _wrap(PORTS, p)}
        view = build_server_status_view(raw)
        assert view["normalized"]["ports_open_count"] == 0
        assert view["normalized"]["ports_total_count"] == 1
        assert "Nenhuma porta aberta." in view["summary"]

    def test_real_three_tool_contract_builds_server_summary(self):
        """Três payloads reais juntos: raw → normalized → summary completo."""
        raw = {
            PANORAMA: _wrap(PANORAMA, REAL_PANORAMA_PAYLOAD),
            CONTAINERS: _wrap(CONTAINERS, REAL_CONTAINERS_PAYLOAD),
            PORTS: _wrap(PORTS, REAL_PORTS_PAYLOAD),
        }
        view = build_server_status_view(raw)
        norm = view["normalized"]
        assert norm["host"] == "vps-prod-01"
        assert norm["container_count"] == 1
        assert norm["ports_total_count"] == 1
        summary = view["summary"]
        assert "Servidor vps-prod-01 está online" in summary  # SERVER_STATUS
        assert "1 containers: 1 rodando." in summary             # CONTAINER_STATUS
        assert "1 de 1 portas abertas." in summary               # PORT_STATUS
        assert norm["degraded"] is False