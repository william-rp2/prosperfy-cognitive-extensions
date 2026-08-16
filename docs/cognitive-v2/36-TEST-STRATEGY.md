# Test Strategy

## Pirâmide

1.  Unit: domínio, policy, resolvers, parsers.
2.  Contract: adapters/MCP/API.
3.  Integration: Postgres/Supabase local/staging.
4.  End-to-end: canal → Cognitive → efeito.
5.  Security: cross-tenant, ACL, secret redaction.
6.  Cost regression: tokens/tool calls/latency.

## Gates obrigatórios

Nenhuma fase avança com testes críticos falhando.

## Multi-tenancy

Para toda raiz: - tenant A acessa A; - tenant A não acessa B; - worker
só acessa scope; - vector search não vaza B; - RPC não vaza B.

## Policy

-   ALLOW executa uma vez;
-   CONFIRM executa zero antes da aprovação;
-   DENY executa zero;
-   adapter não pode bypassar.

## Idempotency

Repetir webhook/message/action não duplica efeito.

## Failure

-   adapter timeout;
-   MCP down;
-   DB down;
-   retry;
-   partial composite capability;
-   restart de scheduler.

## RAG

Dataset de perguntas/respostas esperadas; medir recall/relevância e
cross-tenant.

## Finance

Fixtures sintéticas; somas, invoices, budgets e reconciliação
determinísticas.

## Definition of Done

Código + testes + docs + migration plan + observabilidade + gate report.
