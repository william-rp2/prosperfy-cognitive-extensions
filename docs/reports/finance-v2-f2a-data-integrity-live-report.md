# F2A DATA INTEGRITY LIVE REPORT

> Branch `dev/finance-v2-f2a` @ `f4f491c745c970766274f0f37abfdb3874bc1222`. Homolog (sandbox).
> Recovery: deploy exato + migration 007 + reprocess controlado. **LIVE_READY=YES**.

```
SOURCE_SHA=f4f491c745c970766274f0f37abfdb3874bc1222
API_RUNTIME_SHA=f4f491c7... · WEB_RUNTIME_SHA=f4f491c7... · SOURCE_MATCH=YES
SQLITE_BACKUP=PASS (3473408 B, prefix 45c2cd02787a0096)
MIGRATION_007=APPLIED (amount_in_account_currency_cents + account_currency_code)

API_TESTS=132 (21 files) · WEB_TESTS=41 (6 files) · BUILD=PASS · NEW_REGRESSIONS=0

--- REPROCESS ---
DRY_RUN_PROCESSED=1322 · WOULD_UPDATE=44 · FAILED=0
REPROCESS_PROCESSED=1322 · UPDATED=44 · FAILED=0
SECOND_REPROCESS_UPDATED=0 · SECOND_REPROCESS_FAILED=0 · IDEMPOTENT=PASS

--- PIX ---
C6_PIX_TOTAL=44 (paymentMethod=PIX no raw) · C6_PIX_OUT=30 · C6_PIX_IN=14
C6_PIX_GENERIC_REMAINING=0 (STILL_EXPENSE=0 · STILL_INCOME_GENERIC=0)
PIX_OUT_UI_LABEL="PIX enviado" · PIX_IN_UI_LABEL="PIX recebido"
  (canonical PIX_OUT/PIX_IN + paymentMethod PIX → formatter central → labels corretos)

--- CURRENCY ---
OPENAI (d740818f): ORIGINAL_AMOUNT=20.00 · ORIGINAL_CURRENCY=USD
  ACCOUNT_AMOUNT=109.54 · ACCOUNT_CURRENCY=BRL (backfilled do raw_data)
OPENAI_UI_PRIMARY="US$ 20,00" · UI_ACCOUNT_AMOUNT="~ R$ 109,54" (formatTransactionAmount)
USD_20_RENDERED_AS_BRL_20=NO
USD20_EFFECTIVE_AGGREGATE=109.54 (EFFECTIVE_ABS_AMOUNT_CENTS_SQL: foreign → account amount)
USD_SUMMED_AS_BRL=NO
TOTAL_EXPENSES_FIXED=YES (monthExpense 12292.65 → 13191.67)
CATEGORY_TOTALS_FIXED=YES · DASHBOARD_FIXED=YES · BUDGETS_FIXED=YES (mesmo SQL efetivo)
FOREIGN_MISSING_CONVERSION_COUNT=0 (24 USD tx com account amount)
FOREIGN_MISSING_INCLUDED_IN_BRL_TOTALS=NO (fail-closed: NULL quando sem conversão)

--- PRESERVED ---
EXPLICIT_IOF_LABEL="IOF" (1 · "IOF LIMITE CONTA") · HEURISTIC_IOF_AUTO_CLASSIFIED=0 (12 pares
  OPENAI BRL ficam como despesa — sem sinal explícito, não inventa IOF)
CREDIT_LABEL="Compra no cartão de crédito" (1145) · REFUND_LABEL="Estorno" (13) · TRANSFER_REGRESSION=NO
ALIAS_PRESERVED=YES (3 prefs: 'C6' · 'Bradesco INFINITE PRIME' + favoritos)
NOTES_PRESERVED=YES (0 annotations — sem lixo) · FILTERS_PRESERVED=YES · RESPONSIBLE_PRESERVED=YES
MEUPLUGGY_USER_FACING=NO

TX_COUNT_BEFORE=1322 · TX_COUNT_AFTER=1322 · ITEM_COUNT_BEFORE=3 · ITEM_COUNT_AFTER=3
CLARIFICATIONS_OPEN_BEFORE=1322 · CLARIFICATIONS_OPEN_AFTER=1322
CLARIFICATIONS_MULTI_OPEN_AFTER=0

REPROCESS_EXECUTED=YES · CODE_CHANGED=NO · PRODUCTION_TOUCHED=NO · SECRETS_EXPOSED=NO
CODE_READY=YES · LIVE_READY=YES · HUMAN_PASS=NO
HUMAN_BLOCKERS=none
```

## Observações
1. Fix PIX: normalizer agora usa paymentData.paymentMethod/operationType (metadados estruturados),
   não só descrição → 44 PIX C6 reais corretos (descrições C6 não têm "PIX").
2. Fix moeda: migration 007 + backfill via reprocess (amountInAccountCurrency extraído do raw_data);
   UI currency-aware (US$ + ~R$); agregados usam montante efetivo na moeda da conta; sem conversão =
   excluído (fail-closed).
3. IOF: regra conservadora preservada (só explícito → IOF; heurística por valor NÃO auto-classifica).
4. Frontend acessível em http://127.0.0.1:5175 p/ validação visual do owner.

STOP. F2B não iniciado. Não mergeado. Production intocada.