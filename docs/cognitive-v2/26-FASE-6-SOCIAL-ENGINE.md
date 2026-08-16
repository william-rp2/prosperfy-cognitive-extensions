# Fase 6 --- Social Engine

**Prioridade:** pós-MVP operacional.

## Objetivo

Planejar, gerar, aprovar e publicar conteúdo por marca/projeto com
isolamento de identidade visual e estratégia.

## Brand Pack

-   logo/assets;
-   paleta;
-   fontes/referências;
-   tom;
-   audience;
-   pillars;
-   prohibited content;
-   CTA rules;
-   approved examples.

## Estado

-   brands
-   brand_assets
-   content_strategies
-   content_calendars
-   social_posts
-   post_variants
-   approvals
-   publication_jobs
-   social_accounts

## Fluxo

``` text
calendar/request
 -> brief
 -> 3 options
 -> human approval
 -> final asset/caption
 -> schedule
 -> publish
 -> result
```

## Regras

-   aprovação humana inicial obrigatória;
-   credentials por tenant;
-   publicação via capability/MCP;
-   arte deve usar brand context recuperado, não prompt global;
-   não misturar assets de marcas.

## Gate

-   brand isolation;
-   calendário;
-   opções;
-   approval;
-   publicação;
-   rollback/cancel;
-   audit.
