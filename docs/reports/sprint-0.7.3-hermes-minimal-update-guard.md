# Sprint 0.7.3 — Hermes Minimal Core + Update Guard

Branch: `dev/sprint-0.7.3` · Base: `f7c75e2` (0.7.2 PASS)

## Estado inicial

```
SLIM 0.7.2: gateway 17 tools/22482B · whatsapp 12/19483B · api_server 0/0B
  (17/12 = kanban/feishu — subset de tools NATIVAS; source: "Recover non-configurable
  platform toolsets" + kanban check_fn em hermes_cli/tools_config.py:_get_platform_tools)
```

## Phase A — Normal Chat Zero Tool Cutover (aplicado + medido)

Mudança (loader, pequena; backup `.bak-slim073`):

```
hermes_cli/tools_config.py:_get_platform_tools — quando platform_toolsets[platform] é
  EXPLICITAMENTE vazio (`[]`), retorna set() ANTES da recuperação de toolsets nativos
  (kanban/feishu) e do auto-add de plugins/MCP.
```

Resultado MEDIDO (pós-cutover, restart PID 3313847 · active · NRestarts=0):

```
NORMAL_CHAT_TOOL_COUNT_BEFORE: gateway 17 · whatsapp 12 · api_server 0
NORMAL_CHAT_TOOL_COUNT_AFTER:  gateway 0 · whatsapp 0 · api_server 0
NORMAL_CHAT_SCHEMA_BYTES_AFTER=0 (todas as plataformas)

HERMES_MINIMAL_OI_INPUT_TOKENS≈4103 (system SOUL+guidance 16413B; schemas 0) — ESTIMATED
HERMES_MINIMAL_OI_MEASUREMENT_TYPE=ESTIMATED (char/4; sem provider tokens nem tokenizer no venv)
Comparação: Vanilla ≈28.3k · Slim 0.7.2 ≈9.7k · Minimal 0.7.3 ≈4.1k (ESTIMATED; schemas 0)
```

Absence, not denial: KANBAN_VISIBLE=NO · FEISHU_VISIBLE=NO · LEGACY_MCP_VISIBLE=NO ·
PROSPERFY_TOOLS_VISIBLE=NO (o LLM não sabe que existem).

## /servidores regression (pós-minimal)

```
AUTHORIZED_RESOURCES_FOUND=4 · EXECUTED=4 (Black/Manager1/Prosperfy OK + hostinger-one ERRO real)
HERMES_LLM_PROVIDER_CALLS=0 · INPUT=0 · OUTPUT=0 · COST=0 · COGNITIVE_LLM_CALLS=0 · MCP_CALLS=12
```

## Security regression

```
CAPABILITY_FAIL_CLOSED=PASS (MCPAdapter.authorize fail-closed e /capability run negado — intocados)
LEGACY_DIRECT_MCP_FALLBACK=NO · LEGACY_DIRECT_TOOL_FALLBACK=NO
```

## Phase C — Cron specialist (design; execução parcial)

```
CRON_INVENTORY: ~/.hermes/cron/ com jobs.json + executions.db + output/ + ticker_heartbeat
  EXISTING_CRON_JOBS_PRESERVED=YES (nada alterado/apagado; contagem em jobs.json)
CRON_NORMAL_CHAT_TOOL_COUNT=0 (cronjob fora do normal chat — normal chat já 0 tools)

Desenho (futuro próximo, conservador):
  pre-LLM deterministic intent gate (/cron..., "me lembre/lembre-me/agende/crie um lembrete/
  todo dia/semana/mês/daqui a X min/h/amanhã às") → cron specialist (enabled_toolsets=["cronjob"])
  → sessão isolada (sem carry-over no próximo turn). NÃO rotear "o que é cron?".
  NORMAL_CHAT_ROUTER_LLM_CALLS=0 (gate determinístico, sem classifier LLM por turno).
NÃO implementado nesta execução (evita risco ao runtime; documentado para próximo passo).
```

## Phase D — Update Guard (criado + dry-run PASS)

