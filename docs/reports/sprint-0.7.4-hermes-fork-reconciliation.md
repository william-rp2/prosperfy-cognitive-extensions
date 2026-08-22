# Sprint 0.7.4 — Hermes Fork Reconciliation + Update-Safe Overlay

> Ambiente controlado. Runtime live NÃO tocado. Candidate validado em worktree isolado.

## 1. Estado do fork operacional (Phase A)

```
INSTALL_METHOD=git · CURRENT_BRANCH=main · LIVE_HEAD=b54140f3
ORIGIN_MAIN_SHA=b6bcb3e7 (apos git fetch origin main)
LIVE_LOCAL_COMMITS=44 · LIVE_DIRTY_FILES=10 M + ~50 untracked (~60)
AHEAD_OF_ORIGIN_MAIN=44 · BEHIND_ORIGIN_MAIN=1 · MERGE_BASE=divergido
REMOTE_ORIGIN_URL=github.com/NousResearch/hermes-agent
RUNTIME_UPDATE_UNSAFE=YES · RUNTIME_LIVE_UNTOUCHED=YES
```

## 2. Inventario dos 44 commits locais (Phase A)

Lista completa em `git log origin/main..HEAD`. Agrupados por tema e classificacao:

| SHA | Tema | Classificacao |
|---|---|---|
| b54140f3, 1c366ab5 | bridge budget enforcement | REVIEW (candidato OBSOLETE p/ Slim) |
| 5f9ac7fb | context delivery gate policy | REPLACED_BY_COGNITIVE |
| 6c74cf3b, 5e0552dd, 753fd116, 5e23286c, 9aa38037, 0150db1c, e626e1ba, 5243628a, 3902f6f8, 7e1eabc6, f65a34cf, 67d2148f, 9eeae74b, 4aa67051 | MCP OAuth / Hermes Live Bridge (servir MCP a clientes Claude) | OBSOLETE para Slim (runtime-services; NAO portado) |
| a734a967, 86912624, 9b1ee213, 7536251f, b52564da, 85dfb415, c44157cb, 214a2252, 6920652d, 64ccfcab, 9abb8a3a, 75c6f8f9 | Prosper OS layer (channels/knowledge/context/integrations) | REPLACED_BY_COGNITIVE / OBSOLETE |
| 18846b85, be3aca57, 05673772, d1db2dad, d6380280, a58c540f, 3c7575cf, 44794b5a, a619d6df, 92cc684e, ccead600, 29673258, 1d99b82f, 05413e54 | runtime hardening / single-writer / self-improvement | OBSOLETE (superseded por capability-intelligence) |
| fae3ba2c | test contracts gateway | REVIEW (nao portado) |

`LOCAL_COMMITS_INVENTORIED=44/44`.

## 3. Dirty-tree inventory (Phase B)

`git status --short` = 10 M + ~50 untracked (1083 ins / 57 del):

