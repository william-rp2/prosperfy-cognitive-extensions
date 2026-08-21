"""
Capability Intelligence — Hermes Connector Plugin.

Este plugin conecta a extensão Capability Intelligence ao Hermes Agent.
O código-fonte oficial está em prosperfy-cognitive-extensions/hermes/capability-intelligence/.
~/.hermes/plugins/ é apenas o diretório de instalação/runtime.
"""

from __future__ import annotations

import logging
import os
import shlex
from typing import Any, Optional

from capability_intelligence import __version__ as ci_version
from capability_intelligence.pipeline import Pipeline
from capability_intelligence.feedback_store import FeedbackStore
from capability_intelligence.gap_proposal import GapProposalStore
from capability_intelligence.executor import Executor
from capability_intelligence.negotiator import Negotiator
from capability_intelligence.interpreter import Interpreter
from capability_intelligence.policy_engine import (
    PolicyEngine,
    policy_environment_allowed,
    policy_requires_approval,
)
from capability_intelligence.resolver import Resolver
from capability_intelligence.infra_service import InfraService
from capability_intelligence.transport.adapters.mcp_adapter import MCPAdapter
from capability_intelligence.models import (
    AuthorizationRequest,
    AuthorizationResult,
    CapabilityResult,
    ExecutionReference,
    ExecutionRequest,
    IntentQuery,
    CatalogResult,
    StatusResult,
)

logger = logging.getLogger(__name__)


_pipeline: Optional[Pipeline] = None


def _get_pipeline() -> Pipeline:
    global _pipeline
    if _pipeline is not None:
        return _pipeline
    transport = MCPAdapter(api_key=os.environ.get("MCP_PROSPERFYSKILLS_API_KEY", ""))
    _pipeline = Pipeline(
        resolver=Resolver(catalog=transport),
        negotiator=Negotiator(),
        policy_engine=PolicyEngine(policies=[
            policy_environment_allowed,
            policy_requires_approval,
        ]),
        executor=Executor(authorization=transport, execution=transport),
        interpreter=Interpreter(),
        feedback_store=FeedbackStore(),
        gap_store=GapProposalStore(),
    )
    return _pipeline


_HELP = """\
/capability — Pipeline Capability Intelligence v""" + ci_version + """

Subcomandos:
  /capability status              Estado do módulo
  /capability gaps                Lacunas detectadas
  /capability feedback <id>       Histórico de uma Capability
  /capability run <intent> <domain> [context JSON]

/servidores — Vertical Infra/Servidores via Cognitive (multi-resource)
  Responde "Como estão meus servidores?" (status consolidado de TODOS os
  servidores autorizados da identidade) delegando ao Cognitive: Hermes →
  Cognitive → descoberta de resources → infra.inspect por resource →
  ProsperfySkill → VPS. Determinístico, sem LLM.
"""


def _handle_slash(raw: str) -> Optional[str]:
    try:
        argv = shlex.split(raw.strip())
    except ValueError:
        argv = raw.strip().split(maxsplit=2)
    if not argv or argv[0] in {"help", "-h", "--help"}:
        return _HELP
    sub = argv[0]
    pipe = _get_pipeline()
    if sub == "status":
        fb = pipe.feedback_store
        gaps = pipe.gap_store
        return (
            f"🔧 Capability Intelligence v{ci_version}\n"
            f"  Feedbacks: {len(fb._feedbacks)}\n"
            f"  Lacunas: {len(gaps.list_gaps())}\n"
            f"  Transport: MCP (skills.prosperfy.com.br)"
        )
    if sub == "gaps":
        gaps = pipe.gap_store.list_gaps()
        if not gaps:
            return "Nenhuma lacuna registrada."
        return "📋 Lacunas:\n" + "\n".join(
            f"  • [{g.domain}] {g.intent}" for g in gaps
        )
    if sub == "feedback":
        if len(argv) < 2:
            return "Uso: /capability feedback <capability_id>"
        cid = argv[1]
        fb = pipe.feedback_store.get_history(cid)
        if not fb:
            return f"Sem feedback para '{cid}'."
        ok = sum(1 for f in fb if f.success)
        return (
            f"📊 {cid}: {len(fb)} execuções, "
            f"{ok}/{len(fb)} sucesso ({ok/len(fb)*100:.0f}%)"
        )
    if sub == "run":
        if len(argv) < 2:
            return "Uso: /capability run <intent> <domain> [context JSON]"
        # Fail-closed (Sprint 0.7.1): o pipeline legado executa via MCP DIRETO
        # sem authorization governada. O subcomando NÃO executa nada — retorna
        # negação explícita até a migração governada para Cognitive.
        return (
            "🧠 /capability run indisponível (fail-closed).\n"
            "  Execução direta via MCP legado desabilitada — "
            "use o Cognitive (ex.: /servidores) ou aguarde a migração governada."
        )
    return f"Subcomando desconhecido: {sub}\n\n{_HELP}"


async def _handle_servidores(raw: str) -> str:
    """'Como estão meus servidores?' — caminho NOVO via Cognitive (multi-resource).

    Sprint 0.6 FASE 4: descobre via Cognitive TODOS os resources VPS
    autorizados da identidade (GET /v1/resources) e executa infra.inspect por
    resource (cada um passa pela autorização normal). Consolidação
    determinística em build_servidores_view — SEM LLM. Hermes não possui
    lista hardcoded de servidores.

    Assíncrono de propósito: o dispatcher do gateway (WhatsApp/web) roda no
    event loop e AWAITA handlers que retornam coroutine — `asyncio.run()`
    dentro de um handler síncrono explodiria com "cannot be called from a
    running event loop". Em contextos síncronos (CLI/TUI) o runtime resolve
    coroutines via resolve_plugin_command_result().
    """
    try:
        service = InfraService.from_env()
        view = await service.servidores_status()
    except Exception as exc:  # noqa: BLE001 — plugin surface: reporta falha fechada
        logger.error("servidores via Cognitive falhou: %s", exc)
        return f"❌ Não foi possível consultar os servidores via Cognitive: {exc}"
    norm = view["normalized"]
    if norm.get("failure_count") and not norm.get("resources"):
        return (
            f"🖥️ Servidores — erro na descoberta/execução\n"
            f"  {view['summary']}"
        )
    header = (
        f"🖥️ Servidores [{len(norm.get('resources') or [])}"
        + (f" · {norm['failure_count']} erro(s)" if norm.get("failure_count") else "")
        + f"]"
        f" — {'ATENÇÃO' if norm.get('degraded_count') or norm.get('failure_count') else 'OK'}\n"
    )
    return header + view["summary"]


def register(ctx) -> None:
    ctx.register_command(
        "capability",
        handler=_handle_slash,
        description="Capability Intelligence — consome Capabilities da plataforma Prosperfy Skills.",
    )
    ctx.register_command(
        "servidores",
        handler=_handle_servidores,
        description="Vertical Infra/Servidores via Cognitive — 'Como estão meus servidores?'.",
    )
    logger.info("Capability Intelligence plugin v%s registrado", ci_version)