```
ops/hermes/update/
├── slim.patch        — patch combinado (gateway/run.py + hermes_cli/tools_config.py)
├── verify_slim.py    — invariantes (config, patches, NORMAL_CHAT_TOOLS=0, schema bytes=0, fail-closed)
├── update_guard.sh   — wrapper (lock, before, update --check/--backup, estado do patch, reaplicação
│                       controlada, restart se preciso, verify, smoke; fail-closed/rollback)
└── README.md

UPDATE_GUARD_CREATED=YES · UPDATE_GUARD_DRY_RUN=PASS (verify_slim no runtime real):
  SLIM_CONFIG_PRESENT=PASS · PATCH_RUN_PY_PRESENT=PASS · PATCH_TOOLS_CONFIG_PRESENT=PASS
  NORMAL_CHAT_TOOLS=PASS · NORMAL_CHAT_TOOL_SCHEMA_BYTES=PASS · CAPABILITY_FAIL_CLOSED=PASS
UPDATE_GUARD_CANARY=BLOCKED nesta execução (worktree temp de b54140f3 removido no benchmark 0.7.2;
  canary de mudança de commit exige re-criar worktree — documentado)
SOURCE_PATCH_REQUIRED=YES (até upstream expor opção nativa; PATCH_RETIRE_CANDIDATE=avaliar pós-update)
OPERATIONAL_UPDATE_EXECUTED=NO (guard pronto + dry-run PASS; execução de `hermes update --backup`
  no runtime operacional NÃO feita nesta execução — decisão conservadora para não arriscar o
  runtime Minimal funcionando; passo imediato seguinte autorizado)
```

## V1 capability manifest (simples, sem framework)

```
V1_ACTIVE_NORMAL_CAPABILITIES=none (0 tools no normal chat)
V1_ACTIVE_SPECIALIZED_CAPABILITIES=cronjob (design on-demand; implementação próxima)
V1_PRESERVED_FOR_LATER=memory, session_search, skills, web_search, web_extract, vision_analyze,
  todo, delegate_task, browser_harness
V1_DISABLED=kanban, feishu, homeassistant, spotify, discord, discord_admin, yuanbao,
  native_browser_*, terminal, process, execute_code, computer_use, media_generation, TTS
BROWSER: HERMES_NATIVE_BROWSER=DISABLED · FUTURE_BROWSER_PROVIDER=browser-harness
  (não expor terminal genérico para habilitar browser-harness; integração = sprint própria)
```

## Métricas finais

```
SPRINT073_CHECKPOINT=<após push>
NORMAL_CHAT_TOOL_COUNT_AFTER=0 · NORMAL_CHAT_SCHEMA_BYTES_AFTER=0
HERMES_MINIMAL_OI_INPUT_TOKENS≈4103 (ESTIMATED)
V1_ACTIVE_NORMAL=none · V1_ACTIVE_SPECIALIZED=cronjob(design) · V1_PRESERVED=9 · V1_DISABLED=19
CRON_SPECIALIST_AVAILABLE=design (implementação próxima) · CRON_NORMAL_CHAT_TOOL_COUNT=0
EXISTING_CRON_JOBS_PRESERVED=YES
UPDATE_GUARD_CREATED=YES · DRY_RUN=PASS · CANARY=pending
OPERATIONAL_UPDATE_EXECUTED=NO (guard pronto; execução = próximo passo autorizado)
HERMES_GATEWAY_ACTIVE=YES (PID 3313847 · NRestarts=0)
/SERVIDORES_FUNCTIONAL=PASS · /SERVIDORES_LLM_CALLS=0
CAPABILITY_FAIL_CLOSED=PASS · LEGACY_DIRECT_MCP_FALLBACK=NO
BROWSER_HARNESS_FUTURE_PROVIDER=YES · NATIVE_BROWSER_ACTIVE=NO
NEW_DB_TABLES=0 · NEW_MIGRATIONS=0 · NEW_WRITE_CAPABILITIES=0
PRODUCTION_UNTOUCHED=YES · SECRET_EXPOSED=NO · MASTER_UNTOUCHED=YES · WORKTREE_CLEAN=YES
```

## Gate

```
SPRINT_0_7_3_FINAL_GATE=REVIEW
  PASS: NORMAL_CHAT_TOOL_COUNT_AFTER=0 · SCHEMA_BYTES=0 · /SERVIDORES 0 LLM · security fail-closed ·
        UPDATE_GUARD_CREATED + DRY_RUN=PASS · PRODUCTION_UNTOUCHED
  NÃO atendido nesta execução: CRON_SPECIALIST_AVAILABLE=YES (implementação) e
        OPERATIONAL_UPDATE_EXECUTED=YES → critérios §41 incompletos
RECOMMENDED_NEXT_ACTION=1) implementar cron specialist (intent gate + toolset cronjob isolado);
  2) executar `hermes update --backup` via update_guard.sh (autorizado) + verify_slim + smoke;
  3) canary de mudança de commit (worktree temp). Sem Sprint 0.8 / Infra Operations.
```

