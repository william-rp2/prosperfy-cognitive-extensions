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

## RESUME FASE B–E (retomada, mesma sprint)

### Precheck de acesso (seção 2)

```
HERMES_RUNTIME_ACCESS=NO (ssh will@177.7.50.182/100.88.23.15 → Permission denied publickey)
PROSPERFYSKILL_MCP_ACCESS=YES (MCP direto skills.prosperfy.com.br/mcp autenticado com token local —
  initialize 200 OK, serverInfo=ProsperfySkills 3.4.2)
COGNITIVE_HOMOLOG_ACCESS=NO (sem SSH para ~/.hermes/.env/credential; supabase_consultar_sql sem
  inventário de contas no host do MCP → erro "Nenhum inventário de contas encontrado")
ACCESS_BLOCKER=SSH sem chave; MCP de VPS não anexado; credencial hermes-homolog só no host; contas
  Supabase não configuradas no host do MCP
FAILED_BOUNDARY=srv1631152 (SSH), Cognitive Homolog DB (sem conta Supabase), Hermes runtime
EVIDENCE=ssh: Permission denied (publickey); prosperfy_supabase_listar_contas: "Nenhum inventário
  de contas encontrado" (CLOUD_ACCOUNTS_PATH ausente)
SAFE_NEXT_STEP=Restaurar SSH/MCP VPS (ou informar conta Supabase no MCP) para FASE D/E; FASE B concluída
```

### FASE B — PASS (re-medida, real)

`prosperfy_vps_listar_hosts` (READ-ONLY, re-executado 2026-08-21):

```
PROSPERFYSKILL_SERVERS=4 (real)
  alias=Black          · hostname=46.225.5.64    · user=root · tags=[ubuntu linux hetzner ricardo principal site sistemas oficial]
  alias=Hostinger One  · hostname=147.93.67.71   · user=root · tags=[hostinger primeiro vps]
  alias=Manager1       · hostname=157.180.121.98 · user=root · tags=[hetzner automações primeiro servidor]
  alias=Prosperfy      · hostname=177.7.50.182   · user=will · tags=[hermes hostinger prosperfy]
```

CANONICAL_IDENTIFIER (para o MCP) = **alias** (é o valor do parâmetro `host` das tools VPS — confirmado
pelo resource existente: `prosperfy-vps-homolog` → resolved_params.host="Prosperfy").
SERVER_IDENTITIES_CONFIRMED=YES (aliases canônicos do inventário real; sem assumir slug por conta própria).

### Inventário tools de infra (registry real, tools/list = 186 tools)

```
READ_TOOLS=9: vps_panorama, vps_listar_containers, vps_verificar_portas, vps_listar_hosts,
  vps_ler_arquivo, vps_ler_logs, vps_listar_arquivos, vps_status_servico
WRITE/DESTRUCTIVE=5: vps_executar (shell allowlist), vps_escrever_arquivo, vps_controlar_servico,
  vps_controlar_container (start/stop/restart), vps_gerenciar_pacotes (APT)
NENHUMA write executada. Nenhuma testada.
```

### FASE C — reconciliação (hosts re-medidos; Cognitive OBSERVED sprint 0.6)

```
PROSPERFYSKILL_SERVERS=4 (real) · COGNITIVE_INFRA_RESOURCES=1 (prosperfy-vps-homolog, OBSERVED)
AUTHORIZED_INFRA_RESOURCES=1 (grant infra.inspect/infra-read, OBSERVED)
MISSING_INFRA_RESOURCES=3 (Black, Hostinger One, Manager1 — conhecidos no MCP, sem resource)
STALE_INFRA_RESOURCES=0 · UNKNOWN_INFRA_RESOURCES=0
```

Registro PROPOSTO (identifiers comprovados; NÃO executado — BLOCKED):

| resource_key (proposta) | resolved_params.host (canônico MCP) | type |
|---|---|---|
| black-vps-homolog | Black | vps |
| hostinger-one-vps-homolog | Hostinger One | vps |
| manager1-vps-homolog | Manager1 | vps |

### FASE D — BLOCKED (registro exige mecanismo canônico no host)

O mecanismo canônico é `TenantResourceRepository.upsert` (via admin/Cognitive code — bootstrap CLI
`sprint_0_3_synthetic_context.py`/CLI), acessível somente no host/Homolog. Sem SSH/MCP VPS não há
caminho canônico seguro; escrever direto no DB via MCP não existe (sem contas Supabase configuradas) e
violaria "não escrever diretamente no DB se existir mecanismo canônico".
NEW_RESOURCES_REGISTERED=0.

