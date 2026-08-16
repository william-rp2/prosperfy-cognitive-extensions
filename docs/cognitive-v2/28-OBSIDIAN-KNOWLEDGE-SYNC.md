# Obsidian ↔ Knowledge Sync

## Papel

Obsidian permanece workspace humano de documentação. Supabase/Cognitive
é a camada consultável e operacional.

## Fluxo

``` text
Obsidian selected paths
 -> sync adapter
 -> documents
 -> versions
 -> chunks
 -> embeddings
```

## Regras

-   allowlist de pastas;
-   tenant/project mapping explícito;
-   hash/version;
-   não duplicar documento inalterado;
-   deleção/rename tratados;
-   frontmatter pode fornecer metadata;
-   secrets e notas privadas fora da allowlist;
-   Obsidian não é consultado diretamente pelo Hermes quando Cognitive
    estiver operacional.

## Conflitos

Por padrão, Obsidian é source of truth do documento humano sincronizado;
Cognitive armazena projeção/index. Dados operacionais nunca são
"sincronizados de volta" automaticamente para notas sem workflow
explícito.

## Gate

-   sync incremental;
-   versionamento;
-   tenant filter;
-   reindex;
-   source link;
-   nenhum arquivo fora da allowlist.
