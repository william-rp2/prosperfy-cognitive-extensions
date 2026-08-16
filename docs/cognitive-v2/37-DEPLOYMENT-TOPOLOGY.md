# Deployment Topology

## Shared inicial

``` text
Reverse Proxy
  -> Cognitive API
  -> Cognitive Worker/Scheduler
  -> PostgreSQL/Supabase
  -> external adapters/MCP
```

Pode começar em um único deploy lógico, mas API e worker devem ter
boundaries claros.

## Dedicated

Mesma aplicação/configuração com: - banco dedicado; - secrets
dedicados; - adapters/resources dedicados; - tenant único ou conjunto
dedicado.

## Ambientes

-   local
-   test
-   staging/homolog
-   production

Nunca usar produção como ambiente de desenvolvimento.

## Config

12-factor quando aplicável; secrets por referência; migrations
versionadas.

## Deploy

-   health/readiness;
-   migration step controlado;
-   rollback;
-   backup antes de mudanças destrutivas;
-   zero secrets em logs;
-   versões de API/capability registradas.

## Infra existente

Respeitar guias do servidor e não alterar Traefik/Docker/network/ports
existentes sem plano e autorização.

## Decision Gates

-   plataforma de hosting definitiva;
-   secret store produção;
-   Supabase shared vs dedicated por cliente;
-   worker topology conforme carga real.
