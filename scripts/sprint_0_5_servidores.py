#!/usr/bin/env python3
"""
Sprint 0.5 — Demo do vertical slice "Como estão meus servidores?".

Client fino do Hermes (CognitiveApiAdapter) contra o Cognitive Gateway:
consulta status → autoriza → executa `infra.inspect` (panorama + containers
+ portas via ProsperfySkill MCP) → consolida em raw/normalized/summary.

Uso (dev — gateway in-memory local com MockSkillsAdapter):

    # suba o gateway dev primeiro (ver COGNITIVE-DEPLOY-READINESS.md) OU
    # use os testes: este modo fala HTTP para http://127.0.0.1:8000
    python scripts/sprint_0_5_servidores.py --environment dev

Uso (homolog — API real, MCP real, READ-ONLY):

    export COGNITIVE_LIVE_MCP=1
    export COGNITIVE_GATEWAY_CREDENTIAL=...   # service identity provisionada
    export COGNITIVE_TENANT_ID=<uuid>
    export COGNITIVE_ACTOR_ID=...
    python scripts/sprint_0_5_servidores.py --environment homolog \
        --gateway-url https://api-cognitive-homolog.prosperfy.com.br

Segurança (fail-closed, espelha sprint_0_3_live_mcp_gate.py):
  - `--environment homolog` é obrigatório ser EXPLÍCITO; não existe default
    para a API real.
  - environment=homolog exige COGNITIVE_LIVE_MCP=1 no ambiente E uma URL de
    gateway com o host homolog allowlistado — qualquer divergência recusa
    antes de qualquer chamada HTTP.
  - Nunca imprime a credencial; erros de transporte nunca incluem corpo de
    resposta, headers ou a credencial.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HERMES_SRC = REPO_ROOT / "hermes" / "capability-intelligence" / "src"
sys.path.insert(0, str(HERMES_SRC))

from capability_intelligence.models import (  # noqa: E402
    AuthorizationRequest,
    ExecutionRequest,
)
from capability_intelligence.server_views import build_server_status_view  # noqa: E402
from capability_intelligence.transport.cognitive_api_adapter import (  # noqa: E402
    CognitiveApiAdapter,
)

HOMOLOG_ALLOWLIST_HOSTS = ("api-cognitive-homolog.prosperfy.com.br",)
DEV_DEFAULT_URL = "http://127.0.0.1:8000"
DEV_DEFAULT_CREDENTIAL = "dev-secret"
DEV_DEFAULT_TENANT = "prosperfy"
DEV_DEFAULT_ACTOR = "william"
DEFAULT_RESOURCE = "prosperfy-main"
DEFAULT_CAPABILITY = "infra.inspect"


def _require_live_mcp_for_homolog() -> None:
    if os.getenv("COGNITIVE_LIVE_MCP", "0") != "1":
        raise SystemExit("GATE_REFUSED: environment homolog exige COGNITIVE_LIVE_MCP=1")


def _require_homolog_gateway_url(url: str) -> str:
    normalized = url.rstrip("/")
    host = normalized.split("://", 1)[-1].split("/", 1)[0].lower()
    if not normalized.startswith("https://") or host not in HOMOLOG_ALLOWLIST_HOSTS:
        raise SystemExit(
            "GATE_REFUSED: URL de gateway não homolog allowlistada — "
            "use https://api-cognitive-homolog.prosperfy.com.br."
        )
    return normalized


def _resolve_config(args: argparse.Namespace) -> dict:
    env = args.environment
    if env == "homolog":
        _require_live_mcp_for_homolog()
        url = _require_homolog_gateway_url(
            args.gateway_url or os.getenv("COGNITIVE_GATEWAY_URL", "")
        )
        if not (url or os.getenv("COGNITIVE_GATEWAY_URL")):
            raise SystemExit("GATE_REFUSED: --gateway-url ou COGNITIVE_GATEWAY_URL obrigatório em homolog")
        return {
            "base_url": url,
            "credential": args.credential or os.getenv("COGNITIVE_GATEWAY_CREDENTIAL", ""),
            "tenant_id": args.tenant_id or os.getenv("COGNITIVE_TENANT_ID", ""),
            "actor_id": args.actor_id or os.getenv("COGNITIVE_ACTOR_ID", ""),
        }
    # env == "dev": apenas valores de dev locais, nunca a API real.
    return {
        "base_url": args.gateway_url or DEV_DEFAULT_URL,
        "credential": os.getenv("COGNITIVE_GATEWAY_CREDENTIAL", DEV_DEFAULT_CREDENTIAL),
        "tenant_id": os.getenv("COGNITIVE_TENANT_ID", DEV_DEFAULT_TENANT),
        "actor_id": os.getenv("COGNITIVE_ACTOR_ID", DEV_DEFAULT_ACTOR),
    }


async def _run(args: argparse.Namespace, adapter: CognitiveApiAdapter) -> dict:
    auth = await adapter.authorize(AuthorizationRequest(capability_id=args.capability))
    if not auth.authorized:
        print(f"AUTHORIZE_RESULT=NOT_AUTHORIZED reason={auth.reason}")
        raise SystemExit(f"Falha na autorização: {auth.reason}")

    result = await adapter.get_result(
        await adapter.execute(ExecutionRequest(
            capability_id=args.capability,
            params={"resource": args.resource},
        ))
    )
    if not result.success:
        print(f"EXECUTE_RESULT=FAILED error={result.error}")
        raise SystemExit(f"Execução falhou: {result.error}")

    view = build_server_status_view(result.data or {})
    if args.correlation_id_out:
        Path(args.correlation_id_out).write_text(result.metadata.execution_ref.ref, encoding="utf-8")
    return view


def main() -> int:
    parser = argparse.ArgumentParser(description="Demo do vertical slice 'Como estão meus servidores?'")
    parser.add_argument(
        "--environment", choices=["dev", "homolog"], required=True,
        help="Ambiente-alvo. 'homolog' é uma declaração explícita de risco.",
    )
    parser.add_argument("--gateway-url", default="", help="Base URL da Cognitive API.")
    parser.add_argument("--credential", default="", help="Service identity credential (nunca logada).")
    parser.add_argument("--tenant-id", default="", help="X-Tenant-Id (ADR-V2-002).")
    parser.add_argument("--actor-id", default="", help="X-Actor-Id (ADR-V2-002).")
    parser.add_argument("--resource", default=DEFAULT_RESOURCE, help="Resource lógico tenant-scoped.")
    parser.add_argument("--capability", default=DEFAULT_CAPABILITY, help="Capability a executar.")
    parser.add_argument("--correlation-id-out", default="", help="Arquivo p/ gravar o correlation id.")
    parser.add_argument("--raw", action="store_true", help="Incluir o payload raw no output.")
    args = parser.parse_args()

    cfg = _resolve_config(args)
    adapter = CognitiveApiAdapter(**cfg)

    try:
        view = asyncio.run(_run(args, adapter))
    except Exception as exc:  # noqa: BLE001 — demo CLI: mostra erro sanatizado e sai 1
        print(f"DEMO_RESULT=ERROR {type(exc).__name__}: {exc}")
        return 1

    print("=== normalized ===")
    print(json.dumps(view["normalized"], ensure_ascii=False, indent=2, sort_keys=True))
    print("=== summary ===")
    print(view["summary"])
    if args.raw:
        print("=== raw ===")
        print(json.dumps(view["raw"], ensure_ascii=False, indent=2, sort_keys=True))
    print("DEMO_RESULT=OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())