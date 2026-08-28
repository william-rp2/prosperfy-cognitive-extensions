# MANUAL_ACTIVATION_REQUIRED — P0 Supabase Ops

Verificado ao vivo em 28/08/2026 via Compose MCP. Todos os projetos sao Free
(confirmado pelo owner), portanto todos entram no inventario de protecao e
todos os ATIVOS recebem keepalive.

## Panorama

```
SUPABASE_PROJECTS_TOTAL   = 35
ACTIVE (keepalive OK)     = 15
UNREACHABLE               =  2   ACTIVE_HEALTHY na API, banco recusa conexao
PAUSED                    = 18   status INACTIVE confirmado projeto a projeto
UNKNOWN                   =  0
KEEPALIVE_SUCCESS         = 15/15 dos alcancaveis
KEEPALIVE_COVERAGE_ACTIVE = 15/17 = 88% dos marcados ACTIVE_HEALTHY pela API
```

Os 2 UNREACHABLE impedem `KEEPALIVE_COVERAGE_ACTIVE=100%`. Nao ha acao
autonoma segura: o control plane ja reporta o projeto como saudavel, entao
nao ha o que "reativar" pela API — a investigacao e do titular.

## Acao do owner

Reative manualmente no dashboard do Supabase os projetos abaixo. Depois disso
o programa pode ser retomado e o keepalive roda de novo sobre eles ate atingir
KEEPALIVE_SUCCESS=N/N.

Enquanto nao reativados, ficam classificados como
`BLOCKED_BY_MANUAL_SUPABASE_ACTIVATION` e nao impedem P1/P2/BH.

## Grupo A — banco inalcancavel (investigar, nao e pausa)

1. PROJECT_NAME=DireitoHomolog
   PROJECT_REF=vxcuwfnsdqbkipmlfnxv
   CURRENT_STATUS=ACTIVE_HEALTHY (API) / DB inalcancavel
   FAILURE_REASON=Banco recusa conexao: status 544 connection timeout em 3 tentativas. Control plane reporta saudavel, mas o Postgres nao aceita conexao via Compose MCP.

2. PROJECT_NAME=ProsperFootball-Prod
   PROJECT_REF=xszptvnjgxsqnntqqisb
   CURRENT_STATUS=ACTIVE_HEALTHY (API) / DB inalcancavel
   FAILURE_REASON=Banco recusa conexao: status 544 connection timeout em 3 tentativas. Mesmo padrao do DireitoHomolog.


## Grupo B — pausados por inatividade (restaurar no dashboard)

3. PROJECT_NAME=ProsperfyBusiness-Homologacao
   PROJECT_REF=hncjfxetdtcbiddegoxv
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Projeto pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

4. PROJECT_NAME=CasamentoPicante
   PROJECT_REF=eqgmqzgstjksfbfssnmg
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Projeto pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

5. PROJECT_NAME=CasamentoPicante-Homologacao
   PROJECT_REF=hydkdvedduaxqcbtupog
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Projeto pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

6. PROJECT_NAME=AVSCareer-Homologacao
   PROJECT_REF=rascxrzjsedqztfhcijv
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Projeto pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

7. PROJECT_NAME=ProsperAgents-Homologacao
   PROJECT_REF=vnoowkgaykhijocifyzh
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Projeto pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

8. PROJECT_NAME=SaudeSync-Homologacao
   PROJECT_REF=phnrvvezzejhqnbratbt
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Projeto pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

9. PROJECT_NAME=SaudeSync
   PROJECT_REF=tvjjaxsuvknvvaneusgy
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Projeto pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

10. PROJECT_NAME=ProsperMail-Homologacao
   PROJECT_REF=oafrffphaojjqdfmfvkp
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Projeto pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

11. PROJECT_NAME=GCM-Homologacao
   PROJECT_REF=aowcvvptwxauwodfmkti
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Projeto pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

12. PROJECT_NAME=ArenasEsportivas
   PROJECT_REF=mosewsitsiqpolabrwdt
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Projeto pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

13. PROJECT_NAME=ChacaraFacil
   PROJECT_REF=zxiwijqxcxshxcpstdko
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Projeto pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

14. PROJECT_NAME=ChacaraFacil-Homologacao
   PROJECT_REF=tnvihkmzzjbbmkqrzkoh
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Projeto pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

15. PROJECT_NAME=LancadorPro
   PROJECT_REF=ijzmqmbftmbwvdiqmhtm
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Projeto pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

16. PROJECT_NAME=MetodoManente
   PROJECT_REF=wrlqukqeyxisdxqcklrt
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Projeto pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

17. PROJECT_NAME=ProsperDance-Homologacao
   PROJECT_REF=zuaecyewemirhmqudfni
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Projeto pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

18. PROJECT_NAME=Rankanime
   PROJECT_REF=kwzfdbttlwsyhgrijngm
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Projeto pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

19. PROJECT_NAME=BackSaas
   PROJECT_REF=kfbfezzadqincqwvgsnz
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Projeto pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.

20. PROJECT_NAME=SaasCore
   PROJECT_REF=caiunqdrzjlltaeaexqm
   CURRENT_STATUS=INACTIVE (pausado)
   FAILURE_REASON=Projeto pausado por inatividade. Keepalive nao ressuscita projeto pausado — restore e acao manual do titular no dashboard Supabase.


## Depois da reativacao

Rode o keepalive novamente sobre os reativados. O registry ja tem os 35 com
`keepalive_enabled=true`, entao eles voltam a ser protegidos automaticamente
nas janelas 06:10 / 14:10 / 22:10 America/Sao_Paulo assim que o scheduler
estiver no ar.
