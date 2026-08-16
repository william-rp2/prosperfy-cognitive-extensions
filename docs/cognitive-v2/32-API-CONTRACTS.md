# API Contracts --- Blueprint

## Convenções

Base: `/v1`

Headers: - Authorization - X-Tenant-Id - X-Actor-Id - X-Correlation-Id

Error envelope consistente: - code - message segura -
execution_id/correlation_id quando aplicável - details redigidos

## Foundation

-   `GET /health`
-   `GET /ready`
-   `POST /capabilities/{id}/execute`
-   `GET /executions/{id}`

## Projects

-   `/projects`
-   `/tasks`
-   `/tasks/{id}`
-   `/planning/today`
-   `/planning/week`
-   `/goals`

## Knowledge

-   `POST /knowledge/search`
-   `/documents`
-   `/documents/{id}`
-   `/documents/{id}/reindex`

## Ingestion

-   `POST /ingestion/messages`
-   `POST /ingestion/documents`
-   `GET /ingestion/{id}`

## Workflows

-   `/workflows`
-   `/workflow-instances`
-   `/follow-ups`
-   `/approvals/{id}/approve|reject`

## Finance

-   `/finance/accounts`
-   `/finance/transactions`
-   `/finance/budgets`
-   `/finance/invoices`
-   `/finance/summary`

## Infra

Preferir capability interface para ações/diagnóstico; endpoints CRUD
apenas para targets/check configs/incidents.

## Customer / Proposal

CRUD de estado + capabilities para efeitos externos.

## Regras

-   API não expõe secret real;
-   resource externo é lógico;
-   paginação;
-   filtros tenant-safe;
-   writes idempotentes quando necessário;
-   schemas versionados;
-   breaking change exige `/v2` ou versionamento de capability.
