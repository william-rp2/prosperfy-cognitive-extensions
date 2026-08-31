# FINANCE V2 DATA INTEGRITY FORENSIC REPORT

> READ-ONLY. Branch `dev/finance-v2-f2a` (head 4d0369409c...; deploy 833e53f0). Nenhuma mutação.

## CURRENCY — OPENAI USD

```
OPENAI_TX_COUNT=24 (12 pares/mês: 12× USD + 12× BRL ~3.83)
Caso (d740818f, 19/08):
  PLUGGY_RAW_AMOUNT=20 · RAW_CURRENCY_CODE=USD · RAW_AMOUNT_IN_ACCOUNT_CURRENCY=109.54 (presente no raw_data)
  DB_AMOUNT=2000 cents · DB_CURRENCY_CODE=USD (amountInAccountCurrency NÃO persistido — sem coluna)
  API_AMOUNT=20 · API_CURRENCY_CODE=USD (retornado)
  UI_RENDERED="R$ 20,00" — money() da UI é HARDCODED currency:"BRL"

CURRENCY_LOST_AT=UI (money() ignora currencyCode) + amountInAccountCurrency perdido na INGESTION
HARDCODED_BRL=YES (App.tsx money(): toLocaleString('pt-BR',{currency:'BRL'}))
USD_AMOUNT_SUMMED_AS_BRL=YES (agregados somam amount_cents direto)
FOREIGN_CURRENCY_AFFECTS_TOTAL_EXPENSES=YES · BUDGETS=YES · DASHBOARD=YES
CURRENCY_SEVERITY=BLOCKER (subavalia despesas reais: USD 20 ≈ R$ 109,54 é contado como R$ 20)
```

## PIX — C6

```
C6_CHECKING_TX_COUNT=134 · C6_PIX_CANDIDATES=44
  PIX_WITH_PAYMENT_METHOD_PIX=44 (paymentData.paymentMethod="PIX")
  PIX_WITH_OPERATION_TYPE_PIX=44 (operationType="PIX")
  PIX_WITH_DESCRIPTION_SIGNAL=0 (descrições C6 NÃO contêm "PIX")
ENRICHMENT: 30× EXPENSE|UNKNOWN|OUT + 14× INCOME|UNKNOWN|IN → UI mostra "Despesa"/"Receita"
BEST_PIX_SIGNAL=paymentData.paymentMethod==='PIX' || operationType==='PIX' (metadados estruturados;
  descrição não é confiável no C6 Open Finance)
DETERMINISTIC_PIX=44 (com o sinal de metadados) · NEEDS_CONFIRMATION=0
PIX_CURRENTLY_MISCLASSIFIED=YES (44)

ROOT CAUSE: o normalizer seta paymentMethod/canonicalType PIX SOMENTE via hint de DESCRIÇÃO
  (hints.pix = /\bPIX\b/ na descrição). O rawPaymentMethod extraído de paymentData.paymentMethod
  é usado apenas p/ detecção de CREDIT_CARD/DEBIT_CARD — NUNCA para PIX. C6 (descrição sem PIX)
  cai em EXPENSE/INCOME.
```

## IOF

```
IOF_EXPLICIT_DESCRIPTION_COUNT=1 ("IOF LIMITE CONTA" → FEE → "IOF")
IOF_EXPLICIT_METADATA_COUNT=0 (nenhum sinal IOF em paymentData/operationType)
IOF_ONLY_HEURISTIC_COUNT=12 (pares OPENAI BRL ~3.83 — só valor, SEM sinal explícito → NÃO auto-IOF)
BILLS_IOF_DATA_AVAILABLE=NO (bills têm financeCharges mas 0 cargas IOF)
Comportamento atual JÁ é conservador e correto: só IOF explícito → FEE; demais → expensas.
```

## C6 CARDS

```
CURRENT_C6_CREDIT_ACCOUNTS=1 (conta consolidada "BANDEIRADO")
TX_CARD_METADATA_AVAILABLE=YES (creditCardMetadata.cardNumber="5619" presente nas tx)
CURRENT_ITEM_DISTINGUISHES_4_CARDS=NO (1 conta única; metadata traz 1 cardNumber apenas)
  → upstream consolida; não fabricar 4 cartões.
```

## CONCLUSION

```
ROOT_CAUSES=
  1) MOEDA: UI money() hardcoded BRL (ignora currencyCode) + amountInAccountCurrency não persistido
     na ingestão → USD exibido/somado como R$ (USD 20 → "R$ 20,00").
  2) PIX C6: normalizer depende do token "PIX" na descrição; ignora paymentData.paymentMethod/
     operationType=PIX → 44 PIX C6 reais viram "Despesa"/"Receita".
  3) IOF: regra atual (explícito apenas) é CORRETA; nada a corrigir — 12 pares heurísticos ficam
     como despesa (não IOF) conforme exigido.

MINIMAL_CODE_FIXES_REQUIRED=
  1) money()/formatação de valor: usar tx.currencyCode (mostrar USD/USD quando ≠ BRL; opcional
     converter via amountInAccountCurrency quando disponível).
  2) Ingestão/normalizer: persistir amountInAccountCurrency (coluna nova) e usar paymentData
     .paymentMethod / operationType para PIX (e transfer/boleto) — não só descrição.
  3) Reproc essar histórico após o fix (REPROCESS_REQUIRED=YES).

REPROCESS_REQUIRED=YES (após fixes de normalizer/moeda)
CODE_CHANGED=NO · DB_CHANGED=NO · PRODUCTION_TOUCHED=NO · SECRETS_EXPOSED=NO

CODE_READY=NO · LIVE_READY=NO · HUMAN_PASS=NO
STOP.
```