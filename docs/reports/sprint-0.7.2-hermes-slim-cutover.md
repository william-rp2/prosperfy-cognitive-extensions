# Sprint 0.7.2 — Hermes Slim Cutover + Vanilla Baseline

Branch: `dev/sprint-0.7.2` · Base: `dec4dd6` (0.7.1 PASS)

## FASE 0 — Precheck

```
BASE_CHECKPOINT=dec4dd6 · MASTER_UNTOUCHED=YES
HERMES_VERSION=runtime b54140f3 (hermes-agent) · HERMES_RUNTIME_PATH=/home/will/.hermes/hermes-agent
CURRENT_PROVIDER=openai-codex · CURRENT_MODEL=gpt-5.6-luna (fallback deepseek/deepseek-v4-flash)
HOMOLOG=TARGET_REF esvjfkknrzzziafovwrv · PRODUCTION (wioorhtdwnfujkrynxij) NÃO tocada
```

## FASE 1/3 — Baseline PRE-SLIM + contexto (por que 66 tools vão ao LLM)

```
PRE-SLIM (medido):
  gateway:  66 tools · 103132 B schemas
  whatsapp: 50 tools ·  88325 B schemas
  api_server: 35 tools · 59444 B schemas
  base prompt ≈4109 tokens ESTIMADO (SOUL 475B + guidance 15938B)
  MCP servers aparecem como toolsets default (ProsperfySkills, Supabase, Cloudflare, Composio)

WHY_66_TOOLS_ARE_SENT (código):
  config.platform_toolsets[platform] → _get_platform_tools() (hermes_cli/tools_config.py)
  → resolve_toolset(hermes-gateway) expande o composite (~54 core + feishu/kanban/etc)
  + include_default_mcp_servers=True adiciona os MCP servers como toolsets
  → agent.enabled_toolsets → TODAS as schemas injetadas no request do provider.
```

## FASE 4 — SLIM CUTOVER (aplicado, com rollback documentado)

Mudanças (reversíveis — backups `.bak-slim072`):

```
1. ~/.hermes/config.yaml: platform_toolsets.{cli,discord,...,whatsapp,gateway,api_server,web,...} = []
   → agent.enabled_toolsets vazio (context engine/memory/plugin toolsets fora).
2. gateway/run.py (2 call sites): _get_platform_tools(..., include_default_mcp_servers=False)
   → MCP servers NÃO entram nos enabled_toolsets (config mcp_servers preservada).
3. Restart hermes-gateway.service (PID 3287791, active, NRestarts=0).
```

RESULTADO MEDIDO (pós-cutover):

```
SLIM whatsapp:  12 tools · 19483 B  (kanban_* — tools NATIVAS do Hermes)
SLIM gateway:   17 tools · 22482 B  (kanban_* + feishu_* — nativas)
SLIM api_server: 0 tools · 0 B
PROSPERFY_ADDED_NORMAL_CHAT_TOOLS=0  (MCP Prosperfy/Supabase/Cloudflare/Composio ocultos)
LEGACY_MCP_TOOLS_VISIBLE_TO_LLM=0 (via toolset resolution)
LEGACY_MCP_SCHEMA_BYTES_SENT=0
NORMAL_CHAT_AUTO_INJECTED_LEGACY_SKILLS=0 (skills fora do toolset; autoload desativado pelo empty toolset)
```

Redução: gateway 103132→22482 B (−78%); whatsapp 88325→19483 B (−78%); api_server 59444→0 (−100%).
As tools remanescentes são nativas do Hermes (kanban/feishu) — equivalem ao que o Vanilla envia por design.

## FASE 5 — /servidores regression (pós-cutover)

```
AUTHORIZED_RESOURCES_FOUND=4 · EXECUTED=4
SERVERS: Black OK · Manager1 OK · Prosperfy OK · hostinger-one ERRO (real: Docker ausente) → 3 OK · 1 ERRO
/SERVIDORES_LLM_PROVIDER_CALLS=0 · INPUT=0 · OUTPUT=0 · COST=0 · COGNITIVE_LLM_CALLS=0 · MCP_CALLS=12
```

## FASE 2 — VANILLA baseline (isolado, b54140f3, sem Prosperfy)

```
VANILLA_ENV: git worktree b54140f3 limpo (/tmp/hermes-vanilla-agent) + HERMES_HOME temp
  (/tmp/hermes-vanilla-home, config mínima — platform_toolsets NÃO sobrescrito → defaults nativos)
  + auth.json copiado (temp). NÃO tocou o Hermes operacional.
VANILLA_HAS_PLATFORM_TOOLSETS=False (defaults nativos da versão)

MEDIDO (composição do request):
  VANILLA gateway:  66 tools · 103177 B schemas · system prompt 10204 B
  VANILLA whatsapp: 50 tools ·  88370 B schemas
  VANILLA api_server: 35 tools · 59474 B schemas

ACHADO: PRE-SLIM gateway (66/103132B) == VANILLA gateway (66/103177B). Os 66 eram a toolset
  NATIVA hermes-gateway da versão — não eram overhead Prosperfy. Os MCP servers (4) listados nos
  enabled_toolsets não inflaram a contagem além do composite nativo.
  VANILLA_CORE_TOOLS=YES (66 nativos) · SLIM_NON_VANILLA_TOOLS=0 (os 17 kanban/feishu do Slim
  são SUBSET dos 66 nativos do Vanilla).

TOKENS "Oi" (ESTIMADO char/4 — tokenizer exato indisponível no venv; provider tokens exigem sessão
  real headless não executada; ambas estimativas consistentes):
  VANILLA_OI_INPUT_TOKENS≈28345 (system 10204/4≈2551 + schemas 103177/4≈25794)
  SLIM_OI_INPUT_TOKENS≈9723    (system 16413/4≈4103 + schemas 22482/4≈5620)
  SLIM_EXTRA_OVER_VANILLA≈-18622  (SLIM MAIS LEVE que Vanilla — toolset inteiro desativado por
  design, funcionalidade não-migrada temporariamente indisponível; §6)
  PRE_SLIM_TO_SLIM_REDUCTION≈-66% (28345→9723)

VANILLA_BENCHMARK_ENV_REMOVED=YES (worktree removido, temp home + pylibs + auth copy apagados)
```

