# ADR-V2-007 — Migração RAW Legado

**Status:** Aprovado (Sprint 0)  
**Data:** 2026-08-16  
**Relacionado:** `04-DADOS-RAW-RAG.md`, `08-MIGRACAO-E-REAPROVEITAMENTO.md`, `ADR-V2-001`

---

## Context

A V2 adota pipeline canônico (`conversations` → `raw_messages` → …). Documentação (`00-README.md`, auditoria) indica:

- Supabase possui estruturas RAW **legadas ativas** (`owner_raw_inbox` / `raw_items`) — **NÃO CONFIRMADO** neste repositório (sem migrations Supabase no tree).
- Pipeline canônico novo **pouco utilizado** — referência externa.
- Este repo **não implementa** nenhum dos dois caminhos.

Regra V2 (**08-MIGRACAO**): legado permanece operacional até equivalência funcional e reconciliação. R16: sem mudanças destrutivas implícitas.

## Problem

Migração prematura ou dual-write não controlado pode:

- perder mensagens em produção;
- duplicar conhecimento (legado + canônico + Obsidian);
- quebrar collectors Hermes existentes **NÃO CONFIRMADO** neste repo.

## Decision

### Estratégia congelada (8 passos — de `08-MIGRACAO`)

```text
1. Congelar contrato canônico                    ← ADR-V2-001 (feito Sprint 0)
2. Adicionar tenancy sem quebrar produção        ← Fase 0.2+ / Supabase com aprovação
3. Criar adapters de leitura do legado           ← Fase 2
4. Dual-read ou backfill controlado              ← Fase 2
5. Validar contagens / links / fontes          ← Fase 2 gate
6. Mudar writers para pipeline canônico        ← Fase 2+
7. Observar                                      ← operação
8. Somente depois considerar desativação legado  ← DECISÃO HUMANA explícita
```

### O que NÃO fazer (Sprint 0 e até gate Fase 2)

- Apagar ou arquivar `owner_raw_inbox` / `raw_items`;
- Executar migrations Supabase prod;
- Alterar Hermes collectors **externos**;
- Implementar ingestão canônica no Core.

### Dual-path durante migração

```text
                    ┌─────────────────┐
  Sources ─────────►│ Legado (ativo)  │──► consumidores atuais
                    └─────────────────┘
                    ┌─────────────────┐
  Sources ─────────►│ Canônico (novo) │──► Cognitive V2
                    └─────────────────┘
                           │
                    reconciliação / backfill
```

### Adapters de leitura (futuro — Fase 2)

- `LegacyRawInboxReader`: read-only sobre legado;
- mapeamento documentado legado → canônico (campos, IDs, dedup keys);
- **sem write** no legado após cutover de writers.

### Idempotência e dedup (R12)

Chaves de dedup unificadas entre legado e canônico durante backfill — desenho Fase 2; conceito reutiliza `deduplication.py` (CI).

## Alternatives Considered

| Alternativa | Motivo de rejeição |
|-------------|-------------------|
| Big-bang cutover | Risco produção; viola R16 |
| Ignorar legado | Dados ativos em Supabase externo |
| Só legado forever | Não escala multi-tenant V2 |
| Migrar no Sprint 0 | Escopo proibido |

## Consequences

**Positivas:**

- Produção legada protegida.
- Caminho incremental testável.

**Negativas:**

- Período de duplicação operacional.
- Esforço de reconciliação.

## Security Impact

Backfill cross-tenant proibido; jobs tenant-scoped. Legado pode não ter RLS — adapter read-only com filtros explícitos.

## Multi-Tenant Impact

Canônico nasce tenant-aware. Legado pode precisar mapeamento tenant — **DECISÃO HUMANA NECESSÁRIA** após inventário Supabase.

## Cost/Token Impact

Dual-read temporário aumenta queries; aceitável vs perda de dados.

## Migration Impact

**Sprint 0:** zero migrations executadas. Supabase intocado.

## Compatibility

Obsidian: sync seletivo para `documents` — não substitui legado durante migração (**ADR-V2-001**).

## Open Questions

1. Inventário completo tabelas legado/canônico Supabase — **DECISÃO HUMANA NECESSÁRIA** (trabalho externo ao repo).
2. Volume e taxa de crescimento legado — dimensiona backfill.
3. Writers atuais do legado — quais serviços/Hermes jobs?

## Acceptance Criteria

- [x] Estratégia 8 passos congelada.
- [x] Legado preservado explicitamente.
- [x] Sprint 0 sem migração/implementação RAW.
- [ ] Inventário Supabase externo — pendente.
