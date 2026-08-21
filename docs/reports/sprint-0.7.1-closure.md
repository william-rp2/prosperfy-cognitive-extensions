# Sprint 0.7.1 — Hermes Slim Closure + Security Gate

## Precheck

```
TARGET=Prosperfy Cognitive Homolog · TARGET_REF=esvjfkknrzzziafovwrv (OBSERVED sprints anteriores)
PRODUCTION_TARGET_NOT_USED=YES · PRODUCTION_REF=wioorhtdwnfujkrynxij nunca acessado
AUDIT_COMMIT_FOUND=2b8e3db (dev/sprint-0.7) · AUDIT_REPORT_FOUND=YES
CURRENT_BRANCH=dev/sprint-0.7.1 · CURRENT_HEAD=worktree clean
COGNITIVE_LIVE_MCP=1 (OBSERVED em sprint 0.6; não re-medido)
```

> **Bloqueio de acesso nesta sessão (transparência):** sem MCP de VPS e sem SSH
> ao host srv1631152 → objetivos que exigem o servidor/Homolog (B, C, D, E)
> ficaram BLOCKED. Evidência: ssh negado (publickey), MCP VPS não anexado,
> endpoint MCP skills.prosperfy.com.br/mcp não autentica com o token local
> (400/401; requer MCP_PROSPERFYSKILLS_API_KEY que vive só no host).
> Nada foi inventado nem estimado como fato.

## FASE A — /capability security analysis (CODE_CONFIRMED, local)

```
CAPABILITY_USER_FACING=YES · CAPABILITY_RUNTIME_ACTIVE=YES (registrado/enabled)
USER_CAN_SELECT_TOOL=NO (intent/domain parseados mas NUNCA usados p/ chamar MCP)
USER_CAN_CONTROL_ARGUMENTS=NO (context parseado mas nunca passado ao MCP)
READ_TOOLS_REACHABLE=NO · WRITE_TOOLS_REACHABLE=NO · ARBITRARY_COMMAND_TOOL_REACHABLE=NO
AUTHORIZATION_BEFORE_MCP=NO (mas MCP nunca alcançado pelo path user-facing)
COGNITIVE_BOUNDARY_USED=NO (/capability usa transport MCP direto)
BYPASS_EXPLOITABLE=NO hoje (run é stub; _handle_slash nunca chama pipe.run)
EVIDENCE=CODE_CONFIRMED: plugin _handle_slash (status/gaps/feedback in-memory;
  "run" retorna mensagem sem executar) + Executor.run (único que chama
  authorize) nunca invocado via /capability.
AUTH_BYPASS_CONFIRMED=YES (latente: MCPAdapter.authorize era no-op authorized=True)
```

## SECURITY DECISION — contenção mínima aplicada

Sem redesign, sem tocar authorize de outros adapters, sem migração:

1. `MCPAdapter.authorize` → **FAIL-CLOSED** (`authorized=False` + reason).
   - Não quebra consumidores: único uso real é `plugin._get_pipeline` (nunca
     chama authorize); `test_fase_i` (único teste que usa) só verifica o tipo
     de `PipelineResult`; `/servidores` usa CognitiveApiAdapter (não MCPAdapter).
2. `/capability run` → **fail-closed explícito** (não executa, não exibe
   "✅ instalado").
3. Imports mortos (`json`, `Domain`) removidos do plugin.

Negativos provados (tests/test_sprint_071_capability_security.py, 6):

```
UNAUTHORIZED_CAPABILITY_MCP_CALL=DENIED
CAPABILITY_FAIL_CLOSED=PASS
SERVIDORES_STILL_WORKS=PASS (suíte 0.5/0.6 intacta)
SHARED_MCPADAPTER_CONSUMERS_REGRESSION=PASS
NO_REAL_WRITE_EXECUTED=YES · NO_SHELL_EXECUTED=YES
```

Regressão Hermes: **363 passed / 1 skipped** (pré-existente).

## STATUS_116 (get_status hardcode)

```
STATUS_116_USER_FACING=NO (get_status usado só em telemetry/teste do pipeline legado)
STATUS_116_FUNCTIONAL_IMPACT=baixo · STATUS_116_SECURITY_IMPACT=nenhum
STATUS_116_FIXED=NO · STATUS_116_DEFERRED=YES (correção real exige consulta ao MCP; fora do escopo mínimo)
```

