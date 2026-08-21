# Sprint 0.7 — Hermes Slim Audit + Infra Gap Map

AUDIT-FIRST · READ-ONLY · SEM implementação · SEM restart · SEM mutação.

## 0. Contexto / estado autorizado

Baseline comprovada (medição real, sprint 0.6):

```
HERMES_LLM_PROVIDER_CALLS=0 · INPUT=0 · OUTPUT=0 · COST=0
COGNITIVE_LLM_CALLS=0 · MCP_CALLS=3_PER_RESOURCE
INFRA_CORE=PASS · INFRA_MULTI_RESOURCE_ENGINE=PASS · INFRA_LLM_ZERO_COST=PROVEN
```

## 1. FASE 0 — Precheck

```
TARGET=Prosperfy Cognitive Homolog · TARGET_REF=esvjfkknrzzziafovwrv (OBSERVED)
PRODUCTION_TARGET_NOT_USED=YES (wioorhtdwnfujkrynxij nunca acessado)
COGNITIVE_CHECKPOINT_FOUND=8fab050da9ffc6b9f74a55c10023d66f35c6262f == EXPECTED (CODE_CONFIRMED, git)
BRANCH=dev/sprint-0.6 → dev/sprint-0.7 (audit) · WORKTREE_CLEAN=YES · MASTER_UNTOUCHED=YES
HERMES_RUNTIME_FOUND=~/.hermes (OBSERVED sprints anteriores)
HERMES_AGENT_FOUND=~/.hermes/hermes-agent (OBSERVED)
COGNITIVE_REPO_FOUND=repo local + checkout gate-0.3 (API homolog) (OBSERVED)
```

> **LIMITAÇÃO DE OBSERVAÇÃO (transparência §7):** nesta sessão não há MCP de
> VPS nem SSH ao host srv1631152 → valores "ao vivo" do runtime não puderam ser
> re-medidos agora. Onde usamos observação prévia desta conversa, marcamos
> `OBSERVED (<timestamp>)`. Onde a medição ao vivo é necessária, marcamos
> `UNKNOWN` com `HOW_TO_MEASURE_LATER`. Nenhum número foi inventado.

## 2. FASE 1 — Hermes Runtime Inventory (OBSERVED em sessões anteriores)

| NAME | TYPE | ACTIVE | PURPOSE | STARTED_BY | EVIDENCE |
|---|---|---|---|---|---|
| hermes-gateway.service | systemd user | YES | gateway WhatsApp/Web + slash dispatch + agente | systemd --user (PID 3254622 @sprint0.6) | OBSERVED 2026-08-21 |
| prosperfy-cognitive-homolog-api.service | systemd user | YES | Cognitive API homolog (uvicorn :8800, LIVE_MCP=1) | systemd --user (PID 3252755) | OBSERVED 2026-08-21 |
| prosperfy-cognitive-homolog-console.service | systemd user | YES | console web (http.server :4180) | systemd --user | OBSERVED 2026-08-21 |
| hermes-dashboard.service | systemd user | YES | dashboard web (:9119) | systemd --user | OBSERVED |
| hermes-live-bridge.service | systemd user | YES | MCP bridge-serve (:9120) | systemd --user | OBSERVED |
| whatsapp-bridge (node) | child do gateway | YES | bridge WhatsApp (:3000, session bot) | hermes-gateway | OBSERVED |
| tui_gateway.slash_worker | processo | YES | sessões TUI interativas (model observado: gpt-5.6-luna) | manual/terminal | OBSERVED |
| pyright-langserver | processo | YES | LSP | manual | OBSERVED |
| docker: omniroute/traefik/portainer | containers | YES | serviços do host (não-Hermes) | docker | OBSERVED |

```
HERMES_RUNTIME_SERVICES=6 (systemd user) · PROCESSES=~8 · WORKERS=slash_worker(s)
TIMERS/CRON=UNKNOWN (gateway tem cron ticker no processo; jobs de cron do host não re-medidos)
HERMES_RUNTIME_CONTAINERS=3 (omniroute, traefik, portainer — não-Hermes)
```

## 3. FASE 2/3 — Software + Command Path Map (extension: CODE_CONFIRMED)

Extensão `capability-intelligence` (plugin runtime `~/.hermes/plugins/capability-intelligence`):

