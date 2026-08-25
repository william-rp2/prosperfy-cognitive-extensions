# Sprint 0.7.8.4 — HOST PRE-DEPLOY GATE (resultado: BLOQUEADO)

> Execução no VPS Prosperfy. Repo/work já pronto. Gate parou no PASSO 2 (hash mismatch).

## Gate — verificações executadas

```
1. fetch origin dev/sprint-0.7.8.4           → OK (branch obtida)
   commit c7906ec existente (rev-parse OK)    → OK
   blob ops/hermes/update/memory_on_demand.patch = a188fbbd (5178 B) → extraído p/ /tmp/0784.patch

2. PATCH_SHA256 (esperado 828ab28e...):
   /tmp/0784.patch          = be25a32d51d0ce1f9db4d7264dabe411b2d8f0123fe7d65565090bd460be9607
   blob do commit (direto)  = be25a32d51d0ce1f9db4d7264dabe411b2d8f0123fe7d65565090bd460be9607
   → o CONTEÚDO COMMITADO do patch NÃO corresponde ao hash esperado.
```

## Veredito

```
PATCH_SHA256=be25a32d... (esperado 828ab28e...) → MISMATCH
SAFE_TO_DEPLOY=NO
Per instrução §2 "Se hash diferente: STOP" → gate parado ANTES de git apply --check /
  conferência de overlap / estado runtime. Nada foi alterado.
```

## Estado (não coletado além do gate — STOP no passo 2)

```
Não aplicado patch · Não reiniciado · Não consolidado Memory.
PRODUCTION_UNTOUCHED=YES · SECRET_EXPOSED=NO · MASTER_UNTOUCHED=YES
```

## Próximo passo (decisão humana)

```
O conteúdo commitado em c7906ec difere do hash esperado. Possíveis causas: (a) o patch
  foi refeito/regenerado após a definição do hash; (b) hash esperado calculado de uma
  versão anterior. Recomendo conferir se ops/hermes/update/memory_on_demand.patch em
  dev/sprint-0.7.8.4 é o patch INTENCIONAL (ver README/apply_memory_on_demand.sh/commit
  message) e recalcular o hash esperado ANTES de prosseguir o gate.
```