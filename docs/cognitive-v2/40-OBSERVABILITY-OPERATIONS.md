# Observability and Operations

## Logs

Structured logs com: - timestamp; - service; - tenant pseudonym/id; -
execution/correlation; - capability/workflow; - status; - error code.

Sem secrets ou conteúdo sensível desnecessário.

## Metrics

-   request rate/error;
-   latency;
-   DB;
-   queue/outbox;
-   workflow lag;
-   adapter/MCP availability;
-   token/cost;
-   RAG latency;
-   incident counts.

## Traces

Correlation id atravessa Gateway → workflow → capability → adapter.

## Operational dashboards

Grafana pode ser adicionado posteriormente. Métricas devem existir
independentemente da UI.

## Runbooks

Criar por componente: - DB unavailable; - ProsperfySkill unavailable; -
failed workflow; - stuck outbox; - RAG degradation; - auth failure; -
tenant isolation incident.

## Backups

Definir RPO/RTO por ambiente antes de produção multi-tenant.

## Alerts

Alertar por impacto, não por ruído. LLM não é necessária para detectar
threshold.
