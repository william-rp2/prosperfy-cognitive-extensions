# Gates e Critérios de Aceite

## Gate Foundation

-   [ ] tenant/actor obrigatório;
-   [ ] cross-tenant tests passam;
-   [ ] policy ALLOW/CONFIRM/DENY operacional;
-   [ ] audit trail completo;
-   [ ] ProsperfySkill chamado por adapter;
-   [ ] nenhum secret em logs/prompts;
-   [ ] telemetry de custo ativa.

## Gate Tasks

-   [ ] CRUD projects/tasks;
-   [ ] estados e histórico;
-   [ ] due date/assignee/priority;
-   [ ] queries hoje/semana/bloqueadas;
-   [ ] planejamento diário/semanal;
-   [ ] tenant isolation.

## Gate Collector/RAG

-   [ ] RAW preservado;
-   [ ] dedup;
-   [ ] attachments;
-   [ ] chunks/embeddings;
-   [ ] retrieval com tenant filter;
-   [ ] origem/citação recuperável;
-   [ ] nenhum dado cross-tenant.

## Gate Workflow

-   [ ] scheduler durável;
-   [ ] idempotency;
-   [ ] retries limitados;
-   [ ] outbox;
-   [ ] follow-up condicional;
-   [ ] approval para efeitos externos.

## Gate Finance

-   [ ] fonte da verdade definida;
-   [ ] Pluggy sync;
-   [ ] transações/budgets;
-   [ ] ingestão manual/WhatsApp;
-   [ ] ACL familiar;
-   [ ] consultas SQL corretas.

## Gate Infra

-   [ ] targets;
-   [ ] checks;
-   [ ] incident lifecycle;
-   [ ] ProsperfySkill reutilizado;
-   [ ] sem shell arbitrário;
-   [ ] alertas sem LLM contínua.

## Gate Email/Customer/Proposal

-   [ ] email RAW/classification/routing;
-   [ ] customer scope;
-   [ ] task/follow-up a partir de conversa;
-   [ ] proposal spec versionada;
-   [ ] templates determinísticos;
-   [ ] aprovação antes de envio/publicação.
