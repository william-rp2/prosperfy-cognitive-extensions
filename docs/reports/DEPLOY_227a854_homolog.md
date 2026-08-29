# Deploy Homolog — integração 227a854, 4 tracks (29/08/2026)

```
BACKUP_EXISTS=YES      /home/will/backups/pre-227a854/cognitive-live
SOURCE_SHA_MATCH=YES   staging /home/will/deploy-staging/integration-227a854 @ 227a854
                       = origin/dev/integration-p0-p1
DEPLOY_HASH_MATCH=YES  gateway/app.py        28bfeb19a07de8c7c57670e2153b8d95
                       execution/orchestrator 0f360815b3968f7bdd74dbab7abe44ac
                       capability_router.py  0e2f856ddc07070e8adfdd70d56c84ad
RESTART_CLEAN=YES      prosperfy-cognitive-homolog-api — startup sem traceback
HEALTH=PASS            127.0.0.1:8800/health -> 200
CAPABILITIES_LOADED=35 2 infra + 15 work + 5 supabase + 3 browser + 10 finance
PRODUCTION_UNTOUCHED=YES
```

## Rotas em vigor no Cognitive

SUPABASE_OPS · WORK_MANAGEMENT · BROWSER · FINANCE · NORMAL (0 tools).
Matriz de colisão cruzada verificada nas 5: nenhuma frase de uma track cai na
rota de outra.

## Um dispatch, quatro tracks

Cada track chegou com um mecanismo próprio para o mesmo problema:

| track | mecanismo original |
|---|---|
| P1 | `adapters: dict` chaveado por capability.adapter |
| P0 | parâmetros nomeados `composio_adapter` / `registry_adapter` |
| BH | `adapter_registry: dict` |
| P2 | `RoutingSkillsAdapter` embrulhando skills_adapter, dispatch por prefixo |

Convergidos num registry único no ExecutionOrchestrator. Os outros nomes viram
aliases; `adapters/routing.py` segue versionado e testado, fora do caminho do
gateway.

Regra de injeção de actor: só adapters LOCAIS que gravam WorkEvent recebem
`_ctx_actor_id`. composio (MCP), browser_harness (worker HTTP) e finance_api
(HTTP) ficam de fora — o destino rejeita chave desconhecida. Esse era um bug
real do P1 isolado, que teria quebrado as chamadas das outras três tracks.

## Pendente

`hermes-gateway.service` tem o `capability_router.py` novo no disco com hash
conferido, mas NÃO foi reiniciado: o restart dessa unit está fora da
autorização (é o runtime do WhatsApp, não uma unit Homolog). Enquanto não
reiniciar, as 5 rotas não entram em vigor no chat e WHATSAPP_E2E fica bloqueado
para as 4 tracks.
