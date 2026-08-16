# WhatsApp Channels

## Objetivo

Usar WhatsApp como canal de entrada/saída, não como banco ou cérebro.

## Perfis iniciais

### Owner/Operations

Mensagens para o assistente pessoal.

### Finance Group

Ouvinte allowlisted para gastos/documentos/áudios e consultas
autorizadas.

### Customer Agent

Conversa scoped por cliente.

### Project Collectors

Grupos/projetos selecionados para bugs, ideias, demandas e evidências.

## Ingestão

WhatsApp adapter → canonical RAW → router/processors.

## Identidade

Mapear: - channel/account; - conversation/group; - participant; -
tenant; - actor/contact; - project/client quando configurado.

## Regras

-   allowlist;
-   não responder automaticamente em collector-only;
-   mídia preservada por referência;
-   áudio transcrito assíncronamente;
-   saída passa por policy/workflow;
-   mensagens duplicadas não geram tarefas duplicadas;
-   Customer Agent não herda permissões do Owner.

## ProsperWA

A conectividade pode usar ProsperWA/adapters existentes, mas o Cognitive
não deve assumir responsabilidades de gateway WhatsApp.

## Gate

-   inbound;
-   dedup;
-   participant mapping;
-   finance group;
-   customer scope;
-   collector-only;
-   outbound aprovado.
