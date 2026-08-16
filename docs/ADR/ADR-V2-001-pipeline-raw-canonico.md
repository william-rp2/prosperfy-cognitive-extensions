# ADR-V2-001 — Pipeline RAW Canônico

**Status:** Aprovado (Sprint 0)  
**Data:** 2026-08-16  
**Decisores:** Prosperfy Cognitive V2  
**Relacionado:** `04-DADOS-RAW-RAG.md`, `ADR-V2-007`

---

## Context

A V2 define uma plataforma multi-tenant com RAW-first, RAG tenant-aware e separação entre dados estruturados (SQL) e conhecimento semi-estruturado (RAG). O repositório atual **não implementa** o pipeline canônico; contém apenas sync financeiro Pluggy→SQLite com campos `raw_data`. Documentação V2 e auditoria referem estruturas RAW legadas (`owner_raw_inbox`/`raw_items`) em Supabase **externo a este repo** — **NÃO CONFIRMADO** no tree local.

## Problem

Sem um pipeline canônico congelado, implementações futuras podem:

- duplicar caminhos de ingestão (Supabase legado vs canônico vs arquivos);
- misturar classificação com substituição da fonte;
- indexar conhecimento sem proveniência;
- quebrar migração do legado ativo.

## Decision

Adotar como **direção arquitetural congelada** o pipeline canônico:

```text
SOURCE
  ↓
conversations
  ↓
raw_messages
  ↓
message_attachments
  ↓
classify / extract / promote (determinístico primeiro; LLM só quando necessário)
  ↓
structured data / events / knowledge
  ↓
message_chunks
  ↓
message_embeddings
  ↓
retrieval (tenant-aware, com citação à origem)
```

**Regras congeladas:**

1. **RAW-first (R5):** toda entrada relevante preserva evidência original antes de enriquecimento.
2. **Collector sem LLM por padrão (R3):** ingestão, dedup, normalização mínima e regras são código.
3. **SQL vs RAG (R6):** tarefas, saldo, prazos, estados, métricas → SQL; decisões, atas, documentos, contexto → RAG.
4. **Obsidian:** workspace humano; conteúdo selecionado sincroniza como `documents` e indexa no RAG — **não** fonte operacional concorrente.
5. **Legado:** `owner_raw_inbox` / `raw_items` permanece **preservado e operacional** até equivalência funcional e reconciliação (**ADR-V2-007**).
6. **Sprint 0 / Fase 0:** **não implementar** ingestão RAW; apenas congelar contrato e estratégia de migração.

## Alternatives Considered

| Alternativa | Motivo de rejeição |
|-------------|-------------------|
| Manter só legado `raw_items` | Não escala multi-tenant nem alinha com conversations/messages |
| RAG como substituto de SQL | Viola R6; aumenta custo e imprecisão |
| Obsidian como source of truth operacional | Viola R4 e R5 |
| Implementar RAW na Fase 0 | Escopo proibido; Foundation primeiro |

## Consequences

**Positivas:**

- Caminho único para collectors futuros (Fase 2).
- Proveniência e auditoria rastreáveis.
- Migração legado→canônico pode ser incremental.

**Negativas:**

- Dual-path temporário (legado + canônico) até migração completa.
- Exige tenancy antes de ingestão em produção.

## Security Impact

- RAW contém PII; exige `tenant_id` em toda raiz e RLS (requisito congelado; mecanismo em **ADR-V2-002**).
- Attachments exigem storage tenant-scoped e ACL.
- Secrets nunca em RAW indexado para RAG (**ADR-V2-006**).

## Multi-Tenant Impact

Toda tabela do pipeline canônico deve propagar `tenant_id` por FK desde a raiz (`conversations`). Retrieval e RPC vetorial **devem** filtrar tenant — requisito congelado; implementação detalhada em ADR-V2-002.

## Cost/Token Impact

Collectors e promoção determinística **sem LLM por padrão**. Classificação/extração LLM apenas quando regras não bastarem — medido por telemetry (**09-OBSERVABILIDADE**).

## Migration Impact

Nenhuma migration RAW neste sprint. Estratégia dual-read/backfill documentada em **ADR-V2-007**. Writers canônicos só após gate Fase 2.

## Compatibility

- Finance SQLite `raw_data` / `raw_metadata`: padrão RAW-first **local** compatível conceitualmente; **não** unificado ao pipeline canônico até Fase 4 (**ADR-V2-008**).
- Capability Intelligence: sem pipeline RAW; inalterado no Sprint 0.

## Open Questions

1. Schema SQL exato de `conversations`/`raw_messages` no Supabase prod — **DECISÃO HUMANA NECESSÁRIA** (inventário externo).
2. Provedor de embeddings e dimensão do vetor — Fase 2.
3. Storage de attachments (Supabase Storage vs outro) — Fase 2.

## Acceptance Criteria

- [x] Pipeline canônico documentado e referenciado pela V2.
- [x] Legado explicitamente preservado.
- [x] Implementação RAW adiada à Fase 2.
- [ ] Inventário Supabase legado/canônico externo — pendente pós-Sprint 0.
