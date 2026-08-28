# MANUAL_ACTIVATION_REQUIRED — P0 Supabase Ops

Atualizado 28/08/2026 apos decisao do owner. Estado medido ao vivo via
Compose MCP, nao presumido.

## Panorama

```
SUPABASE_PROJECTS_TOTAL   = 35
DISABLED_BY_OWNER         =  4   nao voltam, nunca recebem keepalive
KEEPALIVE_TARGETS         = 31   35 - 4
ATIVOS COM KEEPALIVE OK   = 16   inclui Production read-only
UNREACHABLE               =  2
PAUSED aguardando owner   = 14
```

Production `wioorhtdwnfujkrynxij` entrou como alvo de keepalive por decisao
explicita do owner: SELECT minimo read-only autorizado, qualquer escrita
(INSERT/UPDATE/DELETE/DDL/migration/seed) permanece PROIBIDA. Keepalive
comprovado ao vivo.

## Nao aparecem nesta lista — DISABLED_BY_OWNER

- SaudeSync-Homologacao (`phnrvvezzejhqnbratbt`) — desativado de proposito, nao volta.
- SaudeSync (`tvjjaxsuvknvvaneusgy`) — desativado de proposito, nao volta.
- SaasCore (`caiunqdrzjlltaeaexqm`) — desativado de proposito, nao volta.
- BackSaas (`kfbfezzadqincqwvgsnz`) — desativado de proposito, nao volta.

Registrados no registry com `keepalive_enabled=false` e
`status=disabled_by_owner` (migration 007 criou esse estado justamente para
nao confundir com pausa por inatividade).

## Grupo A — banco inalcancavel (investigar, nao e pausa)

1. PROJECT_NAME=DireitoHomolog
   PROJECT_REF=vxcuwfnsdqbkipmlfnxv
   CURRENT_STATUS=ACTIVE_HEALTHY na API / banco inalcancavel
   FAILURE_REASON=Conexao recusada: status 544 connection timeout em 3 tentativas. Control plane saudavel nao implica banco alcancavel. Nao ha reativacao a fazer via API — e investigacao do titular.

2. PROJECT_NAME=ProsperFootball-Prod
   PROJECT_REF=xszptvnjgxsqnntqqisb
   CURRENT_STATUS=ACTIVE_HEALTHY na API / banco inalcancavel
   FAILURE_REASON=Mesmo padrao do DireitoHomolog: status 544 em 3 tentativas.


## Grupo B — pausados por inatividade (reativar no dashboard)

3. PROJECT_NAME=ProsperfyBusiness-Homologacao
   PROJECT_REF=hncjfxetdtcbiddegoxv
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

4. PROJECT_NAME=CasamentoPicante
   PROJECT_REF=eqgmqzgstjksfbfssnmg
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

5. PROJECT_NAME=CasamentoPicante-Homologacao
   PROJECT_REF=hydkdvedduaxqcbtupog
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

6. PROJECT_NAME=AVSCareer-Homologacao
   PROJECT_REF=rascxrzjsedqztfhcijv
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

7. PROJECT_NAME=ProsperAgents-Homologacao
   PROJECT_REF=vnoowkgaykhijocifyzh
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

8. PROJECT_NAME=ProsperMail-Homologacao
   PROJECT_REF=oafrffphaojjqdfmfvkp
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

9. PROJECT_NAME=GCM-Homologacao
   PROJECT_REF=aowcvvptwxauwodfmkti
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

10. PROJECT_NAME=ArenasEsportivas
   PROJECT_REF=mosewsitsiqpolabrwdt
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

11. PROJECT_NAME=ChacaraFacil
   PROJECT_REF=zxiwijqxcxshxcpstdko
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

12. PROJECT_NAME=ChacaraFacil-Homologacao
   PROJECT_REF=tnvihkmzzjbbmkqrzkoh
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

13. PROJECT_NAME=LancadorPro
   PROJECT_REF=ijzmqmbftmbwvdiqmhtm
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

14. PROJECT_NAME=MetodoManente
   PROJECT_REF=wrlqukqeyxisdxqcklrt
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

15. PROJECT_NAME=ProsperDance-Homologacao
   PROJECT_REF=zuaecyewemirhmqudfni
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

16. PROJECT_NAME=Rankanime
   PROJECT_REF=kwzfdbttlwsyhgrijngm
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.


## Depois que o owner terminar as reativacoes

Rodar discovery completo de novo (nao confiar nesta lista):
enumerar TODOS os projetos via Compose, confrontar registry x Compose,
identificar faltantes, e executar keepalive em todos os nao-disabled ate
`KEEPALIVE_SUCCESS = KEEPALIVE_TARGETS`. Nenhum projeto pode ficar de fora
em silencio.