### FASE E — BLOCKED (live Hermes token/context exige host)

BASE_PROMPT_TOKENS / AUTO_INJECTED_CONTEXT_TOKENS / TOOL_SCHEMA_TOKENS / COMMANDS_SENT_TO_LLM /
TOOLS_SENT_TO_LLM = UNKNOWN (exige runtime no host).

## FINAL RESUME (FASE D+E) — CONCLUÍDO

Autorização explícita de `prosperfy_vps_executar` (só srv1631152, D/E) recebida.
Acesso executado via MCP direto (token local) → `prosperfy_vps_executar` em host="Prosperfy".

### FASE D1 — Reconfirm estado (DB real, read-only)
```
TARGET_REF=esvjfkknrzzziafovwrv CONFIRMADO (DSN db.esvjfkknrzzziafovwrv.supabase.co) · FORBIDDEN=False
TENANT=prosperfy-homolog (11a26649-...) · RESOURCES_BEFORE=1 (prosperfy-vps-homolog→Prosperfy)
GRANTS=1 (infra.inspect / infra-read — por tenant+profile, cobre todos os resources; sem ampliação)
MISSING=3 confirmado (Black, Hostinger One, Manager1)
```

### FASE D — Registro (mecanismo CANÔNICO `TenantResourceRepository.upsert`, 1 por vez)
```
1. black-vps-homolog       → host "Black"         UPSERTED active → VALIDADO (58 containers, real)
2. hostinger-one-vps-homolog → host "Hostinger One" UPSERTED active → VALIDADO (panorama real OK;
   infra.inspect → ERRO real: Docker indisponível no servidor — estado REAL, não mascarado)
3. manager1-vps-homolog    → host "Manager1"      UPSERTED active → VALIDADO (34 containers, real)
NEW_RESOURCES_REGISTERED=3 · RESOURCES_AFTER=4 · AUTHORIZED_AFTER=4 · MISSING=0
Sem migration, sem tabela nova, sem grant/profile ampliado, sem capability write.
```

### ALL-SERVERS E2E real (runtime Hermes, instrumentado)
```
AUTHORIZED_RESOURCES_FOUND=4 · AUTHORIZED_RESOURCES_EXECUTED=4
SERVERS_DISPLAYED=Black, Manager1, Prosperfy (+ hostinger-one ERRO)
SERVERS_OK=3 · DEGRADED=0 · FAILED=1 (hostinger-one: Docker ausente no servidor real)
SUMMARY=Servidores — 4 | Black — OK (58c) | Manager1 — OK (34c) | Prosperfy — OK (3c)
        | hostinger-one — ERRO (Docker indisponível) | Resumo: 3 OK · 0 DEGRADED · 1 ERRO
Hermes descobre via GET /v1/resources (sem hardcode).
```

### LLM zero-cost — PROVA NOVA (4 resources, medição real com boundary instrumentado)
```
HERMES_LLM_PROVIDER_CALLS=0 · INPUT_TOKENS=0 · OUTPUT_TOKENS=0 · COST=0
COGNITIVE_LLM_CALLS=0 · MCP_CALLS_PER_RESOURCE=3 · MCP_CALLS_TOTAL=12 (4×3, 1 tentativa falha)
```

### FASE E — Live token/context (host real; tiktoken ausente → tokens ESTIMADO char/4, marcados)
```
SOUL_MD_BYTES=475 · GUIDANCE_CONSTANTS_BYTES=15938 · USER_MD=0
BASE_PROMPT_EST_TOKENS=4109 (SOUL+guidance, ESTIMADO)
REGISTERED_COMMANDS=90 (88 built-in real + 2 plugin) · SKILLS_TOTAL=97 (real)
REGISTERED_TOOLS: gateway toolset=66 · whatsapp toolset=54 (real; registry lazy em processo fresco)
TOOL_SCHEMA_PAYLOAD_BYTES=103132 (66 schemas reais pós-import model_tools)
TOOL_SCHEMA_TOKENS_ESTIMATED=25783
COMMANDS_SENT_TO_LLM=/servidores e /capability=0 (determinísticos); conversa=UNKNOWN (exige sessão real)
TOOLS_SENT_TO_LLM=/servidores e /capability=0; conversa=toolset (66 gateway / 54 whatsapp)
LLM_BOUNDARIES_ACTIVE=4 (agent loop, TUI, dashboard, cron — não em /servidores nem /capability)
TOP_TOKEN_COST_PATHS=conversa (base≈4.1k + tools≈25.8k ≈ 29.9k tokens/turno, ESTIMADO) · /servidores=0
MEASURED_REMOVABLE_CONTEXT=0 (nenhum candidato comprovado; /servidores já 0)
```

