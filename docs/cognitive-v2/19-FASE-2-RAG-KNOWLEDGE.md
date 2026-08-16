# Fase 2B --- Knowledge e RAG

## Objetivo

Tornar o Supabase a camada consultável de conhecimento sem transformar
tudo em RAG.

## O que entra

-   documentos;
-   reuniões/transcrições;
-   mensagens promovidas;
-   decisões;
-   regras de negócio;
-   contexto de cliente/projeto;
-   materiais de marca;
-   conteúdo Obsidian selecionado.

## O que NÃO deve depender de RAG

-   saldo;
-   budgets;
-   tarefas;
-   prazos;
-   status;
-   incidentes;
-   permissões;
-   execução de workflow.

## Pipeline

``` text
Source record/document
 -> normalize
 -> deterministic chunk
 -> metadata
 -> embedding
 -> vector index
 -> tenant-aware retrieval
```

## Estruturas

-   documents
-   knowledge_items
-   message_chunks/document_chunks
-   embeddings
-   knowledge_sources
-   knowledge_versions

## Retrieval

Filtros obrigatórios: - tenant_id; - ACL/profile quando necessário.

Filtros opcionais: - project_id; - client_id; - source; - date range; -
document type; - brand.

## Requisitos

-   pgvector;
-   índice vetorial;
-   RPC/API tenant-aware;
-   top-k limitado;
-   source/citation recuperável;
-   versionamento;
-   delete/reindex;
-   avaliação de relevância;
-   observabilidade de tokens e latência.

## Embeddings

Modelo/dimensão é `DECISION GATE` antes da implementação. Não migrar
schema produtivo sem confirmar compatibilidade das estruturas
existentes.

## Gate

-   corpus real indexado;
-   retrieval correto;
-   nenhuma recuperação cross-tenant;
-   fonte disponível;
-   avaliação mínima de relevância;
-   custo medido;
-   RAG não é usado quando SQL resolve.