## FASE B–E — BLOCKED (sem acesso ao host/Homolog nesta sessão)

```
FASE B (server identifiers ProsperfySkill)     → BLOCKED
FASE C (reconfirmar gap + recursos)            → BLOCKED
FASE D (register 3 resources Homolog)          → BLOCKED
FASE 13/14 (all-servers E2E + LLM regression)  → BLOCKED (execução)
FASE 15/16 (live token/context measurement)    → BLOCKED

BLOCKER=Sem MCP VPS, sem SSH, sem MCP_PROSPERFYSKILLS_API_KEY local
EVIDENCE=ssh will@177.7.50.182/100.88.23.15 → Permission denied (publickey);
  MCP skills.prosperfy.com.br/mcp com token local → 400/401 (require client key);
  ferramentas MCP de VPS não anexadas nesta sessão.
SAFE_NEXT_STEP=Restaurar acesso (MCP VPS ou SSH + chave MCP) e rodar FASE B–E;
  ou fornecer MCP_PROSPERFYSKILLS_API_KEY para inventário read-only via MCP.
```

Achados OBSERVED (sprints anteriores, para o report — não re-medidos):
```
PROSPERFYSKILL_SERVERS=4 (Prosperfy, Black, Hostinger One, Manager1)
COGNITIVE_INFRA_RESOURCES=1 (prosperfy-vps-homolog → host Prosperfy)
AUTHORIZED_INFRA_RESOURCES=1 · MISSING_INFRA_RESOURCES=3 (candidatos; identifiers a confirmar em FASE B)
```

## Final

```
SPRINT071_CHECKPOINT=<após push>

AUTH_BYPASS_CONFIRMED=YES (latente) · AUTH_BYPASS_CONTAINED=YES
CAPABILITY_FAIL_CLOSED_OR_GOVERNED=YES
CAPABILITY_USER_CAN_SELECT_TOOL=NO · WRITE_TOOLS_REACHABLE_BEFORE_FIX=NO · AFTER_FIX=NO
STATUS_116_FIXED=NO · STATUS_116_DEFERRED=YES

PROSPERFYSKILL_SERVERS=4 (OBSERVED prévio) · SERVER_IDENTITIES_CONFIRMED=BLOCKED
COGNITIVE_INFRA_RESOURCES=1 (prévio) · AUTHORIZED=1 · MISSING=3 (identities a confirmar)
NEW_RESOURCES_REGISTERED=0
AUTHORIZED_RESOURCES_FOUND=BLOCKED · EXECUTED=BLOCKED
WHATSAPP_ALL_SERVERS=BLOCKED · WEB_ALL_SERVERS=BLOCKED

HERMES_LLM_PROVIDER_CALLS=0 (re-afirmado p/ /servidores; PROVEN 0.6) ·
  INPUT=0 · OUTPUT=0 · COST=0 · COGNITIVE_LLM_CALLS=0
BASE_PROMPT_TOKENS=UNKNOWN · AUTO_INJECTED_CONTEXT_TOKENS=UNKNOWN · TOOL_SCHEMA_TOKENS=UNKNOWN
COMMANDS_SENT_TO_LLM=UNKNOWN · TOOLS_SENT_TO_LLM=UNKNOWN

NEW_DB_TABLES=0 · NEW_MIGRATIONS=0 · WRITE_CAPABILITIES_CREATED=0 · INFRA_WRITE_ACTIONS_EXECUTED=0
PRODUCTION_UNTOUCHED=YES · SECRET_EXPOSED=NO · MASTER_UNTOUCHED=YES · WORKTREE_CLEAN=YES

INFRA_CORE=PASS · INFRA_MULTI_RESOURCE_ENGINE=PASS · INFRA_LLM_ZERO_COST=PROVEN (0.6; não re-medido 4-resource — BLOCKED)
INFRA_ALL_SERVERS_VISIBILITY=PENDING · INFRA_OPERATIONS=PENDING

SPRINT_0_7_1_FINAL_GATE=PARTIAL (security containment PASS · FASE B–E BLOCKED por acesso)
RECOMMENDED_NEXT_ACTION=Restaurar acesso ao host (MCP VPS / SSH + MCP key) e executar
  FASE B–E (descobrir identifiers, registrar 3 resources, all-servers E2E, token/context live).
```