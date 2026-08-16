# Migration Plan

## Objetivo

Migrar sem big bang.

## Princípios

-   preserve first;
-   adapters antes de reescrita;
-   backfill verificável;
-   dual-read/dual-write somente quando necessário e temporário;
-   contagens/checksums;
-   rollback.

## RAW

1.  congelar contrato canônico;
2.  mapear `owner_raw_inbox/raw_items`;
3.  criar adapter de leitura;
4.  definir backfill;
5.  migrar subset;
6.  validar source links;
7.  mudar writers;
8.  observar;
9.  desativar legado apenas após aprovação.

## Finance

1.  confirmar fonte atual;
2.  export/backup;
3.  mapping SQLite → Postgres;
4.  migration dry-run;
5.  reconciliar totais;
6.  cutover controlado;
7.  rollback window.

## Tasks/followups

Avaliar estruturas existentes e adaptar sem presumir compatibilidade.

## Hermes

Migração por profile/capability. Nunca remover todas as skills/MCPs
simultaneamente.

## Obsidian

Sync é projeção; não "migrar" vault para banco apagando origem.

## Gate de cada migração

-   backup;
-   dry-run;
-   reconciliation;
-   security;
-   rollback;
-   human approval.
