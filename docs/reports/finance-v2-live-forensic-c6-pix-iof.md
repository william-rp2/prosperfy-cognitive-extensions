# LIVE FORENSIC REPORT — C6 CARD ATTRIBUTION + PIX/IOF UI MISMATCH

> READ-ONLY. Nenhuma mutação. Branch `dev/finance-v2-f2a` @ `3ab8ce60` (esperado).

## C6 — DADOS REAIS

```
C6_ITEM_COUNT=1 (item 29393675-d11a-48c4-b516-4fd819b314aa)
C6_FINANCIAL_ACCOUNTS_COUNT=2 (1 checking "C6 BANK" + 1 credit "BANDEIRADO")
C6_CREDIT_CARD_ACCOUNTS_COUNT=1

RAW do Pluggy (GET /accounts?itemId=<C6>):
  RAW_ACCT 1: type=BANK subtype=CHECKING_ACCOUNT name="C6 BANK" (brand='' last4='')
  RAW_ACCT 2: type=CREDIT subtype=CREDIT_CARD name="BANDEIRADO" (brand='' last4='')
  → Pluggy retorna APENAS 1 conta de crédito para o Item C6.

Transações C6 (raw_data): NENHUM paymentData, NENHUM campo de cartão
  (last4/lastFour/cardBrand/cardType/cardholderName/virtual/additional ausentes).
Conta de cartão C6: sem brand/last4/owner no raw.

PLUGGY_EXPOSES_MULTIPLE_C6_CARDS=NO
PLUGGY_EXPOSES_CARD_PER_TRANSACTION=NO

CARD_SEPARATION_ROOT_CAUSE=
  O upstream (Pluggy/MeuPluggy) CONSOLIDA os 4 cartões físicos C6 do owner em
  UMA conta de crédito única ("BANDEIRADO", sem brand/last4/owner). O Finance
  modela exatamente o que o Pluggy expõe: 1 cartão C6. Não existe dado de
  cartão-por-transação (physical/virtual/additional) para separar.
```

## PIX / IOF — CASOS REAIS (via API `/api/finance/transactions`)

```
CASE=PIX  TX=1b8e14d2  RAW=DEBIT  desc_signal='PIX ENVIADO - DES ...'
  ENRICHMENT={canonical:PIX_OUT, payment:PIX, dir:OUT}
  API desc='PIX ENVIADO - DES ...' → formatter atual → "PIX enviado"  (CORRETO no homolog)
CASE=PIX_IN  TX=28224451  RAW=CREDIT  desc='PIX RECEBIDO - REM ...'
  ENRICHMENT={canonical:PIX_IN, payment:PIX, dir:IN} → "PIX recebido" (CORRETO)
CASE=IOF  TX=7fad9739  RAW=DEBIT  desc='IOF LIMITE CONTA'
  ENRICHMENT={canonical:FEE, payment:UNKNOWN, dir:OUT} → isExplicitIof(desc) → "IOF" (CORRETO)
  (demais 23 FEE sem token IOF → "Taxa" — comportamento correto)
```

## CAMINHO DA TELA / RUNTIME

```
MOVEMENTS_ENDPOINT=/api/finance/transactions
API_RETURNS_CANONICAL_TYPE=YES · PAYMENT_METHOD=YES · DIRECTION=YES · DESCRIPTION=YES
UI_USES_FORMAT_TRANSACTION_DISPLAY=YES (TransactionTypeCell → formatTransactionDisplay 3-arg,
  com description + accountCanonicalType; module servido CONFIRMA o código novo)
UI_USES_STALE_FIELD=NO · UI_HAS_PARALLEL_FORMATTER=NO

API_RUNTIME_SHA=3ab8ce601546ec0f44cbba473909710aaf3b4305
WEB_RUNTIME_SHA=3ab8ce601546ec0f44cbba473909710aaf3b4305
EXPECTED_SHA=3ab8ce601546ec0f44cbba473909710aaf3b4305
API_SHA_MATCH=YES · WEB_SHA_MATCH=YES
WEB_PROCESS_SHA=3ab8ce60 (PID 472371, iniciado 15:46 -03 pós-deploy; servindo módulos novos)

PIX_ROOT_CAUSE=
  O runtime homolog serve código/API corretos (label computado = "PIX enviado"). O owner
  visualiza o deploy PÚBLICO (https://minhasfinancas.prosperfy.com.br/), cujo bundle
  (index-C3-nXl6T.js) NÃO contém os novos labels (grep "Compra no cartão de crédito/PIX
  enviado/Estorno" = 0) → build antigo/desatualizado. Alternativa: cache do browser.
IOF_ROOT_CAUSE=
  Mesmo: homolog computa "IOF" corretamente; owner vê build público antigo (ou cache).
UI_CACHE_STALE=SIM quando visualizado via deploy público (bundle antigo); homolog ok.
```

## ROOT_CAUSE_SUMMARY

```
1) C6: upstream (Pluggy/MeuPluggy) consolida 4 cartões → 1 conta de crédito sem
   brand/last4/card-per-transaction. O Finance não tem como separar (limitação de modelo
   upstream, NÃO do app).
2) PIX/IOF: homolog computa labels corretos ("PIX enviado"/"IOF"). O mismatch observado vem
   de o owner ver o deploy PÚBLICO (minhasfinancas.prosperfy.com.br) com bundle ANTIGO —
   não o runtime homolog :5175 — ou cache do browser.
```

```
CODE_CHANGED=NO · PRODUCTION_TOUCHED=NO · REPROCESS=NO · MIGRATION=NO
STOP.
```