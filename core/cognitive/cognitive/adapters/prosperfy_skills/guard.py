"""
adapters/prosperfy_skills/guard.py — Boundary guard para argumentos indo ao ProsperfySkill MCP.

Contexto (Sprint 0.3, ADR-V2-003):
O ProsperfySkillsAdapter (client.py) é o único boundary externo do Cognitive
para o ProsperfySkill MCP. Idealmente o ExecutionOrchestrator + ResourceResolver
resolvem `params.resource` (lógico, ex.: "prosperfy-main") para parâmetros
concretos (host/token/...) ANTES de chegar aqui (ADR-V2-002 §3).

Esta guarda é uma defesa em profundidade *no adapter*, independente de outras
camadas estarem corretamente fiadas:
  1. Bloqueia chaves de argumento que nunca são legítimas para nenhuma tool
     MCP conhecida do catálogo ProsperfySkill (comando/shell arbitrário).
  2. Se 'resource' ainda estiver presente nos argumentos (não resolvido),
     valida que o valor é um identificador lógico (slug), nunca um IP/host
     tentando se passar por resource.

Aplicada tanto no adapter real (client.py) quanto no mock (mock.py), para que
o mesmo contrato de segurança valha em CI (COGNITIVE_LIVE_MCP=0) e em produção
(COGNITIVE_LIVE_MCP=1).
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

# Chaves de argumento que nunca são legítimas para as tools MCP conhecidas do
# ProsperfySkill (catálogo real confirmado: host, token, porta,
# incluir_parados — ver `prosperfy_vps_panorama` / `_listar_containers` /
# `_verificar_portas`). Qualquer uma destas chaves indica uma tentativa de
# passar comando/shell arbitrário do cliente para o adapter.
FORBIDDEN_ARG_KEYS = frozenset({
    "command",
    "cmd",
    "comando",
    "shell",
    "bash",
    "exec",
    "execute",
    "script",
    "sh",
    "powershell",
    "eval",
})

# Resource lógico: slug ASCII minúsculo, dígitos, hífen/underscore.
# Nunca contém pontos (IPv4/hostname) ou dois-pontos (IPv6/porta).
_RESOURCE_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-_]{1,63}$")


class ForbiddenArgumentError(ValueError):
    """Levantado quando `arguments` contém uma chave ou valor não permitido."""


def guard_arguments(tool_name: str, arguments: dict[str, Any]) -> None:
    """
    Valida `arguments` antes de invocar uma tool ProsperfySkill (real ou mock).

    Levanta ForbiddenArgumentError (nunca deixa passar silenciosamente) se:
      - Qualquer chave em FORBIDDEN_ARG_KEYS estiver presente.
      - 'resource' estiver presente com um valor que não é um slug lógico
        válido (ex.: parece IP, hostname, ou contém caracteres de shell).

    Não valida 'host' diretamente — a defesa canônica contra host cru vindo
    do cliente é o ResourceResolver (execution/resource_resolver.py) rodando
    ANTES do adapter. Esta função cobre o caso do 'resource' ainda não
    resolvido chegar até aqui.
    """
    present_forbidden = FORBIDDEN_ARG_KEYS.intersection(arguments.keys())
    if present_forbidden:
        raise ForbiddenArgumentError(
            f"Argumento(s) proibido(s) para tool '{tool_name}': "
            f"{sorted(present_forbidden)}"
        )

    if "resource" in arguments:
        value = arguments["resource"]
        if not isinstance(value, str) or not _is_valid_resource_slug(value):
            raise ForbiddenArgumentError(
                f"'resource' inválido para tool '{tool_name}': deve ser um "
                "identificador lógico tenant-scoped (ex: 'prosperfy-main'), "
                "nunca IP/host/comando."
            )


def _is_valid_resource_slug(value: str) -> bool:
    if not _RESOURCE_SLUG_RE.match(value):
        return False
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return True
    return False
