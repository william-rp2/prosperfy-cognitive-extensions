# Fase 3 --- Workflow e Follow-ups

## Objetivo

Tirar lembretes, promessas, cobranças e rotinas da memória da LLM.

## Modelo

-   workflow_definitions
-   workflow_instances
-   workflow_steps
-   workflow_events
-   follow_ups
-   scheduled_actions
-   outbox
-   approvals
-   retry_records

## Motor

``` text
TRIGGER
 -> CONDITION
 -> ACTION
 -> RESULT
 -> NEXT STATE
 -> AUDIT
```

## Triggers

-   event;
-   schedule;
-   due date;
-   record changed;
-   inbound message;
-   manual;
-   future external condition via worker.

## Actions

Actions sempre usam Capability Registry + Policy. Workflow não chama MCP
diretamente.

## Exemplo

Cliente: "te mando as fotos daqui dois dias".

1.  extração gera promessa estruturada;
2.  cria requirement/follow_up;
3.  due_at;
4.  scheduler verifica se requirement foi cumprido;
5.  se sim: close;
6.  se não: prepara/envia lembrete conforme policy.

## Regras

-   scheduler não usa LLM para saber se o tempo chegou;
-   retries limitados;
-   outbox para efeitos externos;
-   idempotência;
-   dead-letter/failed state;
-   approval durável para CONFIRM;
-   timezone do tenant;
-   cancelamento e reschedule.

## Gate

-   follow-up real;
-   restart não perde schedule;
-   duplicate event não duplica ação;
-   CONFIRM espera aprovação;
-   retry controlado;
-   audit completo.
