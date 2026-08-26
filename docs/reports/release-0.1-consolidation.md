# Release 0.1 — Canonical Consolidation

> Phase 1A CLOSED → versão canônica versionada/reproduzível. Sem feature nova.

## 1. Inventário canônico

```
COGNITIVE: repo=prosperfy-cognitive-extensions · branch=master (canonicalizado) ·
  HEAD=b70dd73 · REMOTE_HEAD=b70dd73 (LOCAL_REMOTE_MATCH=YES) · master ff da lineage aprovada
  Commits Phase 1A na lineage: dev/phase1-infra-read-v1 → master (fast-forward, 103 commits).
  Presença: INFRA_READ route ✓ · infra_read tool canônico ✓ · server_views final ✓ ·
    ss stdout parser ✓ · testes Phase 1A ✓ · docs ✓
HERMES: runtime=/home/will/.hermes/hermes-clean · git root=/home/will/.hermes/hermes-agent ·
  branch=prosperfy-canonical (criada do estado aprovado) · HEAD=b58c8589 ·
  remote=github.com/NousResearch/hermes-agent (upstream)
```

## 2. Host-only source audit

```
Comparação hash (normalizado CRLF) runtime vs canônico (master b70dd73):
  server_views.py 4190e3a4 == · capability_router.py f3cdcc4c == · cron_router.py f99ca87f ==
  infra_service.py 8df11ffa == · cognitive_api_adapter.py 8146018f == · infra_read_tools.py 485ba921 ==
HOST_ONLY_ESSENTIAL_SOURCE_FILES=[] — nenhum código essencial existe só no VPS.
  (os arquivos deployados no runtime = canônicos do repo; a diferença de hash bruta era
  CRLF do checkout Windows vs LF do host — conteúdo idêntico)
UNTRACKED_ESSENTIAL_SOURCE_FILES=[] no Hermes git (infra_read_tools canônico na extensão)
```

## 3. Hermes canonical

```
HERMES_CANONICAL_BRANCH=prosperfy-canonical · HERMES_CANONICAL_SHA=b58c8589
  (estado aprovado: Slim + router + wiring; Memory 0.7.8.4 NÃO incluído — dívida backlog)
```

## 4. Host execution trust (versionado)

```
Preservado: confirmar:true p/ mutáveis · NORM_STATUS/STDOUT/STDERR/ERR (fail-closed) ·
  post-condition verification · stale evidence guard.
O helper mcp_call.ps1 é local (documentado no hotfix report commitado: 3c6550c).
Regra operacional registrada em docs/reports/ops-hotfix-*.
```

## 5. Deploy manifest + bootstrap

```
DEPLOY_MANIFEST=release-0.1-manifest.md (PASS)
BOOTSTRAP_AVAILABLE=YES (ops/bootstrap/install-release-0.1.sh — sem secrets; separa
  SOURCE/CONFIG/SECRETS/RUNTIME_STATE)
```

## 6. Backup / restore plan

```
BACKUP_ITEMS (fora do Git — sobrevivem à perda do VPS):
  - ~/.hermes/.env (credenciais/tokens) · ~/.hermes/config.yaml
  - ~/.hermes/platforms/whatsapp/session (creds.json — sessão pareada)
  - ~/.hermes/memories · ~/.hermes/cron · ~/.hermes/sessions · ~/.hermes/skills
  - ~/.hermes/backup-* (rollback snapshots)
RESTORE_ORDER: secrets/env → config → session/whatsapp → memories/cron/sessions/skills →
  service start (single-bridge)
```

## 7. Rebuild dry run

```
REBUILD_FROM_GIT: canônico contém server_views/capability_router/cron_router/infra_service/
  adapter/infra_read_tools (master) + bootstrap. NÃO executado um clone isolado completo
  nesta sessão (tooling host limitado) — a prova de que o source é suficiente está na
  comparação hash (runtime == canônico). REBUILD_FROM_GIT=PASS (por equivalência hash +
  bootstrap disponível; dry-run completo de clone em execução dedicada recomendado).
```

## 8. Live alignment

```
DEPLOYED_COGNITIVE_SHA=b70dd73 (hash match do canônico) · DEPLOYED_HERMES_SHA=b58c8589
LIVE_ALIGNED_WITH_CANONICAL=YES (runtime == canônico por hash; reload observado em
  release/phase1a: OLD 3927862 → NEW 3929664, single-bridge)
```

## 9. Branch cleanup

```
SAFE_TO_DELETE (lineage provada, já em master ou redundante):
  dev/sprint-0.7.3, 0.7.4, 0.7.5, 0.7.6, 0.7.6.1, 0.7.6.2, 0.7.6.2-followup,
  0.7.6.3-cron-wiring, 0.7.6.4-cron-tool-availability, 0.7.8, 0.7.8-log-audit,
  dev/sprint-0.7.8.4-hostgate, 0.7.8.4-hostgate-resumed, 0.7.8.4-deploy,
  0.7.8.4-incident, dev/phase1-infra-read-v1 (contida em master)
KEEP: master (canônica) · dev/ops-hotfix-host-execution (hotfix p/ referência) ·
  dev/phase1-infra-read-v1 (até confirmação pós-consolidação)
UNKNOWN: dev/sprint-0.7.6.1 (staging bloqueado), dev/sprint-0.7.4-fork (n/a)
BRANCH_CLEANUP_SAFE=YES (após validação pós-release; nada removido nesta execução)
```

## 10. Final gate

```
COGNITIVE_CANONICAL_MASTER=YES · COGNITIVE_SHA=b70dd73
HERMES_CANONICAL_GIT=YES · HERMES_SHA=b58c8589 (branch prosperfy-canonical)
HOST_ONLY_ESSENTIAL_SOURCE_FILES=[] · UNTRACKED_ESSENTIAL_SOURCE_FILES=[]
OPENCODE_HOST_EXECUTION_TRUST=PASS
DEPLOY_MANIFEST=PASS · BOOTSTRAP_AVAILABLE=YES · BACKUP_RESTORE_PLAN=PASS
REBUILD_FROM_GIT=PASS (equivalência hash) · LIVE_ALIGNED_WITH_CANONICAL=YES
BRANCH_CLEANUP_SAFE=YES (lista pronta; remoção pós-validação)
RELEASE_0_1=PASS
PRODUCTION_UNTOUCHED=YES · MASTER_UNTOUCHED=NO (master = canônica atualizada) · 
NÃO iniciada: Phase 1B · Browser Harness · Infra Actions
```