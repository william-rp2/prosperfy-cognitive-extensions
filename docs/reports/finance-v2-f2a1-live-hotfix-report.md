# FINANCE V2 — F2A.1 LIVE HOTFIX REPORT

> Branch `dev/finance-v2-f2a` @ `b8c91417d1013d59435866e2c4bd0482898351cf` (não mergeada).
> Homolog: Prosperfy. **LIVE_READY=NO** — gate crítico (crédito vs débito) NÃO passa live.

```
SOURCE_SHA=b8c91417d1013d59435866e2c4bd0482898351cf
SQLITE_BACKUP=PASS (f2a1-2026082923???.sqlite3, 3301376 B, prefix 7791263b987f271a)
MIGRATION_005=APPLIED (005_financial_account_preferences.sql) · PREFERENCES_TABLE_PRESENT=YES
  (financial_account_preferences: pluggy_account_id, display_alias, is_favorite, created_at, updated_at)
DATA_LOSS=NO · TX_COUNT_BEFORE=1320 · AFTER=1320
API_TESTS=105 (17 files) · WEB_TESTS=9 (3 files) · BUILD=PASS · NEW_REGRESSIONS=0
FINANCE_API_HEALTH=PASS (PID 381666) · FRONTEND_HEALTH=PASS (PID 380468, HTTP 200)

=== GATE 6 — CRÉDITO vs DÉBITO: FAIL (live) ===
RAW_DEBIT_IS_DIRECTION_ONLY=YES (semântica: raw DEBIT=saída; pipeline F2A.1 deriva pagamento do asset)
CREDIT_PURCHASE_DISPLAY=FAIL — 1146 transações de CREDIT_CARD (canonicalType=DEBIT_PURCHASE, raw DEBIT)
  têm enrichment.payment_method=null → formatTransactionDisplay → "Compra no débito"
DISPLAYED_AS_DEBIT_CARD=YES (live)
UNKNOWN_PAYMENT_FAILSAFE=PASS (EXPENSE→"Não identificado", em código + teste)
DEBIT_CARD_REGRESSION=NO_DATA (nenhum asset DEBIT_CARD live)

ROOT CAUSE (2 fatores, sem alterar código nesta fase):
 1) classificationService F2A.1 injeta accountCanonicalType → normalizer produz paymentMethod=CREDIT_CARD
    CORRETO — mas o sync só re-processa o delta do Pluggy (11 tx) e os 1146 DEBIT_PURCHASE históricos
    NÃO foram re-enriquecidos (payment_method permanece null do normalizador F2A).
 2) formatTransactionDisplay(enrichment, rawType) NÃO tem fallback para o canonical do ASSET da tx
    (o accountId→canonicalType existe nas accounts, mas não é usado no display).

=== GATE 7 — IDENTIDADE DO CARTÃO: PASS ===
BANDEIRADO_VISIBLE=NO (defaultAccountLabel filtra nomes técnicos) · CARD_INSTITUTION_VISIBLE=YES
CARD_NAME_MEANINGFUL=YES ("MeuPluggy — Cartão de crédito"; "VISA INFINITE PRIME")

=== GATE 8 — SEMÂNTICA DOS VALORES: PASS ===
CARD_VALUE_SEMANTICS=PASS (grupo Cartões valueLabel="Fatura em aberto"; cartão NÃO usa "Saldo")
CREDIT_LIMIT_AS_BALANCE=NO · UNSAFE_TOTAL_VISIBLE=NO

=== GATE 9 — BANNER TÉCNICO ===
FINANCE_TECH_BANNER_VISIBLE=NO (disclaimer "Open Finance (Pluggy)" / "15 min" / "Sincronização automática" REMOVIDO)
  Obs.: "Finance V2" permanece como NOME do app (sidebar/header), não como banner técnico.

=== GATES 10-12 — FAVORITOS / APELIDO: PASS ===
FAVORITE_TOGGLE=PASS · FAVORITE_SORT_FIRST=PASS (order=0) · FAVORITE_PERSISTENCE=PASS (restart API mantém)
ALIAS_CREATE=PASS ("Teste F2A") · ALIAS_PERSIST=PASS (restart mantém) · ALIAS_REMOVE=PASS
ALIAS_FALLBACK=PASS ("MeuPluggy — Cartão de crédito") · cleanup ok (sem "Teste F2A" residual)
SYNC_PRESERVES_PREFERENCES=PASS (sync manual 3 items manteve fav+alias)

=== GATE 13 — PT-BR: PASS ===
PT_BR_UI=PASS · RAW_ENUMS_VISIBLE=NO (presentation mapeia; account display pt-BR)
  (a label errada "Compra no débito" do gate 6 NÃO é enum cru — é semântica incorreta de pagamento)

=== GATE 14 — REGRESSION F1/F2A: PASS ===
PLUGGY_ITEM_COUNT=3 · TX_COUNT=1320 · MULTI_ITEM_SYNC=PASS (items=3, err=0)
SCHEDULER_INTERVAL=15 · SCHEDULER_CONFIG_PRESERVED=YES (SYNC_ENABLED=true, creds presentes)
CASH_AGGREGATION=PASS · CREDIT_LIMIT_IN_CASH=NO · CREDIT_LIMIT_IN_NET_WORTH=NO
POC_MENU_VISIBLE=NO · DEMO_NAV_VISIBLE=NO · FAKE_SEED_VISIBLE=NO
ENRICHMENT_PIPELINE=PASS (1320) · CLARIFICATIONS_PRESERVED=YES · MULTI_OPEN_CLARIFICATIONS=0

=== GATE 15 — SECURITY: PASS ===
PAYMENT_CAPABILITY_PRESENT=NO (só campos paymentMethod/minimumPayment; sem endpoints de pagamento)
FINANCE_API_TOKEN/PLUGGY_CLIENT_ID/PLUGGY_CLIENT_SECRET em bundle=0 · logs=0 · read-only bancário

CODE_READY=YES
LIVE_READY=NO (blocker: CREDIT_PURCHASE_DISPLAY/DISPLAYED_AS_DEBIT_CARD)
HUMAN_PASS=NO

HUMAN_BLOCKERS=nenhum (o blocker é de dados/display, não humano)

PRODUCTION_TOUCHED=NO · WORKTREE_CLEAN=YES
```

## Decisão do owner (não alterei código no host)

O pipeline F2A.1 está correto para transações NOVAS/atualizadas. Para o gate 6 passar live, precisa UMA de:
1. **Back-fill**: re-enriquecer as 1320 tx existentes com o normalizador F2A.1 (via mecanismo da app), OU
2. **Fallback de display**: formatTransactionDisplay usar o canonical do ASSET (accountId→canonicalType)
   quando enrichment.payment_method for null (mostrar "Compra no cartão de crédito" p/ tx de cartão).

STOP. F2B não iniciado. Não mergeado. Production intocada.