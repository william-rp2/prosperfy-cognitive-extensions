# Fase 5B --- Customer Agent

## Objetivo

Criar agentes externos simples e seguros, com contexto menor que o Owner
Hermes.

## Princípio

Customer Agent não é um "superagente". É uma interface scoped sobre
Cognitive.

``` text
Customer Channel
 -> Customer Profile
 -> Cognitive
    -> Knowledge
    -> Requirements
    -> Tasks
    -> Follow-ups
    -> Approved Capabilities
```

## Estado adicional

-   clients/customers
-   customer_contacts
-   customer_projects
-   customer_requirements
-   required_assets
-   customer_conversations
-   customer_agent_profiles

## Casos

### "Qual o link do site?"

Consulta structured data/knowledge e responde.

### "Dá para colocar orçamento?"

Cria `TaskDraft`/requirement, confirma registro e encaminha ao Kanban.

### "Te mando fotos daqui 2 dias"

Cria required_asset + follow_up.

### Implementação concluída

Evento `task.completed` pode disparar notificação ao cliente, se
configurado.

## Segurança

-   apenas tenant/cliente/conversa permitidos;
-   sem Finance pessoal;
-   sem infra admin;
-   sem tools globais;
-   respostas baseadas em conhecimento autorizado;
-   escalonamento humano para dúvida/risco.

## Tone/communication

Tom configurável por tenant/brand, mas regras de negócio ficam fora do
prompt.

## Gate

-   respostas scoped;
-   requirement;
-   task;
-   follow-up;
-   completion notification;
-   escalation;
-   teste de acesso indevido.
