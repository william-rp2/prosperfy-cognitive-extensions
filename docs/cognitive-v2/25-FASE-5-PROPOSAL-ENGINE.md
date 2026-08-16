# Fase 5C --- Proposal Engine

## Objetivo

Gerar propostas/orçamentos consistentes a partir de áudio/texto, usando
conteúdo assistido por LLM e renderização determinística.

## Pipeline

``` text
Brief
 -> extraction
 -> ProposalSpec
 -> validation
 -> content generation
 -> template selection
 -> renderer
 -> preview
 -> approval
 -> publish/send
```

## ProposalSpec

-   tenant/client
-   project/opportunity
-   title
-   objectives
-   scope items
-   exclusions
-   deliverables
-   timeline
-   pricing
-   payment terms
-   validity
-   legal notes
-   brand/template
-   output formats

Preço, parcelas, impostos e condições não podem ser inventados pela LLM.

## Templates

Versionados e separados por tenant/brand. Renderers possíveis: - PDF -
HTML - PPTX

A decisão "render dentro do Cognitive ou capability externa" é um
`DECISION GATE`; preferir adapter se já houver serviço/tool adequado.

## Estado

-   proposal_specs
-   proposal_versions
-   proposal_templates
-   proposal_outputs
-   proposal_approvals

## Gate

-   brief → spec;
-   validação;
-   versionamento;
-   render;
-   preview;
-   aprovação;
-   link/arquivo;
-   nenhuma condição comercial inventada.
