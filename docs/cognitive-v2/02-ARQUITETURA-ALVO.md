# Arquitetura Alvo

``` text
Channels / Apps
 WhatsApp | Hermes | Web/App | Email | APIs
                  |
                  v
          Cognitive Gateway
     auth | tenant | actor | intent
                  |
      +-----------+-----------+
      |           |           |
      v           v           v
    DATA       KNOWLEDGE    WORKFLOW
    SQL           RAG        ENGINE
      |           |           |
      +-----------+-----------+
                  |
          Capability Registry
                  |
       Policy + Resource Resolver
                  |
      +-----------+------------+
      |           |            |
 ProsperfySkill  MCP mercado  APIs próprias
```

## Cognitive Gateway

Responsável por identidade, tenant, actor, request/correlation id,
autorização inicial, roteamento para Data/Knowledge/Workflow e
superfície estável para clientes.

## Data Core

CRUD e queries determinísticas para projects, tasks, goals, finance,
incidents, contacts, clients, workflows e configurações.

## Knowledge Core

Documentos, mensagens promovidas, chunks, embeddings, retrieval
tenant-aware, citações para fonte original e filtros por
projeto/cliente/brand.

## Workflow Engine

Triggers, schedules, conditions, actions, outbox, retries controlados,
idempotência, follow-ups e audit trail.

## Capability Registry

Mapeia capability de negócio para uma ou mais tools/adapters. Hermes
conhece a capability de alto nível; o registry conhece a implementação.

## Interfaces iniciais sugeridas

-   `knowledge.search`
-   `data.query`
-   `task.manage`
-   `workflow.execute`
-   `capability.execute`
-   `status.get`

A API final pode usar REST/MCP internamente; o contrato deve permanecer
independente do Hermes.

## Modos de implantação

### Shared

Core compartilhado, tenant isolation via banco/RLS/namespaces/policies.

### Dedicated

Mesma aplicação com banco/secrets/runtime dedicados para cliente que
exigir isolamento físico.
