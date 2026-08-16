# Observabilidade, Custos e LLM

## Motivação

O Hermes atual apresentou prompts muito grandes, tool surface extensa e
loops com consumo elevado. A V2 precisa medir custo como requisito de
produto.

## Métricas por request

-   tenant;
-   actor/profile;
-   route: code/sql/rag/llm/action;
-   tokens in/out;
-   tool schema tokens quando mensurável;
-   model/provider;
-   latency;
-   cache hit;
-   número de tool calls;
-   retries;
-   cost estimate;
-   correlation id.

## Budgets

Permitir budgets por tenant/profile/capability e circuit breakers.

## Regras

-   collectors: LLM off por padrão;
-   scheduler: LLM off por padrão;
-   health checks: LLM off;
-   SQL query conhecida: LLM opcional apenas para apresentação;
-   RAG: top-k pequeno e filtros fortes;
-   nenhuma tool surface global com centenas de schemas;
-   loops possuem max steps e limite de custo;
-   compressão/sumarização deve ser medida e não automática sem
    benefício comprovado.

## SLO inicial

Definir baseline antes de prometer percentuais de economia. Comparar
tarefas equivalentes antes/depois.
