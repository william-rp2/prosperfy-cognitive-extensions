# FINANCE V2 — F2A LIVE REPORT (FINAL)

> Branch `dev/finance-v2-f2a` @ `15f399dc3b633436bbf19472abd799e69cc737c6` (não mergeada).
> Homolog: Prosperfy (177.7.50.182), deploy `/home/will/deploy-staging/p2-finance-whatsapp`.

```
SOURCE_SHA=15f399dc3b633436bbf19472abd799e69cc737c6

SQLITE_BACKUP=PASS (backups/financeiro-pessoal-f2a-20260829222116.sqlite3, 3293184 B, prefix 7e20eeb1b2938288)
MIGRATION_004=APPLIED (004_financial_asset_types.sql via mecanismo normal) · CANONICAL_TYPE_COLUMN=YES
EXISTING_TRANSACTION_COUNT_BEFORE=1320 · AFTER=1320 (sem perda)

API_TESTS=92 passed (14 files) · WEB_TESTS=7 passed (3 files) · BUILD=PASS · NEW_REGRESSIONS=0
FINANCE_API_HEALTH=PASS (PID 360469) · FRONTEND_HEALTH=PASS (PID 360491, HTTP 200)

CANONICAL_ASSET_COUNTS=CHECKING_ACCOUNT:3, CREDIT_CARD:2, SAVINGS_ACCOUNT:1 (live, pós-sync normalizador F2A)
UNKNOWN_OR_OTHER_COUNT=0
CASH_AGGREGATION_LIVE=PASS (cash=4 cash-like; totalBalance 332.81 EXCLUI cartões)
CREDIT_CARD_SEPARATED_LIVE=PASS (2 cartões em grupo "Cartões", invoice separada; openCardBalance≠saldo)
CREDIT_LIMIT_IN_CASH=NO · CREDIT_LIMIT_IN_NET_WORTH=NO (aggregation: wealth=cash+investments)
INVESTMENT_SEPARATED_LIVE=NO_DATA (0 investimentos live) · RESERVE_LIVE=NO_DATA

INTEGRATIONS_GROUPING=PASS (Contas / Cartões / Investimentos / Outros — AssetGroup por canonical)

INVALID_UUID_GATE=PASS ("ID inválido.", HTTP 400)
DUPLICATE_ITEM_GATE=PASS ("Conexão já cadastrada.", outcome=already_registered, financial_items=3, sem dup)
NOT_FOUND_GATE=PASS ("Não foi possível acessar essa conexão.", outcome=not_accessible, sem persistência)
NEW_REAL_ITEM_ONBOARDING=HUMAN_BLOCKER_NO_NEW_ITEM (sem Item novo real disponível; A/B/C provados)

PT_BR_UI_LIVE=PASS (financePresentation.ts mapeia enums→pt-BR; served usa present* helpers)
RAW_ENUMS_VISIBLE=NO
LOCALE_PT_BR=PASS (money() = toLocaleString('pt-BR', {currency:'BRL'}) → R$)

POC_MENU_VISIBLE=NO · DEMO_NAV_VISIBLE=NO (rota /poc/pluggy gated por VITE_FINANCE_ADMIN_POC==="true")
FAKE_SEED_VISIBLE=NO (VITE_FINANCE_DEMO_MODE=false; branches demo gated no App.tsx)

PLUGGY_ITEM_COUNT=3 (Bradesco/C6/Santander preservados) · MULTI_ITEM_LIVE=PASS · SYNC_MANUAL=PASS
SCHEDULER_CONFIG_PRESERVED=YES (SYNC_ENABLED=true, INTERVAL=15, hasId/hasSec)
AUTO_SYNC_REGRESSION=NO (cron pós-F2A: 00:37/00:52/01:07 — items=3, acc=6, err=0, 15-min cadence)

ENRICHMENT_PIPELINE=PASS (1320) · CLARIFICATIONS_PRESERVED=YES (1320, MULTI_OPEN=0)
DUPLICATE_CLARIFICATIONS=NO

BILLS_MODEL_GAP=YES (declarado; não resolvido nesta fase)
F2A_BILLS_SEMANTICS_SAFE=YES (fatura ≠ saldo: MetricCard "Faturas em cartão — valor em aberto - não é
  saldo bancário"; cards fora de totalBalance; tela não inventa dados)

PAYMENT_CAPABILITY_PRESENT=NO (só paymentMethod/minimumPayment como campos; nenhum endpoint de
  pagamento/PIX/transferência/ordem)
SECRETS_EXPOSED=NO (token/pluggy em bundle=0, logs=0)

CODE_READY=YES
LIVE_READY=YES
HUMAN_PASS=NO

HUMAN_BLOCKERS=NEW_REAL_ITEM_ONBOARDING (opcional — não bloqueia demais gates)

PRODUCTION_TOUCHED=NO
WORKTREE_CLEAN=YES
```

## Observações

1. Asset-type canonical preenchido após sync (migration 004 adiciona colunas; normalizador F2A roda no
   sync e classifica as 6 contas reais: 3 CC, 2 cartão, 1 poupança — 0 unknown).
2. Separação cartão/conta provada em código (accountAggregation: CASH_ASSET_TYPES⊂wealth; CREDIT_CARD →
   invoice+limit separados) e em runtime (summary totalBalance exclui cartões).
3. Onboarding novo item: gates A/B/C (pt-BR, sem duplicata, sem persistência de acesso inválido)
   provados; fluxo D aguarda Item real novo do owner.
4. Acesso p/ validação humana: `ssh -L 5175:127.0.0.1:5175 will@177.7.50.182` → http://127.0.0.1:5175

STOP. F2A não mergeada. F2B não iniciado. Production intocada.