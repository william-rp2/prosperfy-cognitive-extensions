# Fase 5A --- Email Intelligence

## Objetivo

Ler e-mails relevantes sem fazer o Hermes reprocessar a caixa inteira.

## Reuso

Usar capabilities de e-mail já existentes no ProsperfySkill/MCP.
Cognitive controla sync state, RAW, regras, classificação e
consequências.

## Pipeline

``` text
Mailbox
 -> incremental sync
 -> RAW
 -> deterministic filters
 -> classify/extract only when needed
 -> route:
      task
      finance
      offer
      knowledge
      follow-up
      ignore/archive marker
```

## Estado

-   email_accounts/resources
-   email_sync_state
-   email_message_links
-   email_classifications
-   email_actions

RAW canônico continua sendo a origem da mensagem; evitar banco paralelo
de conteúdo quando desnecessário.

## Regras

-   incremental cursor;
-   não reler toda caixa;
-   sender/domain rules;
-   thread awareness;
-   user-read state pode ser sinal, não única regra;
-   promoções só notificam se score/regras justificarem;
-   envio de e-mail = capability com policy;
-   anexos seguem pipeline de documentos.

## Gate

-   sync incremental;
-   dedup;
-   classificação;
-   e-mail → task;
-   e-mail → knowledge;
-   promoção relevante;
-   nenhum envio sem policy;
-   custo medido.
