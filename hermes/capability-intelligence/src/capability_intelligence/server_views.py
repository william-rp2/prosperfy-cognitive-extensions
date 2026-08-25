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
_MAX_UNWRAP_DEPTH = 6

# Chaves que caracterizam um ENVELOPE DE TRANSPORTE (resposta de tool do
# servidor). Um dict é tratado como envelope quando tem uma chave `data` que
# é dict E TODAS as demais chaves estão neste conjunto. Isso evita unwrap
# cego de payload de negócio que tenha um campo `data` legítimo junto de
# chaves de negócio (ex.: {status, name, image, data} de um container).
_ENVELOPE_KEYS = frozenset({"success", "status", "meta", "error"})


def _is_transport_envelope(value: dict[str, Any]) -> bool:
    """Determinístico: é envelope de transporte se tem `data` (dict) e o resto
    das chaves pertencem ao conjunto de envelope conhecido. {status,data,meta,
    error} é envelope; {status,name,image,data} (container) NÃO é."""
    if "data" not in value or not isinstance(value.get("data"), dict):
        return False
    other = set(value.keys()) - {"data"}
    return other <= _ENVELOPE_KEYS


def _unwrap_payload(value: dict[str, Any]) -> dict[str, Any]:
    """
    Desce o envelope de transporte conhecido de forma LIMITADA e
    determinística.

    O Cognitive/ProsperfySkill real retorna por tool um envelope aninhado
    que varia em profundidade e forma:

      DEV (mock):        {success, data: {payload...}}
      Homolog real:      {success, data: {status, data: {data: {payload}},
                                          meta, error}}

    Desce APENAS envelopes de transporte reconhecidos por `_is_transport_envelope`
    (NUNCA unwrap cego de qualquer chave `data`), até o dict que não é mais
    envelope — o payload de negócio. Limitado a `_MAX_UNWRAP_DEPTH`.
    """
    current = value
    depth = 0
    while depth < _MAX_UNWRAP_DEPTH and _is_transport_envelope(current):
        inner = current.get("data")
        if not isinstance(inner, dict):
            break
        current = inner
        depth += 1
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


# ─── Aliases defensivos (contrato REAL do ProsperfySkill primeiro, legado
# DEV/mock como fallback). Sem framework/schema — só normalização de poucos
# campos conhecidos. NUNCA inventa conversão numérica para strings reais
# (ex.: uptime/load_average reais são strings e são preservados como estão)._

def _pick(*values: Any) -> Any:
    """Primeiro valor não-None."""
    for v in values:
        if v is not None:
            return v
    return None


def _container_name(item: dict[str, Any]) -> Any:
    """REAL: Names (lista docker, ex. ['/name']). LEGADO: name (string)."""
    names = item.get("Names")
    if isinstance(names, list):
        for n in names:
            if isinstance(n, str) and n.strip():
                return n.lstrip("/").strip()
    if isinstance(names, str) and names.strip():
        return names.lstrip("/").strip()
    return item.get("name")


def _container_state(item: dict[str, Any]) -> Any:
    """REAL: State (docker, ex. 'running'). LEGADO: status (mock)."""
    return _pick(item.get("State"), item.get("state"), item.get("status"))


def _container_status(item: dict[str, Any]) -> Any:
    """REAL: Status (docker, ex. 'Up 2 hours'/'Exited (0)'). LEGADO: status."""
    return _pick(item.get("Status"), item.get("status"))


def _container_image(item: dict[str, Any]) -> Any:
    """REAL: Image. LEGADO: image."""
    return _pick(item.get("Image"), item.get("image"))


def _container_is_running(item: dict[str, Any]) -> bool:
    state = item.get("State")
    if isinstance(state, str):
        return state.lower() == "running"
    status = item.get("status")
    if isinstance(status, str):
        low = status.lower()
        return low == "running" or low.startswith("up")
    return False


