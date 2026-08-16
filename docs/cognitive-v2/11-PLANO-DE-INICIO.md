# Plano de Início

## Passo 1 --- Commit somente de documentação

Adicionar estes documentos em `docs/cognitive-v2/`. Não alterar runtime,
banco ou Hermes neste commit.

## Passo 2 --- Criar ADRs da Fase 0

Antes de código, decidir e registrar: 1. pipeline canônico
`conversations/raw_messages/message_*`; 2. modelo tenant/actor/resource;
3. boundary Cognitive ↔ ProsperfySkill; 4. policy ALLOW/CONFIRM/DENY; 5.
API/Gateway independente do Hermes; 6. estratégia de secrets; 7.
estratégia de migração do RAW legado; 8. fonte da verdade do Finance.

## Passo 3 --- Branch da V2

Criar branch específica, sem mexer na instalação Hermes em produção.

## Passo 4 --- Spike mínimo da Foundation

Implementar somente um vertical slice:

``` text
Hermes/dev client
 -> Cognitive Gateway
 -> tenant/actor validation
 -> capability `infra.inspect`
 -> Policy ALLOW
 -> ProsperfySkill adapter
 -> audit
 -> resposta
```

Por que `infra.inspect`? A integração VPS já existe, é majoritariamente
read-only e prova a arquitetura sem criar um grande domínio novo.

## Passo 5 --- Testar custo e superfície

Comparar chamada direta atual do Hermes/MCP com Hermes → Cognitive →
capability composta. Medir tokens, tool schemas, latência e número de
chamadas.

## Passo 6 --- Foundation de banco

Depois do spike validar o boundary, implementar tenancy/RLS/audit de
forma incremental e testada. Não migrar todo o legado de uma vez.

## Passo 7 --- Primeiro módulo de negócio

Implementar Projects/Tasks/Planning como primeiro domínio nativo do
Core.

## Passo 8 --- Collector/RAG

Somente após tenancy e Core estáveis.

## Regra para agentes DEV

Cada fase deve começar com leitura dos ADRs e terminar com relatório de
gate. O agente não avança automaticamente para a próxima fase sem
aprovação humana.