```
REGISTERED_COMMANDS (plugin)=2
  /capability  → _handle_slash → Pipeline (Resolver→Negotiator→Policy→Executor→Interpreter)
                → MCPAdapter direto (skills.prosperfy.com.br/mcp, MCP_PROSPERFYSKILLS_API_KEY)
                → DETERMINISTIC (sem LLM) · USES_DIRECT_MCP=YES · USES_COGNITIVE=NO
  /servidores  → _handle_servidores (async) → InfraService.servidores_status()
                → Cognitive (GET /v1/resources + infra.inspect POR resource)
                → DETERMINISTIC · USES_LLM=NO (PROVEN: 0 provider calls) · USES_COGNITIVE=YES
                → USES_DIRECT_MCP=NO · USES_DIRECT_PROSPERFYSKILL=NO (via Cognitive)

Commands do RUNTIME (built-ins): GATEWAY_KNOWN_COMMANDS derivado de COMMAND_REGISTRY
  (hermes_cli/commands.py). Contagem exata ao vivo = UNKNOWN (server).
  Separado: REGISTERED_COMMANDS ≠ COMMANDS_SENT_TO_LLM.
```

```
REGISTERED_COMMAND_COUNT=2 (plugin) + N built-ins runtime (UNKNOWN)
COMMANDS_REACHING_LLM=/servidores=0 · /capability=0 (extension) · built-ins: maioria handlers diretos; runtime "unknown" → UNKNOWN por comando
COMMANDS_BYPASSING_LLM=/servidores, /capability
DETERMINISTIC_COMMANDS=/servidores (PROVEN), /capability (CODE_CONFIRMED)
```

## 4. FASE 4 — LLM Boundary Map

| BOUNDARY | FILE/COMPONENT | CALLER | TRIGGER | LLM |
|---|---|---|---|---|
| Agent loop | runtime `GatewayRunner._run_agent`/`_run_agent_inner` (gateway/run.py) | `_handle_message_with_agent` | mensagem conversacional roteada ao agente | provider (openai/anthropic/bedrock/codex…) |
| Provider client | openai.AsyncClient.chat.completions.create / anthropic messages / adapters | agent loop | conversa normal | SIM |
| Plugin dispatch | get_plugin_command_handler → handler | gateway | /servidores, /capability | NÃO (0) |
| TUI sessions | tui_gateway.slash_worker (processo separado) | terminal | sessão interativa | SIM (model gpt-5.6-luna OBSERVED) |
| Dashboard web | hermes-dashboard | navegador | chat web | SIM (suposto) |
| Extension (plugin) | MCPAdapter / Pipeline / InfraService / server_views | — | — | NÃO (grep: zero import LLM SDK, CODE_CONFIRMED) |

```
LLM_BOUNDARIES_FOUND=4 (runtime: agent loop + provider clients + TUI + dashboard) ; extension: 0
PROVIDER_CALL_PATHS=conversa→agent loop→provider ; TUI; dashboard. /servidores e /capability NÃO.
MEASUREMENT_AVAILABLE=/servidores SIM (0 provado) · conversa UNKNOWN (server)
```

## 5. FASE 5/6 — Token/Context + medição real

```
BASE_PROMPT_SIZE/BYTES/TOKENS=UNKNOWN (compõe SOUL.md ~475B OBSERVED + config.yaml + skills +
  tool schemas + plugin descriptions; tamanho final só no server)
AUTO_INJECTED_CONTEXT_TOKENS=UNKNOWN · TOOL_SCHEMA_TOKENS=UNKNOWN
  HOW_TO_MEASURE_LATER: no host, medir o system prompt montado (runtime) por sessão.
TOOLS_TOTAL=UNKNOWN (tool registry do runtime) — não confundir com tools enviadas ao provider.
CONTEXT_SOURCE conhecidos: SOUL.md (OBSERVED ~475B), config.yaml, plugin descriptions
  (capability/servidores), skills (dir), memories/context.

Medição REAL representativa:
PATH=/servidores → LLM_PROVIDER_CALLS=0 · INPUT=0 · OUTPUT=0 · COST=0 (PROVEN, medição real com
  boundary instrumentado em GatewayRunner._run_agent + openai + anthropic; instrumento validado).
PATH=conversa livre → UNKNOWN (exige sessão no host; provider call real, custo > 0 esperado).
PATH=/capability → 0 LLM (CODE_CONFIRMED: sem SDK LLM na extension) — porém direto ao MCP.
```

## 6. FASE 7 — Component Classification

