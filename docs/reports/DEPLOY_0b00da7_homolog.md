# Deploy Homolog — integração 0b00da7 (28/08/2026)

## Evidência exigida

```
BACKUP_EXISTS=YES     /home/will/backups/pre-integration-0b00da7/cognitive-live
                      /home/will/backups/pre-integration-0b00da7/capability_router.py.gate05.bak
SOURCE_SHA_MATCH=YES  staging /home/will/deploy-staging/integration-0b00da7 @ 0b00da7
                      = origin/dev/integration-p0-p1
DEPLOY_HASH_MATCH=YES orchestrator.py  0f360815b3968f7bdd74dbab7abe44ac (staging == live)
                      gateway/app.py   35516d8317c87f3baf0c3804dd3b4abc (staging == live)
                      capability_router 6034fe282294dd23647f566f9d38051f (staging == live)
RESTART_CLEAN=YES     prosperfy-cognitive-homolog-api.service — startup sem traceback
HEALTH=PASS           curl 127.0.0.1:8800/health -> 200
PRODUCTION_UNTOUCHED=YES
```

## Método

`git fetch` + `git worktree add --detach` criam uma árvore de staging isolada no
host; o deploy é `cp` seletivo dessa árvore para o diretório vivo. Nenhum
arquivo trafegou pelo contexto do agente e nenhum `git checkout` tocou a árvore
viva.

## Drift encontrado e respeitado

O gate-0.5 tem arquivos que divergem do baseline e NÃO pertencem a nenhuma das
tracks: `infra_service.py`, `server_views.py`, `transport/adapters/mcp_adapter.py`.
Foram deixados intactos — copiamos apenas os arquivos das tracks. O
`capability_router.py` vivo foi verificado byte-a-byte contra `b2bddbb` antes de
ser substituído: idêntico, logo seguro.

## Pendente

`hermes-gateway.service` recebeu o `capability_router.py` novo no disco mas
NÃO foi reiniciado — restart dessa unit está fora da autorização (ela é o
runtime do WhatsApp, não uma unit Homolog). Enquanto não reiniciar, as 4 rotas
novas não entram em vigor no chat.

## Reconciliação numérica do inventário

```
total_rows=36   unique_refs=36    (sem duplicidade, chave = project_ref)
disabled_by_owner=4
KEEPALIVE_TARGETS=32              (36 - 4)
  healthy = 30
  failed  =  2   DireitoHomolog, ProsperFootball-Prod (CONN_TIMEOUT_544)
  outros  =  0
  30 + 2 + 0 = 32 ✓
```

Causa da divergência anterior (16+14+2=32 contra TARGETS=31): `wioorhtdwnfujkrynxij`
foi contado duas vezes. Ele já estava entre os 15 keepalives bem-sucedidos da
primeira rodada, e foi somado outra vez quando o owner autorizou Production como
alvo. A chave única passou a ser `project_ref`, o que torna esse erro impossível
de repetir.