def _normalize_ports(ports_raw: dict[str, Any] | None) -> tuple[list[dict[str, Any]] | None, bool]:
    """
    Normaliza o resultado da tool de portas.

    Contrato LEGADO (mock): mapa {ports: {porta: estado}} → 1 item por porta.
    Contrato REAL (ProsperfySkill): verificação única {porta, sucesso,
    exit_status, stdout, stderr, ...} → 1 item.

    Retorna (lista_normalizada, malformed). malformed=True quando a tool está
    presente mas o payload não é nenhum dos formatos conhecidos → fail-closed
    (não vira sucesso válido silencioso).
    """
    if ports_raw is None:
        return None, False
    mapping = ports_raw.get("ports")
    if isinstance(mapping, dict):
        items = [
            {
                "port": str(port),
                "state": str(state),
                "success": str(state).lower() == "open",
            }
            for port, state in mapping.items()
        ]
        return items, False
    # Verificação única (LEGACY porta/port + REAL port_number/numero/...):
    # o identificador vem SEMPRE de _port_identifier() — nunca str(None).
    # O branch antigo interceptava o payload quando "port" existia com valor
    # None e o número real estava em outra chave → "None" na visão.
    porta = _port_identifier(ports_raw)
    success = ports_raw.get("sucesso", ports_raw.get("success"))
    if porta is not None or success is not None:
        return [{
            "port": str(porta) if porta is not None else "?",
            "state": "open" if success is True else str(ports_raw.get("exit_status") or "closed"),
            "success": success is True,
            "exit_status": ports_raw.get("exit_status"),
        }], False
    return [], True


_PORT_IDENTIFIER_KEYS = (
    "porta", "port", "port_number", "portNo", "port_num", "numero",
    "numero_porta", "port_id", "number", "destination_port", "dst_port",
)


