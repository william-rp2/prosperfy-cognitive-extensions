# Capability Catalog --- Domínios de Negócio

Este catálogo é de alto nível. O mapping para primitives reais deve ser
confirmado antes da implementação de cada adapter.

## Core

-   knowledge.search
-   data.query
-   status.get

## Projects

-   project.manage
-   task.manage
-   planning.query

## Workflow

-   workflow.execute
-   followup.manage
-   approval.manage

## Infrastructure

-   infra.inspect
-   infra.health
-   infra.logs
-   infra.application_status

## Email

-   email.search
-   email.read
-   email.send
-   email.thread_summary

## Finance

-   finance.sync
-   finance.transaction.create
-   finance.summary
-   finance.budget.status

## Notifications

-   notification.send

## Customer

-   customer.requirement.register
-   customer.reply.prepare
-   customer.status

## Proposal

-   proposal.generate
-   proposal.render
-   proposal.publish

## Social --- futuro

-   social.content.generate
-   social.schedule
-   social.publish

## Regra

Capability de negócio pode compor várias primitives. O Hermes não deve
receber automaticamente todas as primitives do ProsperfySkill.

## Definition

Cada YAML: - id/version/domain; - schemas; - adapter; - scopes; -
policy; - tenant support; - timeout/retry; - cost class; -
redaction/audit.

## Mapping

Criar arquivos `*-CAPABILITY-MAPPING.md` por domínio quando as
primitives reais forem confirmadas.