### Security regression (pós-onboarding)
```
MCPADAPTER_AUTHORIZE_FAIL_CLOSED=PASS · CAPABILITY_RUN_DENIED=PASS
UNAUTHORIZED_CAPABILITY_MCP_CALL=DENIED · CAPABILITY_WRITE_TOOLS_REACHABLE=NO
HERMES_TESTS=363 passed / 1 skipped · TARGETED_SECURITY=18 passed (071+multi-resource)
```

## Final (gate definitivo)

```
SPRINT071_FINAL_CHECKPOINT=<após push>

AUTH_BYPASS_CONFIRMED=YES (latente) · AUTH_BYPASS_CONTAINED=YES
CAPABILITY_FAIL_CLOSED_OR_GOVERNED=YES
CAPABILITY_USER_CAN_SELECT_TOOL=NO · WRITE_TOOLS_REACHABLE_BEFORE_FIX=NO · AFTER_FIX=NO
STATUS_116_FIXED=NO · STATUS_116_DEFERRED=YES

PROSPERFYSKILL_SERVERS=4 (real) · SERVER_IDENTITIES_CONFIRMED=YES (aliases canônicos)
COGNITIVE_INFRA_RESOURCES_AFTER=4 · AUTHORIZED_INFRA_RESOURCES_AFTER=4
NEW_RESOURCES_REGISTERED=3 · MISSING_INFRA_RESOURCES=0
AUTHORIZED_RESOURCES_FOUND=4 · AUTHORIZED_RESOURCES_EXECUTED=4
WHATSAPP_ALL_SERVERS=VALIDADO_VIA_RUNTIME_PATH (4 discoverable dinâmico; mensagem live = usuário)
WEB_ALL_SERVERS=VALIDADO_VIA_RUNTIME_PATH

HERMES_LLM_PROVIDER_CALLS=0 · INPUT=0 · OUTPUT=0 · COST=0 · COGNITIVE_LLM_CALLS=0
MCP_CALLS_PER_RESOURCE=3 · MCP_CALLS_TOTAL=12

BASE_PROMPT_EST_TOKENS=4109 (SOUL 475B + guidance 15938B; ESTIMADO char/4, sem tiktoken)
TOOL_SCHEMA_TOKENS_ESTIMATED=25783 (66 schemas gateway = 103132B)
REGISTERED_COMMANDS=90 (88 built-in + 2 plugin) · COMMANDS_SENT_TO_LLM: /servidores=/capability=0
REGISTERED_TOOLS (gateway toolset)=66 · whatsapp toolset=54 · TOOLS_SENT_TO_LLM: /servidores=/capability=0
SKILLS_TOTAL=97 · LLM_BOUNDARIES_ACTIVE=4 (não em /servidores nem /capability)
TOP_TOKEN_COST_PATHS=conversa (~29.9k ESTIMADO/turno = base 4.1k + tools 25.8k) · /servidores=0
MEASURED_REMOVABLE_CONTEXT=0

NEW_DB_TABLES=0 · NEW_MIGRATIONS=0 · WRITE_CAPABILITIES_CREATED=0 · INFRA_WRITE_ACTIONS_EXECUTED=0
PRODUCTION_UNTOUCHED=YES · SECRET_EXPOSED=NO · MASTER_UNTOUCHED=YES · WORKTREE_CLEAN=YES

INFRA_CORE=PASS · INFRA_MULTI_RESOURCE_ENGINE=PASS · INFRA_LLM_ZERO_COST=PASS (4-resource, medido)
INFRA_ALL_SERVERS_VISIBILITY=PASS (4 discoverable/executed; 1 real degradado refletido)
INFRA_OPERATIONS=PENDING

SPRINT_0_7_1_FINAL_GATE=PASS
RECOMMENDED_NEXT_ACTION=parar; sem Sprint 0.8; aguardar nova autorização
```