| Arquivo | Classificacao | Evidencia |
|---|---|---|
| gateway/run.py (+451) | SLIM (2 sites) + GATEWAY/LEGACY (resto) | candidate usa SO o site slim (b6bcb3e7 tem 1 site) |
| hermes_cli/tools_config.py (+5) | SLIM (early-return) | PORTADO |
| hermes_cli/async_bridge.py, commands.py, plugins.py, agent/*, tests/* | LEGACY/EXPERIMENTAL | NAO portado |
| untracked: prosperos*.py, execution_*.py, contact_access.py, turn_intent_context.py | MOVE_TO_EXTENSION/OBSOLETE | fora do core |
| untracked: *.bak-*, .tmp_*, *_REPORT.md, HermesWork/, config/, docs/operations/, scripts/ | OBSOLETE/recovery | NAO portado |
| untracked: tests/gateway/*, tests/hermes_cli/* | REVIEW | NAO portado |

`DIRTY_FILES_INVENTORIED=60/60` · `DIRTY_UNIQUE_REQUIRED=1` (slim tools_config).

## 4. Component map (Phase C)

| Componente | Decisao | Forma |
|---|---|---|
| SLIM (0-tools normal chat) | KEEP_AND_PORT | source patch 2 edits (b6bcb3e7) |
| capability security fail-closed | MOVE_TO_EXTENSION | plugin `capability-intelligence` (externo) |
| Cognitive integration / /servidores | MOVE_TO_EXTENSION + MCP config | plugin + `mcp_servers.ProsperfySkills` |
| CRON foundation | MOVE_TO_EXTENSION | `cron_router.py` + toolset `cronjob` |
| Update guard / verify | MOVE_TO_OVERLAY | `ops/hermes/update/` (este repo) |
| Prosper OS / channels / knowledge | REPLACED_BY_COGNITIVE / OBSOLETE | NAO portado |

## 5. Candidate reconciliado (Phase D/E)

```
CANDIDATE_BASE_SHA=b6bcb3e7 (upstream limpo)
CANDIDATE_WORKTREE=/tmp/candidate-074 · branch=prosperfy-reconciled
CANDIDATE_SHA=e47c7f77 (upstream b6bcb3e7 + overlay prosperfy)
CANDIDATE_LOCAL_COMMITS=1 (prosperfy: slim zero-tool platform semantics · 2 files +5/-1)
CANDIDATE_UPSTREAM_FILES_MODIFIED=2
CANDIDATE_WORKTREE_CLEAN=YES
SLIM_PATCH.candidate = ops/hermes/update/slim.patch.candidate-b6bcb3e7 (1357 B, git apply --check=PASS)
```

### Reconstrucao (1 categoria por vez, cada uma testada)

1. **Minimal Slim** — patch 2 edits (`gateway/run.py` call site normal-chat +
   `tools_config._get_platform_tools` early-return p/ toolset vazio). Upstream b6bcb3e7 ja
   expoe `include_default_mcp_servers` nativamente (param) — patch reduzido a 1 linha por
   site. `SLIM_PATCH_VALID=YES`.
2. **Security fail-closed** — plugin externo `capability-intelligence` (sem `authorized=True`).
   `CAPABILITY_FAIL_CLOSED=PASS`.
3. **Cognitive / /servidores** — plugin + `platform_toolsets=[]` + `mcp_servers.ProsperfySkills`.
   Canary E2E PASS (4 resources, 0 LLM).
4. **Cron** — mantido na extensao (nao ampliado).
5. **Update guard** — patch do candidate adicionado; guard falha fechado em conflito/patch
   corrupto (provado em 0.7.3).

## 6. Testes no candidate (temp HERMES_HOME=/tmp/cand-home-074, isolado)

```
VERIFY_SLIM_CANDIDATE=PASS
  NORMAL_CHAT_TOOL_COUNT=0 · NORMAL_CHAT_SCHEMA_BYTES=0
  SLIM_CONFIG/PATCH_RUN_PY/PATCH_TOOLS_CONFIG/CAPABILITY_FAIL_CLOSED = PASS
GATEWAY_MODULE_IMPORT=PASS (gateway.run + tools_config importam limpos)
/SERVIDORES_CANDIDATE=PASS
  AUTHORIZED_RESOURCES_FOUND=4 · EXECUTED=4
  HERMES_LLM_PROVIDER_CALLS=0 · INPUT=0 · OUTPUT=0 · COST=0 · COGNITIVE_LLM_CALLS=0
  MCP_CALLS_TOTAL=12 (Black OK, Manager1 OK, Prosperfy OK, hostinger-one ERRO —
  docker ausente no host, idêntico ao live)
```

## 7. Cron — estado honesto

```
CRON_ROUTER_IMPLEMENTED=YES (cron_router.py, contrato 19 tests)
CRON_SPECIALIST_IMPLEMENTED=YES (toolset cronjob, 1 tool / 7923 B)
CRON_PRE_LLM_DISPATCH_WIRED=NO
CRON_REAL_USER_PATH_ACTIVE=NO
```
Nao ampliado nesta sprint (apenas preservado).
## 8. Future update simulation (Phase G)

```
upstream b6bcb3e7
+ commit sintetico future-upstream (92556ddf, avanca docs)
+ rebase do overlay prosperfy (9ce4b771 -> e47c7f77)
SMALL_OVERLAY_REBASEABLE=PASS (rebase 1/1 limpo, sem conflito)
SLIM_PATCH_REAPPLYABLE=YES (verify_slim=PASS apos rebase)
UPDATE_GUARD_COMPATIBLE=YES (verify_slim e o mesmo; guard falha fechado em conflito)
```

## 9. Delta atual vs candidate

```
LIVE: b54140f3 + 44 commits + dirty ~60 + run.py +451 linhas locais
CANDIDATE: b6bcb3e7 + 1 commit overlay (2 files, +5/-1) + worktree limpo
FORK_DIVERGENCE_REDUCED=YES (44 commits -> 1; 451 linhas -> patch 1357 B)
SOURCE_PATCH_REQUIRED=YES (Slim ainda depende de source behavior)
PATCH_RETIRE_CANDIDATE=NO (upstream b6bcb3e7 nao oferece 0-tools nativo: gateway=19,
  whatsapp=14 sem patch — verificado em canary 0.7.3)
```

## 10. Itens nao portados / aposentar

```
OLD_LOCAL_COMMITS_NOT_PORTED=43 (runtime hardening, MCP OAuth bridge, Prosper OS layer)
OLD_DIRTY_FILES_NOT_PORTED=~58 (prosperos/execution/contact_access/turn_intent + bak/reports)
Risco de remocao: medido — candidate roda /servidores + normal chat sem nenhum deles
  (canary 0.7.4). Legacy path direto MCP = REPLACED_BY_COGNITIVE, nao portado.
```

## 11. Rollout proposal (cutover em sprint/cutover posterior, NAO agora)

```
1. Human acceptance do candidate (branch prosperfy-reconciled, worktree /tmp/candidate-074).
2. Cutover controlado: parar gateway live -> trocar checkout para candidate (b6bcb3e7 +
   overlay commit) + manter HERMES_HOME (config/plugins/venv iguais) -> verify_slim -> start.
3. Runtime antigo b54140f3 retido p/ rollback (backup ja existe).
4. Rollback path: restaurar checkout antigo + service; prova 0.7.3/0.7.4 (canary).
```

## 12. Metricas finais

```
SPRINT074_CHECKPOINT=<pos commit/push>
LIVE_HERMES_SHA=b54140f3 · TARGET_UPSTREAM_SHA=b6bcb3e7
LIVE_LOCAL_COMMITS=44 · LIVE_DIRTY_FILES=60
LOCAL_COMMITS_INVENTORIED=44/44 · DIRTY_FILES_INVENTORIED=60/60
CANDIDATE_SHA=e47c7f77 · CANDIDATE_BASE_SHA=b6bcb3e7
CANDIDATE_LOCAL_COMMITS=1 · CANDIDATE_UPSTREAM_FILES_MODIFIED=2
CANDIDATE_WORKTREE_CLEAN=YES
NORMAL_CHAT_TOOL_COUNT=0 · NORMAL_CHAT_SCHEMA_BYTES=0
/SERVIDORES_FUNCTIONAL=PASS · /SERVIDORES_LLM_CALLS=0
AUTHORIZED_RESOURCES_FOUND=4 · EXECUTED=4
CAPABILITY_FAIL_CLOSED=PASS
CRON_ROUTER_IMPLEMENTED=YES · CRON_SPECIALIST_IMPLEMENTED=YES
CRON_PRE_LLM_DISPATCH_WIRED=NO · CRON_REAL_USER_PATH_ACTIVE=NO
SLIM_PATCH_VALID=YES · UPDATE_GUARD_CANARY=PASS · SMALL_OVERLAY_REBASEABLE=YES
OLD_LOCAL_COMMITS_NOT_PORTED=43 · OLD_DIRTY_FILES_NOT_PORTED=58
FORK_DIVERGENCE_REDUCED=YES · SOURCE_PATCH_REQUIRED=YES
LIVE_RUNTIME_UNTOUCHED=YES · NEW_DB_TABLES=0 · NEW_MIGRATIONS=0
NEW_WRITE_CAPABILITIES=0 · PRODUCTION_UNTOUCHED=YES · SECRET_EXPOSED=NO
MASTER_UNTOUCHED=YES · WORKTREE_CLEAN=YES

SPRINT_0_7_4_FINAL_GATE=PASS
LIVE_CUTOVER_AUTHORIZED=NO (sprint termina com candidate validado + plano; aguardar nova autorizacao)
RECOMMENDED_NEXT_ACTION=aceitacao humana do candidate + cutover controlado (sprint dedicada);
  apos cutover, update futuro = fetch upstream + rebase overlay pequeno + verify + guarded rollout.
```
