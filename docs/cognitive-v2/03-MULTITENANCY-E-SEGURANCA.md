# Multi-tenancy e Segurança

## Regra

Nenhum segundo cliente entra em produção antes de isolamento
cross-tenant comprovado.

## Entidades-base

-   `tenants`
-   `tenant_members`
-   `tenant_resources`
-   `tenant_integrations`
-   `credential_refs`
-   `capability_grants`

## Ownership

Propagar `tenant_id` por FK para raízes como projects, conversations,
raw_messages, documents, tasks, workflows, follow_ups, finance,
incidents, knowledge e audit.

## RLS

-   RLS tenant-aware em tabelas expostas.
-   RPC/vector search obrigatoriamente filtra tenant.
-   Service role restrita a workers mínimos; não usar como caminho
    genérico da aplicação.
-   Testes negativos de cross-tenant são obrigatórios.

## Recursos externos

Não basta `tenant_id` no banco. Hosts, mailboxes, projetos Supabase,
contas, sites e integrações devem ser resolvidos via `tenant_resources`
e `credential_refs`.

## Policies

-   `ALLOW`: leitura e operações seguras/idempotentes.
-   `CONFIRM`: envio, publicação, alteração externa, ações
    financeiras/infra relevantes.
-   `DENY`: shell arbitrário, destruição, bypass de policy, operações
    não cadastradas.

## Segurança financeira

Informação financeira tem escopo próprio e ACL explícita. Apenas membros
autorizados do tenant/família recebem consultas detalhadas.

## Customer Agent

Nunca recebe capabilities administrativas globais. Escopo: tenant +
cliente + conversa + conjunto explícito de ações.

## Secrets

Nunca em prompts, embeddings, logs ou documentos RAG. Guardar somente
referência segura.
