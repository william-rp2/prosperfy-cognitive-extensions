# F2A.1 HISTORICAL REPROCESS LIVE CLOSURE

> Branch `dev/finance-v2-f2a` @ `2ae79d1c945c16a2ea64d2b4bfc95a2bde6407e1` (não mergeada).
> Homolog: Prosperfy. **LIVE_READY=YES** — blocker crédito vs débito FECHADO via mecanismo oficial.

```
SOURCE_SHA=2ae79d1c945c16a2ea64d2b4bfc95a2bde6407e1

SQLITE_BACKUP=PASS (backups/financeiro-pessoal-reprocess-*.sqlite3, 3321856 B, prefix 102bcf89601893dd)
BACKFILL_MECHANISM=finance:reprocess (CLI oficial: tsx src/cli/reprocessTransactions.ts — invoca
  normalizer + ClassificationService + clarifications idempotentes; NÃO toca source rows/cursor/Pluggy)

API_TESTS=112 (18 files) · WEB_TESTS=9 (3 files) · BUILD=PASS · NEW_REGRESSIONS=0

TX_TOTAL_BEFORE=1320 · TX_TOTAL_AFTER=1320 (source preservado)
CREDIT_CARD_TX_TOTAL=1182

CREDIT_CARD_PAYMENT_METHOD_NULL_BEFORE=1182 · AFTER=0
CREDIT_CARD_DEBIT_PURCHASE_NULL_BEFORE=1146 · AFTER=0

DRY_RUN_PROCESSED=1320 · DRY_RUN_UPDATED=1317 · DRY_RUN_FAILED=0 · DRY_RUN_WRITES=NO
  (counts inalterados após dry-run: TX/ENRICH/CLARIF iguais)

FIRST_RUN_PROCESSED=1320 · UPDATED=1317 · UNCHANGED=3 · FAILED=0
FIRST_RUN_ACCOUNT_CONTEXT_MISSING=0 · CLARIFICATIONS_CREATED=0 · CLARIFICATIONS_REUSED=1320
SECOND_RUN_UPDATED=0 · SECOND_RUN_FAILED=0 · SECOND_RUN_CLARIFICATIONS_CREATED=0
SECOND_RUN_IDEMPOTENT=PASS (unchanged=1320)

OPEN_CLARIFICATIONS_BEFORE=1320 · AFTER=1320 · MULTI_OPEN_CLARIFICATIONS_AFTER=0

CREDIT_CARD_DISPLAYED_AS_DEBIT_AFTER=0 (CC tx com canonical DEBIT_PURCHASE ou payment DEBIT_CARD = 0)
CREDIT_PURCHASE_DISPLAY=PASS (1149 compras: paymentMethod=CREDIT_CARD, canonical=CREDIT_PURCHASE, dir=OUT)
DISPLAYED_AS_DEBIT_CARD=NO
  (semântica: CC asset + raw DEBIT → direction OUT + payment CREDIT_CARD + display "Compra no cartão
  de crédito"; UNKNOWN/EXPENSE → failsafe "Não identificado"; nunca DEBIT_CARD só por raw DEBIT)

BANDEIRADO_VISIBLE=NO · FINANCE_TECH_BANNER_VISIBLE=NO
CARD_INSTITUTION_VISIBLE=YES · CARD_NAME_MEANINGFUL=YES · CARD_VALUE_SEMANTICS=PASS

FAVORITE_PERSISTENCE=PASS (prefs sobreviveram ao reprocess) · ALIAS_PERSISTENCE=PASS
SYNC_PRESERVES_PREFERENCES=PASS (sync manual manteve prefs; prefs row intacta)

PLUGGY_ITEM_COUNT=3 · MULTI_ITEM_SYNC=PASS (items=3, acc=6, err=0) · SCHEDULER_INTERVAL=15

PAYMENT_CAPABILITY_PRESENT=NO · SECRETS_EXPOSED=NO (bundle=0, logs=0)

CODE_READY=YES
LIVE_READY=YES
HUMAN_PASS=NO

HUMAN_BLOCKERS=none

PRODUCTION_TOUCHED=NO · CODE_CHANGED=NO
```

## Observações

1. Mecanismo oficial executado 3× (dry-run + real + idempotência). Falhas=0 em todas; source rows,
   sync cursors e Items intocados; clarifications reutilizadas (nunca duplicadas).
2. Distribuição pós-reprocess: CREDIT_CARD=1176 · UNKNOWN=134 · TRANSFER=7 · PIX=3; CC-asset:
   CREDIT_PURCHASE OUT 1149, REFUND 13, CARD_PAYMENT 12, TRANSFER_OUT 6, INCOME 2.
3. Frontend disponível p/ validação visual final: `ssh -L 5175:127.0.0.1:5175 will@177.7.50.182` →
   http://127.0.0.1:5175 (Movimentações mostra compras de cartão como "Compra no cartão de crédito").

STOP. F2B não iniciado. Não mergeado. Production intocada.