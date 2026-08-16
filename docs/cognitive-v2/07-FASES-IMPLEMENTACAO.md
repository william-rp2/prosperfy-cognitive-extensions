# Fases de Implementação

## Fase 0 --- Foundation

Objetivo: criar a fundação independente do Hermes.

Entregas: - ADRs e contratos; - estrutura do Cognitive Core/service; -
tenant model + RLS; - actor/resource context; - Cognitive Gateway; -
Capability Registry; - Policy Layer; - audit/execution trace; -
cost/token telemetry; - adapter inicial ProsperfySkill; - estratégia de
migração RAW; - testes cross-tenant.

**Gate:** nenhuma capability externa é executada sem
tenant/actor/policy/audit.

## Fase 1 --- Projects / Tasks / Planning

-   projects/tasks/state machine;
-   CRUD;
-   planning diário/semanal/mensal;
-   queries determinísticas;
-   interface mínima Hermes ↔ Cognitive.

**Gate:** "o que tenho hoje/semana?", criar/mover/concluir tarefa e
isolamento tenant funcionando.

## Fase 2 --- Collector + RAW + RAG

-   canonical ingestion;
-   dedup/idempotency;
-   attachments;
-   promoção do legado;
-   chunks/embeddings;
-   retrieval tenant-aware;
-   primeiro source real.

**Gate:** uma entrada real é preservada, indexada e recuperada com
fonte, sem cross-tenant.

## Fase 3 --- Workflow + Follow-ups

-   scheduler durável;
-   triggers/conditions/actions;
-   outbox;
-   retries;
-   idempotency;
-   follow-ups;
-   approval hooks.

**Gate:** promessa "em dois dias" executa fluxo correto sem LLM
observando continuamente.

## Fase 4 --- Finance + Infrastructure

### Finance

Adaptar backend/frontend existentes; definir fonte da verdade; Pluggy;
ledger/budgets; ingestão WhatsApp; ACL. \### Infra Compor tools VPS
existentes; targets/checks/incidents; alertas.

**Gate:** consultas financeiras estruturadas e health check de servidor
funcionam com custo LLM mínimo.

## Fase 5 --- Email + Customer + Proposal

-   Email Intelligence;
-   Customer Agent scoped;
-   ProposalSpec/templates/renderers;
-   integrações de envio e links.

**Gate:** e-mail gera tarefa quando necessário; cliente gera
follow-up/demanda; proposta completa passa por aprovação.

## Fase 6 --- Social Engine

Somente após estabilidade operacional, tenancy e approval workflow.
