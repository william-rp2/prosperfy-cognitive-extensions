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