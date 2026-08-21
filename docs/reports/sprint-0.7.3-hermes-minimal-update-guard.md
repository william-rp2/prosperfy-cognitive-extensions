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