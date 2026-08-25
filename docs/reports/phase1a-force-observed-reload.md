# Phase 1A — Force Observed Reload (resultado: BLOCKED_HOST_TOOLING)

> Execução única (zero code changes). A ferramenta de acesso ao host deixou de
> executar/observar comandos systemctl — o stop não tem efeito.

## O que foi tentado (todos os passos §2–§6)

```
1. systemctl --user stop hermes-gateway.service (isolado) → (no output); estado inalterado
2. stop via script (stop_obs.sh) → (no output)
3. is-active após stop → ACTIVE (persistente)
4. MainPID → 3897783 (INALTERADO — o processo pré-fix continua em memória)
→ Não foi possível: OLD_MAINPID_DEAD / PORT_3000_FREE / NEW_MAINPID / reload observado /
  registry execution / pipeline real.
Per §2: "Se não conseguir observar: STOP. Não emitir start às cegas."
```

## Estado observável

```
HERMES_GATEWAY_ACTIVE=active · MainPID=3897783 (INALTERADO)
O gateway segue rodando o handler infra_read PRÉ-fix (dict) em memória.
O fix correto (str/json.dumps/tool_error) permanece no disco (sem reload).
```

## Veredito (regra estrita do gate)

```
OLD_MAINPID=3897783 · OLD_MAINPID_DEAD=NO (não observado; processo ativo)
NEW_MAINPID=— (reload não executável) · PORT_3000_FREE=— 
REGISTRY_PROSPERFY/BLACK/ALL=— · PIPELINE_ALL_SERVERS=— (não observáveis)
TOOL_RESULT_CONTRACT_ERROR=PRESENTE até reload real
CODE_CHANGED=NO (zero mudanças — conforme exigido)
READY_FOR_USER_TEST=NO
FINAL_STATUS=BLOCKED_HOST_TOOLING
PRODUCTION_UNTOUCHED=YES · MASTER_UNTOUCHED=YES
```

## Ação pendente (ferramenta host estável)

```
1. systemctl stop → OBSERVAR inactive + PID morto + porta 3000 livre
2. systemctl start → OBSERVAR NEW_MAINPID != 3897783 + bridge + QR_REQUIRED=NO
3. handler identity via registry real (co_filename + fonte)
4. registry: containers/Prosperfy · ports/Black · all → str, accepted
5. pipeline "Como estão meus servidores?" OBSERVADO
6. SÓ ENTÃO READY_FOR_USER_TEST=YES
```