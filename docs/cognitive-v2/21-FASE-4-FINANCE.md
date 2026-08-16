# Fase 4A --- Finance

## Objetivo

Evoluir o POC financeiro existente para módulo tenant-aware,
reaproveitando Pluggy e frontend/backend úteis.

## Decision Gate obrigatório

Antes de migrar: - confirmar SQLite/API atual como source of truth real
do POC; - decidir destino PostgreSQL/Supabase; - definir estratégia de
migração; - confirmar modelo Pluggy e constraints de produção.

## Entradas

``` text
Pluggy
WhatsApp Finance
texto
áudio
nota/recibo
lançamento manual
```

## Modelo alvo

-   financial_accounts
-   financial_connections
-   financial_transactions
-   financial_transaction_enrichment
-   credit_cards
-   card_invoices
-   budgets
-   budget_categories
-   recurring_bills
-   payable_items
-   financial_documents
-   reconciliation_links

## Regra RAW/enrichment

Dados originais da instituição/Pluggy não são sobrescritos pela
classificação. Enrichment fica separado e auditável.

## WhatsApp ouvinte

Canal/grupo dedicado: - allowlist de participantes; - tenant
explícito; - áudio → transcrição; - documento → extraction; - texto →
extraction; - criar `TransactionDraft`; - confirmar quando ambíguo; -
persistir somente após validação necessária.

## ACL

Finance possui escopo sensível próprio. Perfis não autorizados não podem
consultar saldos, faturas ou budgets.

## Queries

"quanto ainda temos para mercado?" → SQL.\
"faltou pagar alguma conta?" → SQL/workflow.\
"por que gastamos mais este mês?" → SQL agregado + LLM opcional para
explicar.

## Gate

-   migração validada;
-   Pluggy sync;
-   transactions;
-   budgets;
-   invoices;
-   ingestão WhatsApp/manual;
-   ACL;
-   conciliação;
-   consultas determinísticas.
