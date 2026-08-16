# Cost and Token Budgets

## Objetivo

Custo é requisito arquitetural.

## Métricas

Por request/execution: - tenant; - actor/profile; - route:
code/sql/rag/llm/action; - tokens input/output; - model/provider; -
estimated cost; - latency; - tool calls; - RAG calls; - retries; -
cache; - correlation/execution id.

## Regras

-   CODE/SQL/RULE não chamam LLM;
-   health checks: 0 LLM;
-   scheduler: 0 LLM por padrão;
-   collector: 0 LLM até enrichment necessário;
-   RAG top-k limitado;
-   tool schemas não são globais;
-   loops possuem max steps e max cost;
-   fallback não cria cascata ilimitada.

## Budgets

Configuração futura: - per tenant/day/month; - per profile; - per
workflow; - per capability; - per request.

## Circuit breaker

Ao exceder: - degradar para modelo barato quando policy permitir; -
adiar processamento não crítico; - bloquear loop; - notificar owner.

## Baseline

Medir antes/depois da migração Hermes. Não prometer percentual de
economia sem workload equivalente.
