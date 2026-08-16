# Data Model Completo --- Blueprint

Este documento é blueprint lógico; migrations reais devem ser criadas
fase a fase.

## Foundation

-   tenants
-   tenant_members
-   actors
-   service_identities
-   tenant_resources
-   tenant_integrations
-   credential_refs
-   capability_grants
-   capability_executions
-   audit_events
-   telemetry_events
-   idempotency_records

## Projects

-   projects
-   tasks
-   task_history
-   task_dependencies
-   goals
-   milestones
-   planning_periods
-   planning_items

## RAW / Conversations

-   conversations
-   raw_messages
-   message_attachments
-   ingestion_sources
-   ingestion_events
-   processing_state

## Knowledge

-   documents
-   document_versions
-   knowledge_items
-   message_chunks/document_chunks
-   embeddings
-   knowledge_sources

## Workflow

-   workflow_definitions
-   workflow_instances
-   workflow_steps
-   workflow_events
-   follow_ups
-   scheduled_actions
-   outbox
-   approvals

## Finance

-   financial_connections
-   financial_accounts
-   financial_transactions
-   financial_transaction_enrichment
-   credit_cards
-   card_invoices
-   budgets
-   budget_categories
-   recurring_bills
-   payable_items
-   financial_documents

## Infrastructure

-   infra_targets
-   application_targets
-   health_check_definitions
-   health_snapshots
-   incidents
-   incident_events
-   alert_rules

## Customer

-   clients
-   customer_contacts
-   customer_projects
-   customer_requirements
-   required_assets
-   customer_agent_profiles

## Proposal

-   proposal_specs
-   proposal_versions
-   proposal_templates
-   proposal_outputs
-   proposal_approvals

## Social

-   brands
-   brand_assets
-   content_strategies
-   content_calendars
-   social_posts
-   post_variants
-   publication_jobs

## Convenções

-   UUID/identificador consistente;
-   `tenant_id` em raízes multi-tenant;
-   timestamps UTC;
-   soft delete apenas onde houver requisito;
-   JSONB para metadata, não para esconder modelo relacional;
-   FK/indexes explícitos;
-   RLS onde exposto;
-   audit separado de history de domínio;
-   source refs para rastreabilidade.

## Legado

Não renomear/apagar tabelas atuais automaticamente. Criar mapping e
plano de migração em `38-MIGRATION-PLAN.md`.
