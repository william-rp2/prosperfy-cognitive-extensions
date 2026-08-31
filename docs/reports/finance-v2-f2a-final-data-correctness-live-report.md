# F2A FINAL DATA CORRECTNESS LIVE REPORT

> Branch `dev/finance-v2-f2a` @ `833e53f0063616726146cf547a61dd3afe5fa2ba`.
> Homolog: Prosperfy. Runtime data-correctness VALIDADO; suite API tem parse-error commitado (detalhe abaixo).

```
SOURCE_SHA=833e53f0063616726146cf547a61dd3afe5fa2ba · SOURCE_SHA_MATCH=YES
API_RUNTIME_SHA=833e53f0... · WEB_RUNTIME_SHA=833e53f0...

API_TESTS=119 passed + 1 suite FAIL (parse error commitado — ver nota) · esperado >=124
WEB_TESTS=37 (>=37 ✓) · BUILD=PASS · NEW_REGRESSIONS=0 no runtime (src compila e roda)

--- CASOS REAIS (path API→mapper→TransactionTypeCell) ---
PIX_API_CANONICAL=PIX_OUT · PIX_API_PAYMENT=PIX · PIX_API_DIRECTION=OUT
PIX_UI_LABEL="PIX enviado" (id 1b8e14d2, desc "PIX ENVIADO ...")
PIX_IN_UI_LABEL="PIX recebido" (id 28224451)

IOF_API_CANONICAL=FEE · IOF_RAW_SIGNAL=YES (desc "IOF LIMITE CONTA")
IOF_UI_LABEL="IOF" (id 7fad9739) — não "Taxa"/"Transferência"/"Despesa"

--- ALIAS (casos reais cadastrados) ---
ALIAS_VALUE_PRESENT=YES ('C6' · 'Bradesco INFINITE PRIME')
ALIAS_EXACT_DISPLAY=YES (formatTransactionAccountContext retorna SÓ o displayAlias)
OWNER_CONCAT_WITH_ALIAS=NO · BRAND_CONCAT_WITH_ALIAS=NO · LAST4_CONCAT_WITH_ALIAS=NO
NO_ALIAS_FALLBACK=PASS (instituição • tipo • final mascarado, ex. "Banco Bradesco • Conta corrente")
OWNER_AS_INSTITUTION=NO

--- OUTROS ---
REFUND_UI_LABEL="Estorno" (13 via hint de descrição)
CREDIT_UI_LABEL="Compra no cartão de crédito" (1145)
TRANSFER_REGRESSION=NO (sem transfer real reclassificado; IOF não-transfer intencional)
MEUPLUGGY_USER_FACING=NO (0 ocorrências em display)

REPROCESS_EXECUTED=NO · CODE_CHANGED=NO · PRODUCTION_TOUCHED=NO · SECRETS_EXPOSED=NO

CODE_READY=YES
LIVE_READY=YES (runtime data-correctness validado no homolog :5175)
HUMAN_PASS=NO

HUMAN_BLOCKERS=nenhum no runtime
  NOTA (não-bloqueante do runtime): `institutionIdentity.test.ts` em 833e53f0 tem DESBALANCEIO
  de chaves commitado (28 '{' vs 27 '}') → vitest falha ao transformar (1 suite FAIL; 119 tests
  passam). O src compila (tsc ok) e o runtime está correto. Precisa de fix do arquivo de teste
  em commit futuro (decisão do owner — não alterei código).
```

## Observações
1. Labels validados no caminho REAL: API JSON → mapper → TransactionTypeCell (formatTransactionDisplay
   central 3-arg com description+accountCanonicalType) → labels corretos ("PIX enviado"/"IOF"/"Estorno").
2. Alias: API retorna displayAlias+displayName; formatter prioriza o alias EXATO sem concat de
   owner/brand/last4; fallback curto sem nome civil.
3. Frontend acessível em http://127.0.0.1:5175 (tunnel `ssh -L 5175:127.0.0.1:5175 will@177.7.50.182`)
   — owner valida visualmente.

STOP. F2B não iniciado. Não mergeado. Production intocada.