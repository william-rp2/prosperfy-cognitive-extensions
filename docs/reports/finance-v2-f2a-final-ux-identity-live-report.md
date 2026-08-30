# F2A FINAL UX + FINANCIAL IDENTITY LIVE REPORT

> Branch `dev/finance-v2-f2a` @ `3ab8ce601546ec0f44cbba473909710aaf3b4305` (não mergeada).
> Homolog: Prosperfy. **LIVE_READY=YES** — F2A fechado tecnicamente.

```
SOURCE_SHA=3ab8ce601546ec0f44cbba473909710aaf3b4305 · SOURCE_SHA_MATCH=YES
SQLITE_BACKUP=PASS (backups/financeiro-pessoal-ux-*.sqlite3, 3452928 B, prefix 2b1912a27e4c0fad)
MIGRATION_006_APPLIED=YES (006_annotations_responsible.sql: financial_transaction_annotations +
  responsible_label em preferences)

API_TESTS=123 (20 files) · WEB_TESTS=27 (5 files) · BUILD=PASS · NEW_REGRESSIONS=0
TX_TOTAL_BEFORE=1320 · TX_TOTAL_AFTER=1320

DRY_RUN_PROCESSED=1320 · UPDATED=0 · FAILED=0 · DRY_RUN_WRITES=NO
FIRST_RUN_PROCESSED=1320 · UPDATED=0 · FAILED=0
SECOND_RUN_UPDATED=0 · SECOND_RUN_FAILED=0 · SECOND_RUN_IDEMPOTENT=PASS

--- TRANSACTION SEMANTICS (tabela real) ---
IOF_TABLE_DISPLAY=PASS ("IOF" ×1) · PIX_OUT_TABLE_DISPLAY=PASS ("PIX enviado" ×2)
PIX_IN_TABLE_DISPLAY=PASS ("PIX recebido" ×1) · REFUND_TABLE_DISPLAY=PASS ("Estorno" ×2)
CREDIT_TABLE_DISPLAY=PASS ("Compra no cartão de crédito" ×1143)
TRANSFER_TABLE_REGRESSION=NO (sem transfer real reclassificado; único hint transfer = caso IOF, intencional)

--- BANK / CARD IDENTITY ---
MEUPLUGGY_USER_FACING=NO (0 ocorrências em display; institutionIdentity filtra connectors de infra)
BANK_IDENTITY_VISIBLE=YES (C6 BANK · Banco Bradesco · Banco Santander · "Bradesco INFINITE PRIME")
CARD_ALIAS_VISIBLE=YES (alias/displayName suportado + aplicado)
CARD_LAST4_MASKED=YES (4017 · 5619 — final mascarado) · CARD_BRAND_VISIBLE=YES (VISA · MASTERCARD)
BANDEIRADO_VISIBLE=NO

MULTIPLE_CARDS_SAME_BANK_FOUND=YES (2 cartões sob o mesmo item) · MULTIPLE_CARDS_SEPARATED=YES
TRANSACTION_CARD_IDENTIFIER_AVAILABLE=YES (pluggy_account_id por tx)
CARD_LEVEL_ATTRIBUTION_SUPPORTED=NO (cartão físico/virtual/adicional = limitação de upstream/modelo —
  NÃO blocker do F2A)

--- EDIT / RESPONSIBLE ---
CARD_EDIT_CONTEXT=PASS (instituição + tipo + last4 + bandeira visíveis no contexto)
ALIAS_SAVE=PASS · ALIAS_PERSIST_RESTART=PASS · ALIAS_PERSIST_SYNC=PASS (preferências sobrevivem)
RESPONSIBLE_LABEL_SAVE=PASS · RESPONSIBLE_LABEL_PERSIST=PASS (persistido; limpo ao final)

--- NOTES ---
NOTE_CREATE=PASS · NOTE_VISIBLE=PASS · NOTE_SEARCHABLE=PASS (q= 1 hit)
NOTE_EDIT=PASS · NOTE_DELETE=PASS (0 rows restantes)
NOTE_PERSISTS_SYNC=PASS · NOTE_PERSISTS_REPROCESS=PASS (nota intacta após sync+reprocess)

--- SEARCH / FILTER ---
FREE_SEARCH_MERCHANT=PASS (q=pix → 3 hits) · FREE_SEARCH_NOTE=PASS (1 hit)
FREE_SEARCH_INSTITUTION=PASS · FREE_SEARCH_ALIAS=PASS (via filtros + testes)
MOVEMENTS_AUTOCOMPLETE=PASS · ACCOUNT_CARD_AUTOCOMPLETE=PASS · FILTER_COMPONENT_REUSABLE=YES
  (FinanceFilterBar + transactionFilters cobertos por testes; digitar termo reduz opções)
FILTER_PRESERVES_DISTINCT_CARDS=YES (2 cartões → 2 itens distintos)

--- REGRESSION ---
CREDIT_CARD_DISPLAYED_AS_DEBIT=0 · CREDIT_PURCHASE_DISPLAY=PASS · REAL_TRANSFER_DISPLAY=PASS
FAVORITE_PERSISTENCE=PASS · ALIAS_PERSISTENCE=PASS
CASH_AGGREGATION=PASS · CREDIT_LIMIT_IN_CASH=NO · CREDIT_LIMIT_IN_NET_WORTH=NO
OPEN_CLARIFICATIONS=1320 · MULTI_OPEN_CLARIFICATIONS=0
PLUGGY_ITEM_COUNT=3 · MULTI_ITEM_SYNC=PASS · SCHEDULER_INTERVAL=15
PT_BR_UI=PASS · RAW_ENUMS_VISIBLE=NO · POC_MENU_VISIBLE=NO · FAKE_SEED_VISIBLE=NO

PAYMENT_CAPABILITY_PRESENT=NO · SECRETS_EXPOSED=NO (bundle=0, logs=0)
CODE_CHANGED=NO · PRODUCTION_TOUCHED=NO
CODE_READY=YES · LIVE_READY=YES · HUMAN_PASS=NO
HUMAN_BLOCKERS=none
```

## Observações
1. Deploy ocorreu após o MCP voltar (session renovada); backup+checkout+testes+start+reprocess
   executados integralmente; migration 006 aplicada via mecanismo normal.
2. Reprocess de histórico: 0 updates (3ab8ce60 não muda normalizer) → idempotente, sem duplicatas,
   clarifications intactas.
3. Frontend disponível p/ HUMAN TEST final: `ssh -L 5175:127.0.0.1:5175 will@177.7.50.182` →
   http://127.0.0.1:5175 (IOF/PIX/Estorno, identidade de cartão, alias/responsável, notas, busca/filtros).

STOP. F2B não iniciado. Não mergeado. Production intocada.