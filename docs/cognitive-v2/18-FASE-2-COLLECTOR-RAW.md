# Fase 2A --- Collector e RAW

## Objetivo

Criar uma porta única e confiável para ingestão progressiva de WhatsApp,
e-mail, arquivos, áudio, reuniões e APIs.

## Regra

**Collector coleta; não raciocina.**

``` text
Source
 -> Adapter
 -> Ingestion Envelope
 -> Dedup
 -> RAW persistence
 -> Processing queue/state
```

## Modelo canônico

-   conversations
-   raw_messages
-   message_attachments
-   ingestion_sources
-   ingestion_events
-   processing_jobs / processing_state

O caminho legado `owner_raw_inbox/raw_items` deve ser preservado até
migração validada.

## Ingestion Envelope

Campos mínimos: - tenant_id - source_type - source_account/resource -
external_conversation_id - external_message_id - sender identity/ref -
occurred_at - received_at - content_type - raw payload reference -
normalized text quando aplicável - attachment refs - idempotency/dedup
key

## Princípios

-   RAW imutável sempre que possível;
-   preservar fonte;
-   attachments fora do prompt por padrão;
-   hashes/dedup;
-   timezone explícito;
-   retries não duplicam mensagem;
-   secrets e tokens de webhook não são RAW de conhecimento;
-   processamento pode falhar sem perder origem.

## Canais em ordem sugerida

1.  entrada manual/API de teste;
2.  e-mail;
3.  WhatsApp;
4.  arquivos;
5.  reuniões/transcrições;
6.  demais integrações.

## Processamento posterior

``` text
RAW
 -> deterministic rules
 -> extraction/classification if needed
 -> domain events
 -> tasks/finance/followups
 -> knowledge promotion
```

## Gate

-   ingestão real de pelo menos um canal;
-   dedup;
-   attachment;
-   source trace;
-   retry seguro;
-   tenant isolation;
-   legado intacto;
-   nenhuma mensagem perdida por falha de enrichment.
