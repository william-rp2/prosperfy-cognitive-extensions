# Dados, RAW e RAG

## Pipeline canônico escolhido

A V2 adota como direção canônica:

``` text
SOURCE
  -> conversations
  -> raw_messages
  -> message_attachments
  -> classify/extract/promote
  -> structured data / events / knowledge
  -> message_chunks
  -> message_embeddings
  -> retrieval
```

`owner_raw_inbox/raw_items` permanece preservado como legado ativo
durante migração. Não apagar antes de equivalência funcional e
reconciliação.

## Collector

Collector coleta e persiste; não deve depender de LLM por padrão.

Etapas: 1. ingestão; 2. deduplicação; 3. normalização mínima; 4.
preservação RAW; 5. regras determinísticas; 6. extração/classificação
somente quando necessária; 7. promoção para domínios estruturados e/ou
knowledge.

## RAG

RAG deve ser tenant-aware e citar a origem. Requisitos mínimos: - chunks
determinísticos/versionados; - embeddings reais; - índice vetorial; -
retrieval RPC/API com filtro tenant; - filtros por
project/client/source/date; - top-k limitado; - testes de relevância; -
métricas de custo/latência.

## Obsidian

Obsidian é workspace humano, não fonte operacional concorrente. Conteúdo
selecionado é sincronizado como `documents` e indexado no RAG.

## Dados estruturados vs RAG

SQL: tarefas, saldo, orçamento, prazos, status, incidentes, faturas.
RAG: decisões, atas, documentos, contexto de cliente, regras textuais,
histórico semiestruturado.
