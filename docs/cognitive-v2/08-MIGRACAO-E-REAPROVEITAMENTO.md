# Migração e Reaproveitamento

## Manter/Reutilizar

-   ProsperfySkill como execution layer.
-   Capability Intelligence: reaproveitar conceitos de PolicyEngine,
    ContextEnvelope, ToolGate, dedup/follow-up quando úteis, sem manter
    acoplamento obrigatório ao runtime Hermes.
-   Finance API/Web e integração Pluggy existentes: adaptar, não
    reescrever automaticamente.
-   Supabase atual: preservar estruturas e dados até plano de migração.
-   pgvector/HNSW existentes: reaproveitar após tenant-aware retrieval.
-   tasks/follow_ups e estruturas canônicas existentes: avaliar e
    adaptar.

## Simplificar

-   Hermes skills Cognitive duplicadas.
-   auto-load de contexto cognitivo.
-   catálogo MCP/tool excessivo.
-   múltiplos caminhos de memória/conhecimento.

## Legado

`owner_raw_inbox/raw_items` permanece operacional até migração
comprovada. Estruturas vazias/POCs só podem ser arquivadas após
inventário e decisão explícita.

## Estratégia de migração

1.  congelar contrato canônico;
2.  adicionar tenancy sem quebrar produção;
3.  criar adapters de leitura do legado;
4.  dual-read ou backfill controlado quando necessário;
5.  validar contagens/links/fontes;
6.  mudar writers para pipeline canônico;
7.  observar;
8.  somente depois considerar desativação do legado.

## Hermes

Não otimizar destrutivamente antes do Core existir. Depois, reduzir
contexto, skills e MCPs gradualmente, mantendo rollback.
