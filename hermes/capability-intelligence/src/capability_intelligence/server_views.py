"""
server_views.py — Consolidação determinística do vertical slice de infraestrutura.

Transforma o resultado CRU da capability `infra.inspect` (dict com uma chave
por tool MCP — `prosperfy_vps_panorama`, `prosperfy_vps_listar_containers`,
`prosperfy_vps_verificar_portas`) em uma visão normalizada + resumo em PT-BR
para consumo humano ("Como estão meus servidores?").

Sem LLM, sem framework: função pura e determinística (mesma entrada → mesma
saída, ordenação estável). Resposta divide explicitamente:
  raw        → payload original (para o chamador que precisa do detalhe bruto)
  normalized → campos estruturados/tipados derivados
  summary    → linhas de texto PT-BR prontas para o usuário final
"""

from __future__ import annotations

from typing import Any

PANORAMA = "prosperfy_vps_panorama"
CONTAINERS = "prosperfy_vps_listar_containers"
PORTS = "prosperfy_vps_verificar_portas"

# Limite de profundidade do unwrap do envelope {success, data}. Alto o
# bastante para o shape real observado no Homolog (success → data → data →
# payload), baixo o bastante para nunca descer estruturas de negócio
# profundas de forma cega.
_MAX_UNWRAP_DEPTH = 4


def _unwrap_payload(value: dict[str, Any]) -> dict[str, Any]:
    """
    Desce o envelope de transporte conhecido de forma LIMITADA e
    determinística.

    O Cognitive/ProsperfySkill retorna por tool um envelope que varia em
    profundidade de `data`:

      DEV (mock):        {success, data: {payload...}}
      Homolog (real):    {success, data: {data: {payload...}}}

    Desce apenas envelopes PUROS — dict cujo conjunto de chaves é exatamente
    {success, data} ou {data} — até encontrar o dict com as chaves de negócio
    (status/host/containers/ports/etc.). NUNCA remove uma chave `data` que
    seja parte legítima do payload final (dict com outras chaves além de um
    envelope puro). Limitado a `_MAX_UNWRAP_DEPTH` para não percorrer
    estruturas de negócio profundas.
    """
    current = value
    depth = 0
    while depth < _MAX_UNWRAP_DEPTH:
        keys = set(current.keys())
        if keys == {"data"} or keys == {"success", "data"}:
            inner = current.get("data")
            if isinstance(inner, dict):
                current = inner
                depth += 1
                continue
        break
    return current


def _tool_payload(raw: dict[str, Any], tool: str) -> dict[str, Any] | None:
    value = raw.get(tool)
    if not isinstance(value, dict):
        return None
    # Envelope de erro da aplicação — tool falhou (fail-closed, não sucesso).
    if value.get("success") is False or value.get("status") == "error":
        return None
    # Descida limitada do envelope success/data (suporta DEV e Homolog real).
    payload = _unwrap_payload(value)
    if payload.get("status") == "error" or payload.get("error"):
        return None
    # Envelope success sem payload interno → não é um resultado válido.
    if "success" in value and not payload:
        return None
    return payload


def _uptime_human(uptime_seconds: Any) -> str:
    try:
        seconds = int(float(uptime_seconds))
    except (TypeError, ValueError):
        return "desconhecido"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    return " ".join(parts) or "menos de 1m"


def build_server_status_view(
    raw: dict[str, Any],
    capability_id: str = "infra.inspect",
) -> dict[str, Any]:
    """
    Constrói a visão consolidada raw → normalized → summary de `infra.inspect`.

    Tools opcionais ausentes ou com erro não derrubam a visão: as seções
    correspondentes ficam omissas no normalized/summary e `degraded=True`
    sinaliza o problema parcial.
    """
    panorama = _tool_payload(raw, PANORAMA)
    containers_raw = _tool_payload(raw, CONTAINERS)
    ports_raw = _tool_payload(raw, PORTS)

    container_list = [
        c for c in containers_raw.get("containers", [])
        if isinstance(c, dict)
    ] if containers_raw else []
    port_mapping: dict[str, Any] = ports_raw.get("ports", {}) if ports_raw else {}

    broken_containers = [
        c for c in container_list
        if str(c.get("status", "")).lower() != "running"
    ]
    open_ports = sorted(
        (str(port) for port, state in port_mapping.items() if str(state).lower() == "open"),
        key=str,
    )
    total_ports = len(port_mapping)
    missing_optional = [
        name for name, payload in (
            (PORTS, ports_raw),
        )
        if payload is None
    ]
    degraded = bool(broken_containers or (total_ports and len(open_ports) < total_ports) or missing_optional)

    normalized: dict[str, Any] = {
        "host": panorama.get("host") if panorama else None,
        "uptime_seconds": panorama.get("uptime_seconds") if panorama else None,
        "uptime_human": _uptime_human(panorama.get("uptime_seconds")) if panorama else None,
        "load_avg": list(panorama.get("load_avg", [])) if panorama else [],
        "containers": [
            {"name": c.get("name"), "status": c.get("status"), "image": c.get("image")}
            for c in container_list
        ],
        "container_count": len(container_list),
        "container_running_count": len(container_list) - len(broken_containers),
        "container_broken": [c.get("name") for c in broken_containers],
        "ports": [
            {"port": str(port), "state": str(state)}
            for port, state in sorted(port_mapping.items(), key=lambda kv: str(kv[0]))
        ],
        "ports_open": open_ports,
        "ports_open_count": len(open_ports),
        "ports_total_count": total_ports,
        "degraded": degraded,
    }

    summary: list[str] = []
    if normalized["host"]:
        uptime = normalized["uptime_human"]
        summary.append(
            f"Servidor {normalized['host']} está online"
            + (f" (uptime {uptime})" if uptime != "desconhecido" else "")
            + "."
        )
    else:
        summary.append("Não foi possível obter o panorama do servidor.")

    if container_list:
        summary.append(
            f"{normalized['container_count']} containers: "
            f"{normalized['container_running_count']} rodando"
            + (f", {len(broken_containers)} com problema." if broken_containers else ".")
        )
    elif containers_raw is None:
        summary.append("Não foi possível listar os containers.")

    if port_mapping:
        if normalized["ports_open_count"] == 0:
            summary.append("Nenhuma porta aberta.")
        else:
            summary.append(
                f"{normalized['ports_open_count']} de {normalized['ports_total_count']} "
                "portas abertas."
            )
    elif ports_raw is None and total_ports == 0:
        summary.append("Verificação de portas não retornou dados.")

    if degraded:
        detail: list[str] = []
        for name in normalized["container_broken"]:
            detail.append(f"container '{name}' fora de running")
        if missing_optional:
            detail.append("tool de portas indisponível")
        summary.append("Atenção: " + "; ".join(detail) + ".")
    else:
        summary.append("Todos os serviços e portas verificados estão OK.")

    return {
        "capability_id": capability_id,
        "raw": raw,
        "normalized": normalized,
        "summary": "\n".join(summary),
    }