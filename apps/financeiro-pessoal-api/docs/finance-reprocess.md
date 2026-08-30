# Finance — Historical Transaction Reprocess (F2A.1)

## Objetivo

Reprocessar transações **já persistidas** pelo pipeline oficial de classificação
(normalizer → `ClassificationService` → enrichment → clarifications idempotentes),
sem alterar dados-fonte da transação Pluggy.

Use após correções no normalizador (ex.: `CREDIT_CARD` + raw `DEBIT` → `CREDIT_PURCHASE`).

## Comando

```bash
cd apps/financeiro-pessoal-api

# Simulação — nenhuma escrita
npm run finance:reprocess -- --all --dry-run

# Reprocessamento real
npm run finance:reprocess -- --all

# Uma transação
npm run finance:reprocess -- --transaction-id <pluggy_transaction_id>
```

## Métricas retornadas (JSON)

| Campo | Descrição |
|-------|-----------|
| `processed` | Itens avaliados |
| `updated` | Enrichment derivado alterado |
| `unchanged` | Sem mudança semântica |
| `failed` | Erros isolados (batch continua) |
| `accountContextMissing` | Conta ausente — fail-closed, sem inventar payment method |
| `clarificationsCreated` | Novas clarifications abertas |
| `clarificationsReused` | Clarification open existente reutilizada |
| `dryRun` | `true` se `--dry-run` |

## Segurança

- **Não altera** `financial_transactions` (valor, data, merchant raw, Pluggy id, `last_synced_at`).
- **Não chama** Pluggy API nem altera cursores de sync.
- **Bloqueado** em `PLUGGY_ENV=production` salvo `FINANCE_REPROCESS_ALLOW=1` (autorização explícita do owner).
- **Não deployar** nem executar em Production sem autorização humana.

## Idempotência

Executar duas vezes seguidas deve resultar em `updated=0` e `clarificationsCreated=0` na segunda passagem.
