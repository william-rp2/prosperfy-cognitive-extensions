"""
browser_tools.py — Browser Harness V1 (Track BH).

Tool Hermes NARROW que fala com o Cognitive (capabilities browser.*),
preservando authorization/policy/audit/SecretBroker do caminho canônico.
NUNCA abre navegador nem toca CDP diretamente — mesmo contrato de
hermes/p0-supabase-ops/supabase_ops_tools.py.

  User → Hermes (rota BROWSER) → browser → CognitiveApiAdapter → Cognitive
  → browser.* → BrowserAdapter → Browser Worker isolado → browser-harness/CDP
  → Chrome dedicado → site → dados → LLM fraseia.

Só registrado no toolset "browser_harness". NORMAL_CHAT_TOOLS continua 0:
estas tools só entram no schema do turno quando capability_router.py resolve
a rota BROWSER (ver _ROUTE_TOOLSETS).

Decision gate (doc 00 §4.2) NÃO é decidido aqui por keyword: quem escolhe
entre fetch e navegador é browser.read, dentro do Cognitive, onde existe a
evidência real da página (pública/estática → fetch; JS/login/bot-protection
→ navegador).

Limites duros que esta tool NÃO pode contornar:
  - browser.act e browser.account têm default_policy=deny no Cognitive.
    Sem grant explícito o DENY chega como erro, e isso é o comportamento
    correto.
  - MFA, CAPTCHA, verificação por e-mail, pagamento e termos atípicos voltam
    do worker como `blocked_reason` com `submitted: false`. Isso é
    HUMAN_STEP_REQUIRED, não falha da capability — a tool repassa o dado
    íntegro em vez de tentar contornar.
  - Secrets circulam por REFERÊNCIA (secret_ref). O valor nunca passa por
    aqui, nunca entra em log e nunca vai para o LLM.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from tools.registry import registry, tool_error

BROWSER_SCHEMA = {
    "name": "browser",
    "description": (
        "Le paginas web e interage com formularios/cadastros atraves de um Browser "
        "Worker isolado, com autorizacao do tenant. operation=read le uma ou mais URLs "
        "e resume citando a origem (usa fetch quando a pagina e publica/estatica e "
        "navegador so quando a pagina exige JS, login ou tem bot-protection). "
        "operation=act preenche formulario. operation=create_account cria conta "
        "gratuita. act e create_account exigem grant explicito e param sozinhas em "
        "MFA/CAPTCHA/pagamento, devolvendo blocked_reason sem submeter."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["read", "act", "create_account"],
                "description": (
                    "read = ler/resumir URLs (usa urls e task); "
                    "act = preencher/navegar formulario (usa url, action, fields, submit); "
                    "create_account = criar conta gratuita (usa url, fields)."
                ),
            },
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "URLs a ler. Obrigatorio em operation=read. Aceita varias.",
            },
            "task": {
                "type": "string",
                "description": "O que extrair/resumir das URLs. Opcional em operation=read.",
            },
            "url": {
                "type": "string",
                "description": "URL alvo. Obrigatorio em act e create_account.",
            },
            "action": {
                "type": "string",
                "description": "Descricao da interacao pretendida. Obrigatorio em act.",
            },
            "fields": {
                "type": "object",
                "description": (
                    "Campos do formulario. Para dado sensivel use REFERENCIA de secret "
                    "(ex.: {\"senha\": {\"secret_ref\": \"alias\"}}), nunca o valor em claro."
                ),
            },
            "submit": {
                "type": "boolean",
                "description": "Se true, submete o formulario. Default false (so preenche).",
            },
            "accept_standard_terms": {
                "type": "boolean",
                "description": (
                    "Aceita termos padrao indispensaveis para criar a conta. Termos "
                    "atipicos ou com compromisso financeiro sempre param para confirmacao."
                ),
            },
            "session_id": {
                "type": "string",
                "description": "Reutiliza a sessao isolada de uma chamada anterior do mesmo job.",
            },
        },
        "required": ["operation"],
    },
}

# operation -> (capability_id, chaves aceitas, chaves obrigatorias)
_OPS: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "read": ("browser.read", ("urls", "task", "session_id"), ("urls",)),
    "act": (
        "browser.act",
        ("url", "action", "fields", "submit", "session_id"),
        ("url", "action", "fields"),
    ),
    "create_account": (
        "browser.account",
        ("url", "fields", "accept_standard_terms", "plan"),
        ("url", "fields"),
    ),
}


def _call(capability_id: str, params: dict[str, Any]) -> dict:
    from capability_intelligence.browser_service import BrowserService

    return asyncio.run(BrowserService.from_env().call(capability_id, params))


def browser(operation: str = "read", **kwargs: Any) -> str:
    """Resolve operation -> monta params -> chama a capability browser.*.

    Retorna JSON string (contrato do registry: handler devolve str, nunca dict).
    Fail-closed: qualquer excecao vira tool_error, nunca sucesso fabricado.

    `blocked_reason` no retorno NAO e erro: significa que o worker parou antes
    de submeter porque encontrou MFA, CAPTCHA, verificacao por e-mail,
    pagamento ou termo atipico. E repassado como HUMAN_STEP_REQUIRED para o
    LLM explicar ao usuario o que falta — nunca contornado.
    """
    spec = _OPS.get(operation)
    if spec is None:
        return tool_error(
            "operation desconhecida: " + str(operation),
            success=False,
            operation=operation,
        )
    capability_id, aceitas, obrigatorias = spec

    params = {k: kwargs[k] for k in aceitas if kwargs.get(k) not in (None, "", [], {})}
    faltando = [k for k in obrigatorias if k not in params]
    if faltando:
        return tool_error(
            "parametro(s) obrigatorio(s) ausente(s) para operation="
            + str(operation)
            + ": "
            + ", ".join(faltando),
            success=False,
            operation=operation,
        )

    try:
        data = _call(capability_id, params)
    except Exception as exc:  # noqa: BLE001 — fail-closed; nunca mascarar
        return tool_error(str(exc)[:400], success=False, operation=operation)

    bloqueio = data.get("blocked_reason") if isinstance(data, dict) else None
    return json.dumps(
        {
            "operation": operation,
            "capability": capability_id,
            "ok": True,
            "human_step_required": bool(bloqueio),
            "blocked_reason": bloqueio,
            "data": data,
        },
        ensure_ascii=False,
        default=str,
    )


def check_browser_requirements() -> bool:
    """Disponivel quando o Hermes roda em gateway/mensageria ou interativo
    (mesmo gate de supabase_ops_tools.py e infra_read_tools.py)."""
    from utils import env_var_enabled

    return (
        env_var_enabled("HERMES_INTERACTIVE")
        or env_var_enabled("HERMES_GATEWAY_SESSION")
        or env_var_enabled("HERMES_EXEC_ASK")
    )


# --- Registry ---
registry.register(
    name="browser",
    toolset="browser_harness",
    schema=BROWSER_SCHEMA,
    handler=lambda args, **kw: browser(
        operation=str(args.get("operation", "read")),
        urls=args.get("urls"),
        task=args.get("task"),
        url=args.get("url"),
        action=args.get("action"),
        fields=args.get("fields"),
        submit=args.get("submit"),
        accept_standard_terms=args.get("accept_standard_terms"),
        session_id=args.get("session_id"),
    ),
    check_fn=check_browser_requirements,
)
