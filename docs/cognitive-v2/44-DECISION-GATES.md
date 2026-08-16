# Decision Gates

Este documento centraliza decisões deliberadamente não congeladas.

## DG-001 --- RLS / Database Identity

**Deadline:** antes de Fase 0.2 ser considerada production-ready.\
Avaliar Supabase Auth/JWT, service identities, workers, connection
context e RPC.

## DG-002 --- Production Secret Store

**Deadline:** antes de armazenar credenciais reais de múltiplos
tenants.\
Opções devem ser comparadas por isolamento, rotação, audit e deploy.

## DG-003 --- Embedding Model / Dimension

**Deadline:** antes de migrations definitivas da Fase 2B.\
Considerar custo, qualidade, dimensão existente e estratégia de reindex.

## DG-004 --- Finance Source of Truth

**Deadline:** antes da Fase 4A.\
Confirmar SQLite/API atual, dados reais, frontend seed e destino.

## DG-005 --- Proposal Renderer Boundary

**Deadline:** antes da Fase 5C.\
Cognitive interno vs adapter/tool externa para PDF/PPTX/HTML.

## DG-006 --- Dedicated Deployment

**Deadline:** antes do primeiro cliente que exija isolamento físico.

## DG-007 --- WhatsApp Adapter

**Deadline:** antes do primeiro collector/customer agent WhatsApp
produtivo.\
Definir uso de ProsperWA/camada compatível sem acoplar Cognitive ao
gateway.

## Regra

O agente não decide silenciosamente um Decision Gate bloqueante. Deve
apresentar evidências/opções e aguardar decisão humana.