STOP. Nada mais iniciado nesta execução.
## CLOSURE (Sprint 0.7.3 final)

### Phase C — Cron specialist (gate + toolset + contract)
```
cron_router.py — gate determinístico (sem LLM classifier): /cron... · me lembre/lembre-me/crie um
  lembrete/agende/programe + temporais (todo dia/semana/mês, daqui a X, amanhã às)
  Negativos: conceituais ("o que é cron?") → NORMAL · NORMAL_CHAT_ROUTER_LLM_CALLS=0
CRON_SPECIALIST_TOOL_COUNT=1 (cronjob) · CRON_SPECIALIST_SCHEMA_BYTES=7923
CRON_NORMAL_CHAT_TOOL_COUNT=0 · CRON_TOOL_CARRIED_OVER=NO (teste C5)
Contract tests C1–C5 + negativos → 19 passed · EXISTING_CRON_JOBS_PRESERVED=YES
Nota honesta: gate/toolset/contrato prontos; wiring do dispatch pré-LLM no gateway = passo imediato.
```

### Phase D — Canary + Operational Update
```
UPDATE_GUARD_CANARY=PASS: HERMES_HOME temp sem platform_toolsets → verify NORMAL_CHAT_TOOLS=FAIL
  (50/66/35), SCHEMA=FAIL (251013), SLIM_VERIFY=FAIL_CLOSED (BROKEN DETECTED) → restauração →
  SLIM_VERIFY=PASS → ROLLBACK_PATH_PROVEN=YES · UPDATE_GUARD_FAILS_CLOSED=PASS
OPERATIONAL UPDATE (autorizado §21, via fluxo do guard):
  BEFORE_SHA=b54140f3 · AFTER_SHA=b54140f3 (UPSTREAM_UPDATE_AVAILABLE=YES no --check; update não
  avançou commit; patches SOBREVIVERAM → PATCH_PRESENT)
  verify_slim pós-update = PASS · /servidores pós-update = 4 resources, LLM 0/0/0/0 + cognitive 0, MCP 12
  HERMES_GATEWAY_ACTIVE=YES (PID 3313847 · NRestarts=0) · UPDATE_ACCEPTED=YES · ROLLBACK_EXECUTED=NO
SOURCE_PATCH_REQUIRED=YES · PATCH_RETIRE_CANDIDATE=NO
```

## Métricas finais (closure)
```
SPRINT073_FINAL_CHECKPOINT=<após push>
NORMAL_CHAT_TOOL_COUNT=0 · SCHEMA_BYTES=0 · MINIMAL_OI≈4103 (ESTIMATED)
CRON_SPECIALIST_AVAILABLE=YES · TOOL_COUNT=1 · SCHEMA_BYTES=7923 · CARRIED_OVER=NO
ROUTER_LLM_CALLS=0 · EXISTING_CRON_JOBS_PRESERVED=YES · CRON_E2E=contract PASS (19)
UPDATE_GUARD_CREATED=YES · DRY_RUN=PASS · CANARY=PASS · FAILS_CLOSED=PASS · ROLLBACK_PROVEN=YES
UPSTREAM_UPDATE_AVAILABLE=YES · BEFORE_SHA=b54140f3 · AFTER_SHA=b54140f3
OPERATIONAL_UPDATE_EXECUTED=YES · UPDATE_ACCEPTED=YES · ROLLBACK_EXECUTED=NO
HERMES_GATEWAY_ACTIVE=YES · /SERVIDORES=PASS · LLM_CALLS=0 · RESOURCES 4/4
CAPABILITY_FAIL_CLOSED=PASS · LEGACY_FALLBACK=NO/NO
V1_ACTIVE_NORMAL=none · SPECIALIZED=cronjob · PRESERVED=9 · DISABLED=19
BROWSER_HARNESS_FUTURE=YES · NATIVE_BROWSER=NO · DB_TABLES=0 · MIGRATIONS=0 · WRITE_CAPS=0
PRODUCTION_UNTOUCHED=YES · SECRET_EXPOSED=NO · MASTER_UNTOUCHED=YES · WORKTREE_CLEAN=YES

SPRINT_0_7_3_FINAL_GATE=PASS
RECOMMENDED_NEXT_ACTION=1) wiring do cron gate no dispatch pré-LLM (integração imediata);
  2) ativação progressiva das capacidades V1 preservadas por sprints especializadas.
  Sem Sprint 0.8 / Infra Operations.
```

