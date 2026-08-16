# Fase 4B --- Infrastructure Monitor

## Objetivo

Monitorar servidores e aplicações usando ProsperfySkill como execution
layer.

## Não duplicar

Não implementar SSH/Docker/systemd/log reader no Cognitive se já existir
no ProsperfySkill.

## Modelo

-   infra_targets
-   health_check_definitions
-   health_snapshots
-   application_targets
-   incidents
-   incident_events
-   alert_rules

## Capabilities de negócio

-   infra.inspect
-   infra.health
-   infra.application_status
-   infra.logs
-   infra.disk_analysis
-   infra.incident.acknowledge

Primitives reais devem ser mapeadas ao catálogo ProsperfySkill antes de
implementação.

## Monitor

``` text
Scheduler
 -> deterministic checks
 -> snapshot
 -> threshold/rule
 -> incident
 -> notification
```

LLM não participa de health checks normais.

## Diagnóstico assistido

Quando houver incidente: 1. coletar métricas/logs necessários; 2.
limitar janela; 3. só então LLM pode resumir hipótese/causa; 4. qualquer
ação corretiva passa por policy.

## Grafana

Opcional. Pode ser adicionado como visualização/observabilidade sem ser
dependência do MVP.

## Gate

-   target tenant-aware;
-   checks;
-   snapshots;
-   incident lifecycle;
-   alert;
-   zero shell arbitrário;
-   ProsperfySkill reutilizado;
-   monitor contínuo sem LLM.
