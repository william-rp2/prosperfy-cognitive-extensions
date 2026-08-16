# Workflow Catalog Inicial

## WF-001 --- Customer promised asset

Trigger: promessa extraída.\
Condition: asset ainda ausente no vencimento.\
Action: lembrete amigável.\
Close: asset recebido/cancelado.

## WF-002 --- Task deadline reminder

Trigger: due_at aproximando.\
Condition: task não concluída.\
Action: notificar responsável.

## WF-003 --- Overdue task

Trigger: due_at ultrapassado.\
Action: marcar overdue derivado + incluir em digest/alerta.

## WF-004 --- Weekly planning

Trigger: schedule semanal.\
Action: montar dados SQL; LLM opcional apenas para síntese.

## WF-005 --- Daily plan

Trigger: schedule diário/manual.\
Action: listar planned/due/priority.

## WF-006 --- Important email → task

Trigger: classificação.\
Condition: action required.\
Action: criar TaskDraft/task.

## WF-007 --- Bill/payment reminder

Trigger: payable due.\
Condition: unpaid.\
Action: notificar usuários financeiros autorizados.

## WF-008 --- Infrastructure incident

Trigger: health rule violated.\
Action: incident + notify; diagnóstico LLM opcional.

## WF-009 --- Task completed → customer update

Trigger: task completed.\
Condition: customer-facing + notification enabled.\
Action: preparar mensagem e enviar conforme policy.

## WF-010 --- Proposal approval

Trigger: proposal preview ready.\
Action: solicitar approval; após aprovação publicar/enviar.

## Regras globais

-   todo workflow tem tenant;
-   idempotency;
-   timeout;
-   retry;
-   audit;
-   capability actions passam por policy;
-   nenhuma espera é mantida em memória de processo.
