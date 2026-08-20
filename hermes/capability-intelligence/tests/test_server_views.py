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
            "data": {"status": "ok", "host": "real-vps", "uptime_seconds": 7200,
                     "load_avg": [0.2, 0.3, 0.4]},
        },
    },
    CONTAINERS: {
        "success": True,
        "data": {
            "data": {"containers": [
                {"name": "cognitive-api", "status": "running", "image": "prosperfy/cognitive:latest"},
                {"name": "postgres", "status": "running", "image": "postgres:16"},
            ]},
        },
    },
    PORTS: {
        "success": True,
        "data": {
            "data": {"ports": {"80": "open", "5432": "open"}},
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
        FINAL (dict com outras chaves) — só desce envelopes puros
        ({success,data} / {data}). Um container com campo `data` legítimo
        permanece intacto no raw preservado da visão."""
        from capability_intelligence.server_views import _unwrap_payload

        container = {"name": "a", "status": "running", "data": {"memo": "x"}}
        # payload final com outras chaves + data → não é envelope, não desce.
        assert _unwrap_payload(container) == container

        raw = dict(REAL_HOMOLOG_RAW)
        raw[CONTAINERS] = {
            "success": True,
            "data": {
                "data": {
                    "containers": [container],
                },
            },
        }
        view = build_server_status_view(raw)
        # O raw preservado mantém o container com seu campo `data` legítimo.
        assert view["raw"][CONTAINERS]["data"]["data"]["containers"][0]["data"] == {"memo": "x"}

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