| COMPONENT | TYPE | LLM | DIRECT_MCP | REPLACED_BY_COGNITIVE | SHARED | CLASS | REASON | EVIDENCE |
|---|---|---|---|---|---|---|---|---|
| /servidores (plugin+InfraService+adapter+server_views) | deterministic | 0 | NO | — (já Cognitive) | NO | KEEP | core aprovado 0 LLM | PROVEN |
| /capability (pipeline+Executor) | deterministic | 0 | YES | YES (infra) | YES (/capability) | REVIEW | direto MCP, authorize é NO-OP | CODE_CONFIRMED |
| MCPAdapter | legacy transport | 0 | YES (skills.mcp) | YES (infra) | YES (/capability) | KEEP (shared) / REVIEW | regra: não remover compartilhado; authorize no-op = risco | CODE_CONFIRMED |
| Pipeline genérico (resolver/negotiator/policy/executor/interpreter) | deterministic | 0 | via MCPAdapter | parcial | YES | REVIEW | authorize placeholder → bypass de auth | CODE_CONFIRMED |
| CognitiveApiAdapter/InfraService/server_views | deterministic | 0 | NO | — | NO | KEEP | caminho oficial | PROVEN |

Achados de segurança (OBSERVED+CODE_CONFIRMED):
- `MCPAdapter.authorize` retorna `authorized=True` sempre (placeholder) — o `/capability` NÃO valida identidade/tenant.
- `MCPAdapter.get_status` hardcoda `capabilities_total=116` (valor obsoleto).

## 7. FASE 8/9 — ProsperfySkill Infra Tools + Resource Gap

Servidores conhecidos pelo ProsperfySkill (OBSERVED via listar_hosts, sprint 0.6):

```
PROSPERFYSKILL_SERVERS=4: Black(46.225.5.64), Hostinger One(147.93.67.71),
  Manager1(157.180.121.98), Prosperfy(177.7.50.182)
```

Tools infra do ProsperfySkill (OBSERVED de uso real nesta conversa + code):

```
prosperfy_vps_panorama          READ (usada por infra.inspect)
prosperfy_vps_listar_containers READ (usada por infra.inspect)
prosperfy_vps_verificar_portas  READ (usada por infra.inspect)
prosperfy_vps_listar_hosts      READ (inventário de hosts)
prosperfy_vps_executar          WRITE/shell (NÃO migrada)
prosperfy_vps_ler_arquivo       READ (NÃO migrada)
prosperfy_vps_escrever_arquivo  WRITE (NÃO migrada)
prosperfy_vps_controlar_servico WRITE/service (NÃO migrada)
prosperfy_vps_ler_logs          READ (NÃO migrada)
prosperfy_hello / list_tools    meta
Registry completo real = UNKNOWN (exige MCP tools/list no host).
```

Resource Gap (OBSERVED):

```
COGNITIVE_INFRA_RESOURCES=1 (prosperfy-vps-homolog → host Prosperfy)
AUTHORIZED_INFRA_RESOURCES=1 (grant infra.inspect/infra-read)
MISSING_INFRA_RESOURCES=3 (Black, Hostinger One, Manager1 — conhecidos no ProsperfySkill,
  NÃO discoverable via Cognitive GET /v1/resources)
STALE_INFRA_RESOURCES=0 · UNKNOWN_INFRA_RESOURCES=0
```

## 8. FASE 10 — Hermes Direct Paths

```
HERMES_DIRECT_MCP_PATHS=1: /capability → MCPAdapter → skills.prosperfy.com.br/mcp
HERMES_DIRECT_PROSPERFYSKILL_PATHS=1: (mesmo, via MCPAdapter)
PATH=/capability · VERTICAL=Capability Intelligence (pipeline) · USER_FACING=YES · ACTIVE=YES
  LLM_DEPENDENCY=NO · DIRECT_TARGET=ProsperfySkill MCP · CURRENT_AUTH_MODEL=NENHUM (authorize no-op)
  COGNITIVE_REPLACEMENT_EXISTS=parcial (Cognitive cobre capabilities determinísticas)
  SHARED_COMPONENT=MCPAdapter · RISK=MÉDIO (sem auth no path direto) · RECOMMENDATION=migrar /capability
  para Cognitive ou fechar o authorize placeholder (FUTURO; não migrar nesta sprint)
```

## 9. FASE 11 — Quick Wins (propostas; NÃO executar)