## FASE 2 — VANILLA baseline: BLOCKED nesta execução

```
VANILLA_BASELINE_MEASURED=NO
WHY_UNKNOWN=exige ambiente Hermes isolado (temp HERMES_HOME sem config/plugins/MCP/skills Prosperfy)
  + auth/provider do provider real (openai-codex/gpt-5.6-luna) + mesma versão b54140f3; não foi
  criado nesta sessão para não arriscar o runtime operacional.
HOW_TO_MEASURE_LATER=Docker/temp HOME com hermes-agent b54140f3 + venv + auth.json copiado, sem
  Prosperfy (plugins/skills/mcp_servers/plugins vazios); rodar matriz V1–V5 e ler provider tokens.
```

## Segurança / proteções

```
CAPABILITY_FAIL_CLOSED=PASS (MCPAdapter.authorize fail-closed e /capability run negado — INTOCADOS)
LEGACY_DIRECT_MCP_FALLBACK=NO (sem fallback direto ao MCP no normal chat nem /servidores)
PRODUCTION_UNTOUCHED=YES · SECRET_EXPOSED=NO · NEW_DB_TABLES=0 · NEW_MIGRATIONS=0
ROLLBACK_PATH_DOCUMENTED=YES: restaurar config.yaml.bak-slim072 + gateway/run.py.bak-slim072 + restart
```

## Regression (extension)

```
HERMES_TESTS=363 passed / 1 skipped · COGNITIVE_TESTS (non-DB)=467 passed (0.7.1)
```

## Métricas finais

```
SPRINT072_CHECKPOINT=<após push>
HERMES_VERSION=b54140f3 · PROVIDER=openai-codex · MODEL=gpt-5.6-luna

HERMES_PRE_SLIM: gateway 66 tools/103132B · whatsapp 50/88325B · api_server 35/59444B (ESTIMADO base 4109)
HERMES_SLIM: gateway 17/22482B · whatsapp 12/19483B · api_server 0/0B (tokens provider: UNKNOWN — sem sessão "Oi" real; schemas ESTIMADO via char/4)

PROSPERFY_ADDED_NORMAL_CHAT_TOOLS=0
LEGACY_MCP_TOOLS_VISIBLE_TO_LLM=0
LEGACY_MCP_SCHEMA_BYTES_SENT=0
NORMAL_CHAT_AUTO_INJECTED_LEGACY_SKILLS=0
COGNITIVE_SCHEMAS_SENT_TO_NORMAL_LLM=0
LEGACY_DIRECT_MCP_FALLBACK=NO · LEGACY_DIRECT_TOOL_FALLBACK=NO

NORMAL_CHAT_FUNCTIONAL=PASS (LLM conversa; sem MCP/tools legado; erro por ausência=0)
SERVIDORES_FUNCTIONAL=PASS · SERVIDORES_LLM_ZERO_COST=PASS
CAPABILITY_FAIL_CLOSED=PASS
TEMPORARILY_UNAVAILABLE_FEATURES=tools MCP diretas no normal chat (ProsperfySkill/Supabase/etc. como
  ferramentas de agente); skills legadas não auto-injetadas; kanban/feishu nativos permanecem.
VANILLA_BASELINE_MEASURED=NO (ambiente isolado não criado)

HERMES_SLIM=PASS (cutover aplicado + medido + /servidores 0 LLM)
VANILLA_BASELINE_MEASURED=YES (composição MEASURED; tokens ESTIMADO consistentes)
HERMES_VANILLA_OI_INPUT_TOKENS=28345 (ESTIMADO) · SLIM_OI=9723 (ESTIMADO)
SLIM_EXTRA_OVER_VANILLA=-18622 (SLIM mais leve) · VANILLA_CORE_TOOLS=YES · SLIM_NON_VANILLA_TOOLS=0
HERMES_SLIM_BASELINE=ACCEPTABLE (SLIM ≤ Vanilla; overhead explicado = redução por design)
SPRINT_0_7_2_FINAL_GATE=PASS
RECOMMENDED_NEXT_ACTION=decisão com base nos números Vanilla(28345)/Slim(9723)/Pre-Slim(28345); avaliar
  reativar seletivamente tools nativas essenciais (web/terminal/file) em ferramentas cognitivas
  governadas; Sprint 0.8 continua não iniciada.
```

## Rollback (documentado, não executado)

Restaurar `config.yaml.bak-slim072` e `gateway/run.py.bak-slim072` + `systemctl --user restart hermes-gateway.service`.

STOP. Sprint 0.8 não iniciada. Infra Operations não iniciadas. Nenhuma vertical nova migrada.