def _port_identifier(item: dict[str, Any]) -> Any:
    """Identificador da porta a partir de chaves conhecidas (LEGACY + REAL)."""
    if not isinstance(item, dict):
        return None
    for key in _PORT_IDENTIFIER_KEYS:
        value = item.get(key)
        if value is not None:
            return value
    return None


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
    port_results, ports_malformed = _normalize_ports(ports_raw)

    broken_containers = [
        c for c in container_list
        if not _container_is_running(c)
    ]
    open_ports = sorted(
        (str(p["port"]) for p in port_results if p.get("success") is True),
        key=str,
    ) if port_results else []
    total_ports = len(port_results) if port_results else 0
    missing_optional = [
        name for name, payload in (
            (PORTS, ports_raw),
        )
        if payload is None
    ]
    # Tool presente mas com payload estruturalmente inválido/incompleto → NÃO
    # é um resultado válido. Sem essas flags, panorama/containers malformed
    # seriam retornados como visão não-degradada (success de status falso).
    panorama_malformed = panorama is not None and not panorama.get("host")
    containers_malformed = (
        containers_raw is not None
        and not isinstance(containers_raw.get("containers"), list)
    )
    degraded = bool(
        broken_containers
        or (total_ports and len(open_ports) < total_ports)
        or missing_optional
        or ports_malformed
        or panorama_malformed
        or containers_malformed
    )

    # Panorama: contrato real (host/uptime/load_average) + legado
    # (uptime_seconds/load_avg). uptime/load_average reais são strings e são
    # preservados sem conversão inventada.
    panorama_host = panorama.get("host") if panorama else None
    uptime_seconds = panorama.get("uptime_seconds") if panorama else None
    uptime_str = panorama.get("uptime") if panorama else None
    load_average = _pick(
        panorama.get("load_avg") if panorama else None,
        panorama.get("load_average") if panorama else None,
    )

    normalized: dict[str, Any] = {
        "host": panorama_host,
        "uptime_seconds": uptime_seconds,
        "uptime": uptime_str,
        "uptime_human": (
            _uptime_human(uptime_seconds)
            if uptime_seconds is not None
            else (uptime_str if uptime_str else None)
        ),
        "load_avg": list(load_average) if isinstance(load_average, (list, tuple)) else load_average,
        "containers": [
            {
                "name": _container_name(c),
                "status": _container_status(c),
                "state": _container_state(c),
                "image": _container_image(c),
                "health_status": _pick(c.get("HealthStatus"), c.get("health_status")),
            }
            for c in container_list
        ],
        "container_count": len(container_list),
        "container_running_count": sum(1 for c in container_list if _container_is_running(c)),
        "container_broken": [_container_name(c) for c in broken_containers],
        "ports": sorted(port_results or [], key=lambda p: str(p["port"])),
        "ports_open": open_ports,
        "ports_open_count": len(open_ports),
        "ports_total_count": total_ports,
        "ports_malformed": ports_malformed,
        "degraded": degraded,
    }

    summary: list[str] = []
    if normalized["host"]:
        uptime = normalized["uptime_human"]
        summary.append(
            f"Servidor {normalized['host']} está online"
            + (f" (uptime {uptime})" if uptime else "")
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

    if port_results:
        if normalized["ports_open_count"] == 0:
            summary.append("Nenhuma porta aberta.")
        else:
            summary.append(
                f"{normalized['ports_open_count']} de {normalized['ports_total_count']} "
                "portas abertas."
            )
    elif ports_raw is None:
        summary.append("Verificação de portas não retornou dados.")

    if degraded:
        detail: list[str] = []
        for name in normalized["container_broken"]:
            detail.append(f"container '{name}' fora de running")
        if missing_optional:
            detail.append("tool de portas indisponível")
        if ports_malformed:
            detail.append("payload de portas malformado")
        summary.append("Atenção: " + "; ".join(detail) + ".")
    else:
        summary.append("Todos os serviços e portas verificados estão OK.")

    return {
        "capability_id": capability_id,
        "raw": raw,
        "normalized": normalized,
        "summary": "\n".join(summary),
    }


def build_servidores_view(
    resource_views: list[dict[str, Any]],
    failures: list[dict[str, Any]] | None = None,
    capability_id: str = "infra.inspect",
) -> dict[str, Any]:
    """Consolida a visão multi-servidor (Sprint 0.6 FASE 4).

    Transforma N visões individuais (build_server_status_view) + falhas por
    resource em uma visão única determinística — SEM LLM.

    Partial failure (fail-closed por resource): um resource com erro não
    vira falso OK; é reportado como ERRO e NÃO impede mostrar os demais
    resultados válidos.

    Formato do summary (contrato aprovado):
      Servidores — 3
      Prosperfy — OK
        <linhas da visão do resource>
      ...
      Resumo: 2 OK · 1 DEGRADED [· 1 ERRO]
    """
    failures = failures or []
    ok = [v for v in resource_views if not v["normalized"].get("degraded")]
    degraded = [v for v in resource_views if v["normalized"].get("degraded")]

    resources_norm = [
        {
            "resource_key": v.get("resource_key"),
            "host": v["normalized"].get("host"),
            "degraded": bool(v["normalized"].get("degraded")),
            "container_count": v["normalized"].get("container_count"),
            "ports_open_count": v["normalized"].get("ports_open_count"),
        }
        for v in resource_views
    ]

    summary: list[str] = [f"Servidores — {len(resource_views) + len(failures)}"]
    for v in resource_views:
        norm = v["normalized"]
        host = norm.get("host") or v.get("resource_key") or "?"
        state = "DEGRADED" if norm.get("degraded") else "OK"
        summary.append(f"{host} — {state}")
        for line in v["summary"].split("\n"):
            if line.startswith("Servidor "):
                # A linha de status online vira o header do resource (dedup)
                continue
            summary.append("  " + line)
    for f in failures:
        # Friendly name quando disponível (host do panorama no sucesso;
        # display_name do metadata quando a Cognitive expuser). Nunca expor
        # o resource_key cru se existir nome de exibição/canônico.
        display = (
            f.get("display_name")
            or f.get("host")
            or f.get("resource_key")
            or "?"
        )
        summary.append(f"{display} — ERRO")
        summary.append(f"  {f['error']}")

    tail = f"Resumo: {len(ok)} OK · {len(degraded)} DEGRADED"
    if failures:
        tail += f" · {len(failures)} ERRO"
    summary.append(tail)

    return {
        "capability_id": capability_id,
        "normalized": {
            "resources": resources_norm,
            "failures": failures,
            "ok_count": len(ok),
            "degraded_count": len(degraded),
            "failure_count": len(failures),
        },
        "summary": "\n".join(summary),
    }