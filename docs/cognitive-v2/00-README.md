# Prosperfy Cognitive V2

## Objetivo

Transformar a estrutura atual Hermes + Prosperfy Cognitive +
ProsperfySkill em uma plataforma cognitiva barata, previsível,
multi-tenant e vendável, sem reconstruir integrações já existentes.

## Princípio central

**Código determinístico → SQL → regras → RAG → LLM.**

A LLM interpreta o que é ambíguo ou não estruturado. Processos
conhecidos devem ser executados por código, SQL, policies, scheduler e
workflows.

## Papéis

-   **Hermes:** interface conversacional e raciocínio sob demanda.
-   **Prosperfy Cognitive:** fonte operacional, RAW, RAG, workflows,
    policies, tenancy, capability registry e auditoria.
-   **ProsperfySkill/MCP:** integração e execução de tools. Não duplicar
    VPS, e-mail, Supabase, notificações ou outras capabilities
    existentes.
-   **Supabase/PostgreSQL:** estado operacional canônico e conhecimento
    indexado.
-   **Obsidian:** workspace humano de conhecimento; conteúdo relevante
    pode ser sincronizado/indexado no Cognitive.

## MVP prioritário

1.  Projects / Tasks / Planning
2.  Collector + RAW + RAG
3.  Workflow / Follow-up Engine
4.  Finance
5.  Infrastructure Monitor
6.  Email Intelligence
7.  Customer Agent
8.  Proposal Engine
9.  Social Engine --- fase futura

## Documentos

-   `01-PRINCIPIOS-E-REGRAS.md`
-   `02-ARQUITETURA-ALVO.md`
-   `03-MULTITENANCY-E-SEGURANCA.md`
-   `04-DADOS-RAW-RAG.md`
-   `05-CAPABILITIES-POLICIES-MCP.md`
-   `06-MVP-FUNCIONALIDADES.md`
-   `07-FASES-IMPLEMENTACAO.md`
-   `08-MIGRACAO-E-REAPROVEITAMENTO.md`
-   `09-OBSERVABILIDADE-CUSTOS-E-LLM.md`
-   `10-GATES-E-CRITERIOS-DE-ACEITE.md`
-   `11-PLANO-DE-INICIO.md`
-   `12-FASE-0-PLANO-TECNICO.md`
-   `13-SPRINT-0-ADR-REVIEW.md`
-   `16-FASE-0-FOUNDATION-SPEC.md`
-   `41-MASTER-IMPLEMENTATION-PLAN.md`
-   `42-MASTER-ACCEPTANCE-GATES.md`
-   `43-MASTER-DEV-PROMPT.md`
-   `44-DECISION-GATES.md`
-   `45-REQUIREMENTS-TRACEABILITY.md`
-   `46-SESSION-HANDOFF-PROTOCOL.md`
-   `47-EXECUTION-PROTOCOL-REVIEW.md`
-   `SESSION-HANDOFF.md` — estado operacional mutável (handoff entre sessões)

ADRs V2: `docs/adr/ADR-V2-001` … `ADR-V2-008`

## Estado atual resumido

O repositório atual é de extensões cognitivas, não um Core completo. O
Supabase possui estruturas RAW antigas ativas e um pipeline canônico
novo ainda pouco utilizado. Multi-tenancy estrutural ainda não está
pronta. ProsperfySkill já possui grande catálogo de capabilities e deve
ser reaproveitado como execution layer. Hermes hoje carrega
contexto/tool surface excessivos e isso é um alvo explícito de redução.
