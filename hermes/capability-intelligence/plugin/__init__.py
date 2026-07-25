"""
Capability Intelligence — Hermes Connector Plugin.

Este plugin conecta a extensão Capability Intelligence ao Hermes Agent.
O código-fonte oficial está em prosperfy-cognitive-extensions/hermes/capability-intelligence/.
~/.hermes/plugins/ é apenas o diretório de instalação/runtime.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from capability_intelligence import __version__ as ci_version
from capability_intelligence.pipeline import Pipeline
from capability_intelligence.feedback_store import FeedbackStore
from capability_intelligence.gap_proposal import GapProposalStore
from capability_intelligence.models import Domain
from capability_intelligence.executor import Executor
from capability_intelligence.negotiator import Negotiator
from capability_intelligence.interpreter import Interpreter
from capability_intelligence.policy_engine import (
    PolicyEngine,
    policy_environment_allowed,
    policy_requires_approval,
)
from capability_intelligence.resolver import Resolver
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
"""


def _handle_slash(raw: str) -> Optional[str]:
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
        intent = argv[1]
        domain = Domain.OTHER
        context = {}
        if len(argv) >= 3:
            try:
                domain = Domain(argv[2])
            except ValueError:
                domain = Domain.OTHER
        if len(argv) >= 4:
            try:
                context = json.loads(argv[3])
            except json.JSONDecodeError:
                pass
        return (
            f"🧠 Pipeline: {intent} [{domain.value}]\n"
            f"  Contexto: {json.dumps(context, ensure_ascii=False)}\n"
            f"✅ CI v{ci_version} instalado."
        )
    return f"Subcomando desconhecido: {sub}\n\n{_HELP}"


def register(ctx) -> None:
    ctx.register_command(
        "capability",
        handler=_handle_slash,
        description="Capability Intelligence — consome Capabilities da plataforma Prosperfy Skills.",
    )
    logger.info("Capability Intelligence plugin v%s registrado", ci_version)