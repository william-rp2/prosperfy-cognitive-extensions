# Princípios e Regras Arquiteturais

## R1 --- Não começar do zero

A V2 é evolução e reorganização. Antes de criar qualquer componente,
verificar: Cognitive atual → ProsperfySkill → MCP de mercado → API
existente → somente então código novo.

## R2 --- LLM por último

Ordem obrigatória de resolução: **CODE → SQL → RULE → RAG → LLM**.

## R3 --- LLM não observa continuamente

Collectors, schedulers, health checks e triggers são código. Eventos
relevantes chamam inteligência apenas quando necessário.

## R4 --- Uma fonte operacional

Supabase/PostgreSQL é a fonte oficial para estado: tarefas, projetos,
finanças, workflows, follow-ups, integrações, auditoria e referências de
conhecimento.

## R5 --- RAW-first

Toda entrada relevante preserva evidência original antes de
enriquecimento. Nenhuma classificação substitui a fonte.

## R6 --- RAG não substitui dados estruturados

Saldo, orçamento, tarefas, prazos, estados e métricas são SQL. RAG é
para conhecimento, decisões, documentos, reuniões e contexto
semiestruturado.

## R7 --- Hermes não conhece internals

Hermes não deve precisar conhecer tabelas, vaults, dezenas de MCPs ou
186 tools. Ele usa uma superfície curta do Cognitive.

## R8 --- Cognitive não duplica integração

ProsperfySkill permanece execution/integration layer. MCPs de mercado
são preferidos quando maduros e seguros.

## R9 --- Multi-tenant desde a fundação

Toda raiz de dados, execução, conhecimento, credencial, integração e
auditoria precisa de ownership tenant-aware.

## R10 --- Least privilege

Cada tenant/profile recebe somente capabilities necessárias. Tools
administrativas não entram no profile conversacional comum.

## R11 --- Efeitos externos têm policy

Toda capability é classificada como `ALLOW`, `CONFIRM` ou `DENY`.

## R12 --- Idempotência

Writes, collectors, webhooks, workflows e follow-ups devem suportar
idempotency keys e evitar duplicação.

## R13 --- Auditabilidade

Toda ação relevante registra actor, tenant, capability, inputs
redigidos, decisão de policy, resultado, duração, custo e correlation
id.

## R14 --- Secrets fora do prompt/RAG

Credenciais ficam em secret store/configuração apropriada e são
referenciadas por IDs. Nunca são armazenadas como conhecimento ou
entregues à LLM.

## R15 --- Repositório é canônico

Código do Cognitive é desenvolvido no repositório com agentes de
programação. Hermes não é o ambiente canônico de desenvolvimento do
Core.

## R16 --- Sem mudanças destrutivas implícitas

Migrações, limpeza de legado, remoção de plugins e alterações de
infraestrutura exigem plano, backup e aprovação explícita.

## R17 --- Social por último

Social Engine não bloqueia o MVP operacional.