| ITEM | RISK | EXPECTED_REDUCTION | RECOMMENDATION |
|---|---|---|---|
| MCPAdapter.authorize no-op | médio (segurança) | elimina bypass de auth no /capability | corrigir ou migrar /capability p/ Cognitive |
| MCPAdapter.get_status hardcoded 116 | baixo | info fiel | remover hardcode |
| Descrições de plugin/contexto | baixo | contexto | revisar descrições enviadas ao LLM |
| Registro de 3 resources faltantes | — | visibilidade | FUTURO (autorização explícita) |

```
SAFE_QUICK_WINS=1-2 (fix authorize placeholder; remover hardcode 116)
ESTIMATED_REMOVABLE_CONTEXT=UNKNOWN · MEASURED_REMOVABLE_CONTEXT=0 (servidores já 0; demais UNKNOWN)
```

## 10. Mapas A e B (estrutura)

```
MAP A — HERMES SLIM
Hermes Runtime
├── services: gateway / dashboard / live-bridge / cognitive-api / console
├── commands: /servidores (deterministic→Cognitive) · /capability (deterministic→direct MCP)
│             · built-ins runtime (N count, UNKNOWN)
├── plugins: capability-intelligence (enabled) · cognitive-engine (disabled) · model-providers
├── LLM boundaries: agent loop (conversa/TUI/dashboard) — NOT em /servidores nem /capability
└── classification: KEEP(/servidores, adapters Cognitive) · REVIEW(/capability, MCPAdapter auth)
    · REMOVE candidates: nenhum nesta sprint

MAP B — INFRA GAP
ProsperfySkill (4 servers; tools read+write)
   ↓ infra.inspect (3 tools read) [+ listar_hosts/ler_arquivo/ler_logs read; executar/escrever/controlar WRITE]
Cognitive (1 resource: prosperfy-vps-homolog; 1 capability: infra.inspect ALLOW; 1 grant infra-read)
   ↓
Hermes (/servidores — 0 LLM)
EXISTS_AND_MAPPED: prosperfy-vps-homolog→Prosperfy
MISSING_RESOURCE: Black, Hostinger One, Manager1
CAPABILITY_GAP: writes (restart/cleanup/execute/control_service) sem capability
DIRECT_LEGACY_PATH: /capability → MCPAdapter (authorize no-op)
WRITE_OPERATION_NOT_MIGRATED: prosperfy_vps_executar/escrever_arquivo/controlar_servico
```

## 11. Métricas obrigatórias

```
SPRINT07_CHECKPOINT=8fab050da9ffc6b9f74a55c10023d66f35c6262f (baseline; audit branch dev/sprint-0.7)

HERMES_RUNTIME_SERVICES=6 · PROCESSES=~8 · WORKERS=UNKNOWN (slash_worker obs.) · TIMERS=UNKNOWN · CRON=UNKNOWN
REGISTERED_COMMANDS=2 (plugin) + built-ins UNKNOWN
COMMANDS_REACHING_LLM=0 (extension) · COMMANDS_BYPASSING_LLM=2 · DETERMINISTIC_COMMANDS=2
PLUGINS_TOTAL=3 (capability-intelligence, cognitive-engine, model-providers) · ENABLED=UNKNOWN ao vivo (capability-intelligence sim) · DISABLED=cognitive-engine
SKILLS_TOTAL=UNKNOWN · TOOLS_TOTAL=UNKNOWN · MCP_INTEGRATIONS=1 (skills.prosperfy.com.br/mcp)

BASE_PROMPT_SIZE=UNKNOWN · BASE_PROMPT_TOKENS=UNKNOWN
AUTO_INJECTED_CONTEXT_TOKENS=UNKNOWN · TOOL_SCHEMA_TOKENS=UNKNOWN
LLM_BOUNDARIES_FOUND=4 (runtime) / 0 (extension) · PROVIDER_CALL_PATHS=3 (conversa/TUI/dashboard)
TOP_TOKEN_COST_PATHS=UNKNOWN (exige medição no host; /servidores=0)

COMPONENTS_KEEP=/servidores stack, CognitiveApiAdapter · DETERMINISTIC=/capability (0 LLM)
COMPONENTS_MIGRATE=candidato futuro: /capability → Cognitive
COMPONENTS_REMOVE_CANDIDATES=nenhum (regra estrita não atendida p/ MCPAdapter: compartilhado)
COMPONENTS_REVIEW=MCPAdapter authorize, /capability path, hardcode 116

PROSPERFYSKILL_INFRA_TOOLS=9 observadas (3 read migradas + 6 não-migradas) · PROSPERFYSKILL_SERVERS=4
COGNITIVE_INFRA_RESOURCES=1 · AUTHORIZED_INFRA_RESOURCES=1
MISSING_INFRA_RESOURCES=3 · STALE=0 · UNKNOWN=0
INFRA_READ_COVERAGE=parcial (3 tools read) · INFRA_WRITE_TOOLS_AVAILABLE=3 (executar/escrever/controlar) · INFRA_DESTRUCTIVE_TOOLS_AVAILABLE=sim (executar/cleanup classes)

RECOMMENDED_INFRA_CAPABILITIES (conceituais, não criadas):
  infra.read_status (ALLOW) · infra.read_containers (ALLOW) · infra.read_ports (ALLOW)
  infra.logs_read (ALLOW limitado) · infra.restart_container (CONFIRM) · infra.restart_application (CONFIRM)
  infra.cleanup (CONFIRM restrito) · infra.execute_command (DENY / CONFIRM extremo) · infra.file_write (DENY)
RECOMMENDED_CONFIRM_OPERATIONS=restart_* , cleanup, deploy
RECOMMENDED_DENY=shell arbitrário, sudo, filesystem mutation ampla, prune amplo

HERMES_DIRECT_MCP_PATHS=1 (/capability) · HERMES_DIRECT_PROSPERFYSKILL_PATHS=1
ESTIMATED_REMOVABLE_CONTEXT=UNKNOWN · MEASURED_REMOVABLE_CONTEXT=0
NEW_DB_TABLES=0 · NEW_MIGRATIONS=0 · SOURCE_CODE_CHANGED=NO (apenas este doc de auditoria)

PRODUCTION_UNTOUCHED=YES · SECRET_EXPOSED=NO · GRANTS_MUTATED=NO · RESOURCES_MUTATED=NO
```