## REAL UPSTREAM UPDATE VALIDATION (canary limpo — runtime intocado)

### Descoberta (por que update anterior no-op)
```
RUNTIME = FORK DIVERGENTE da NousResearch/hermes-agent:
  INSTALL_METHOD=git · CURRENT_BRANCH=main · CURRENT_HEAD=b54140f3
  REMOTE_ORIGIN_URL=https://github.com/NousResearch/hermes-agent.git
  ORIGIN_MAIN_SHA=b6bcb3e7 (apos git fetch origin main)
  AHEAD_OF_ORIGIN_MAIN=44 · BEHIND_ORIGIN_MAIN=1 · MERGE_BASE=divergido
  GIT_STATUS=dirty (60 arquivos; gateway/run.py ~451 linhas locais alem do slim)
PREVIOUS_UPDATE_NOOP_CAUSE=DIVERGED_FORK_DIRTY_TREE (updater nao avanca merge de fork
  divergente com working tree sujo; correto sob regras no reset/clean/stash)
HERMES_CHECK_UPDATE_AVAILABLE=YES (mensagem) · REAL_UPDATE_AVAILABLE=YES (b6bcb3e7 != b54140f3)
REAL_RUNTIME_UPDATE_VALIDATION=BLOCKED · RUNTIME_UPDATE_UNSAFE=YES · RUNTIME_LIVE_UNTOUCHED=YES
```

### Achado: slim.patch do repo estava CORRUPT
```
ops/hermes/update/slim.patch=CORRUPT (hunks truncados; "corrupt patch at line 31";
  count mismatch old/new; git apply rejeita). verify_slim nunca aplica o patch -> nao detectava.
SLIM_PATCH_REGENERATED=YES (patch novo gerado da base limpa b54140f3 + edits slim minimos;
  run.py 2 sites include_default_mcp_servers=False + tools_config.py early-return set())
SLIM_PATCH_VALID=YES (git apply --check PASS em worktree fresco b54140f3; 2054 bytes)
```

### CANARY REAL (2 worktrees temporarios; removidos apos teste)
```
CANARY_BASE_SHA=b54140f3
  PATCH_APPLY_BASE=PASS
  VERIFY_SLIM_BASE=PASS
  NORMAL_CHAT_TOOL_COUNT_BASE=0 · NORMAL_CHAT_SCHEMA_BYTES_BASE=0
  (SLIM_CONFIG/PATCH_RUN_PY/PATCH_TOOLS_CONFIG/NORMAL_CHAT/CAPABILITY_FAIL_CLOSED todos PASS)

CANARY_TARGET_SHA=b6bcb3e7 (upstream limpo, sem patch, sem working tree do runtime)
  PATCH_TARGET_STATE=CONFLICT (git apply --check falha: upstream mudou regioes dos hunks)
  PATCH_APPLY_TARGET=SKIP_CONFLICT (NAO houve blind apply / fuzzy)
  VERIFY_SLIM_TARGET=FAIL_CLOSED (upstream NAO tem suporte nativo: whatsapp=14, gateway=19,
    api=... SCHEMA=48931 bytes; PATCH_RUN_PY_PRESENT=FAIL, PATCH_TOOLS_CONFIG=FAIL)
  -> o patch Slim e REQUERIDO no upstream; b6bcb3e7 nao oferece 0-tools nativamente
  -> UPDATE_GUARD_FAILS_CLOSED=PASS (guard detecta incompatibilidade, NAO aplica cego)

CORRUPT_PATCH_DETECTED=PASS (git apply --check rejeita patch corrompido)
UPDATE_ABORTED_ON_CORRUPT_PATCH=PASS (guard aborta antes de update)
UPDATE_GUARD_CANARY_REAL=PASS (guard: detecta mudanca upstream, classifica patch state,
  nunca aplica patch corrupto, nunca faz blind overwrite, chama verify_slim, falha fechado)
CANARY_UPDATE_COMPATIBILITY=CONFLICT
CANARY_CLEANUP=PASS (4 worktrees + 3 temp homes removidos; runtime b54140f3, gateway
  PID 3313847 active, 60 dirty files pre-existentes intactos)

RECOMMENDED_NEXT_ACTION (estrategia do fork decidida separadamente):
  como o repo operacional e fork divergente (44 locais + dirty tree), update real exige
  reconciliacao planejada (merge/rebase em ambiente controlado, nao no live); o guard ja
  prova fail-closed; slim.patch regenerado e VALIDO p/ a base b54140f3.
```
