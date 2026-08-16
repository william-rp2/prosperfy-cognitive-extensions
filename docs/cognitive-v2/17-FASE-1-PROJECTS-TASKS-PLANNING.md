# Fase 1 --- Projects, Tasks e Planning

## Objetivo

Criar a primeira funcionalidade operacional nativa do Cognitive:
organizar projetos, demandas, metas e planejamento sem depender de
memória da LLM.

## Modelo

### Project

-   tenant_id
-   id
-   name
-   slug
-   description
-   status: active \| standby \| archived
-   owner_actor_id
-   metadata

### Task

-   tenant_id
-   project_id
-   title
-   description
-   status: backlog \| planned \| in_progress \| blocked \| standby \|
    done \| cancelled
-   priority
-   assignee_actor_id
-   due_at
-   planned_for
-   completed_at
-   source_ref
-   parent_task_id
-   blocker_reason
-   metadata

### Complementares

-   task_history
-   task_dependencies
-   goals
-   milestones
-   planning_periods
-   planning_items
-   task_comments/notes

## Regras

1.  Estado operacional é SQL, não RAG.
2.  Toda alteração gera history/audit.
3.  Uma mensagem pode criar tarefa, mas a LLM apenas extrai um
    `TaskDraft`; o domínio valida e persiste.
4.  Queries "hoje", "semana", "bloqueadas", "atrasadas" são
    determinísticas.
5.  Não misturar projetos de tenants.
6.  Delegação exige actor válido no tenant.
7.  Agify será adapter futuro; Cognitive continua source of truth até
    decisão explícita diferente.

## APIs/capabilities mínimas

-   project.create/update/list/get
-   task.create/update/move/complete/list/get
-   task.query.today
-   task.query.week
-   task.query.blocked
-   task.assign
-   planning.daily
-   planning.weekly
-   planning.monthly
-   goal.create/update/list

## UX Hermes

"o que planejei para hoje?" → SQL → resposta.\
"adicione configurar Pluggy esta semana" → parse estruturado →
task.create.

## Gate

-   CRUD completo;
-   state machine validada;
-   history;
-   due dates;
-   assignees;
-   queries hoje/semana;
-   planejamento;
-   cross-tenant;
-   sem necessidade de RAG para operação básica.