## 12. Recomendação final

**A. Hermes Slim (quick wins 3–10):**
1. Corrigir/remover `MCPAdapter.authorize` (no-op → risco de bypass) ou migrar `/capability` para Cognitive (0 LLM já; ganha auth+audit).
2. Remover hardcode `capabilities_total=116` no MCPAdapter.
3. Revisar descriptions de plugins/contexto injetados ao LLM (medir primeiro).
4. Inventariar skills/tool registry para achar contexto morto (medir no host).

**B. Migrações futuras (ordenadas por valor):**
1. `/capability` → Cognitive (VALUE alto: remove path direto não-autenticado; token 0 já; esforço baixo-médio).
2. Read tools não-migradas (ler_arquivo/ler_logs/listar_hosts) → capabilities read ALLOW.

**C. Infra visibility (o que falta p/ /servidores mostrar todos):**
Registrar 3 resources (Black, Hostinger One, Manager1) no Cognitive Homolog + grants
infra.inspect → **NÃO feito** (exige autorização; `RESOURCES_MUTATED=NO`).

**D. Infra Operations (Sprint 0.8 conceitual):**
Operations disponíveis no ProsperfySkill (executar/escrever/controlar/ler_logs) →
capabilities com ALLOW(read)/CONFIRM(write)/DENY(shell) + resources por servidor.
DO_NOT_START_SPRINT_0_8=YES.

**E. Próxima vertical:** decidir por dados (uso/custo/chamadas reais) — medir primeiro no host.

```
SPRINT_0_7_AUDIT_COMPLETE=YES
AUDIT_READ_ONLY=YES
PRODUCTION_UNTOUCHED=YES
DESTRUCTIVE_ACTIONS_EXECUTED=NO
RESOURCES_MUTATED=NO
GRANTS_MUTATED=NO
NEW_MIGRATIONS=0
NEW_DB_TABLES=0
SECRET_EXPOSED=NO
INFRA_CORE=PASS
INFRA_MULTI_RESOURCE_ENGINE=PASS
INFRA_LLM_ZERO_COST=PROVEN
INFRA_ALL_SERVERS_VISIBILITY=PENDING (3 resources faltantes)
INFRA_OPERATIONS=PENDING (capabilities write não existem)
RECOMMENDED_NEXT_ACTION=Medir token/contexto real no host (base prompt, tools, conversa) e
  decidir próximas migrações por dados; para ALL_SERVERS: autorizar registro dos 3 resources.
```