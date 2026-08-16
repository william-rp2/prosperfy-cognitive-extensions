# Integração Hermes ↔ Cognitive

## Objetivo

Transformar Hermes de "sistema que sabe tudo" em cliente fino do
Cognitive.

## Estado desejado

``` text
Hermes
 -> poucas tools Cognitive
 -> Cognitive Gateway
 -> SQL / RAG / Workflow / Capability
```

## Tool surface alvo

Inicialmente: - knowledge.search - data.query - task.manage -
workflow.execute - capability.execute - status.get

Pode ser refinada após métricas reais.

## Migração

1.  Cognitive Core operacional;
2.  criar client/adapter Hermes;
3.  profile experimental;
4.  remover auto-load cognitivo apenas no profile experimental;
5.  reduzir MCPs diretos;
6.  comparar respostas/custos;
7.  migrar funções uma a uma;
8.  somente então desativar duplicações.

## Contexto Hermes

Meta: - SOUL pequeno; - USER pequeno; - MEMORY mínima; - skills
mínimas; - tools mínimas; - conhecimento recuperado sob demanda.

## Não fazer

-   desligar skills antigas antes de equivalência;
-   dar 186 tools ao Hermes;
-   duplicar RAG no Hermes;
-   armazenar secrets em memória/prompt;
-   fazer Hermes decidir tabela/MCP primitive.

## Gate

-   perguntas operacionais equivalentes;
-   redução mensurada de tokens;
-   rollback;
-   nenhum capability bypass;
-   nenhum contexto crítico perdido.
