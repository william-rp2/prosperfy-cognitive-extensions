# MVP --- Funcionalidades

## 1. Projects / Tasks / Planning

Workspaces/projetos separados; backlog, planned, in_progress, blocked,
standby, done; prioridade; prazo; responsável; dependências; metas;
planejamento diário/semanal/mensal.

Perguntas como "o que tenho hoje?" são SQL. Priorização entre projetos
pode usar LLM após recuperar dados estruturados.

## 2. Collector

Canais progressivos: WhatsApp, e-mail, uploads, reuniões/transcrições,
áudio, APIs. Tudo preservado em RAW e promovido conforme regras.

## 3. Workflow / Follow-up

Promessas, cobranças, reminders e automações duráveis. Ex.: cliente diz
"te mando em dois dias" → follow-up programado → se material não chegou,
mensagem amigável.

## 4. Finance

Grupo WhatsApp ouvinte + Pluggy + documentos/áudio/texto. Extrair
gastos, categorizar, conciliar quando possível, budgets familiares e ACL
forte. Consultas de saldo/orçamento são SQL.

## 5. Infrastructure Monitor

Usar ProsperfySkill para VPS/containers/systemd/logs. Cognitive guarda
targets, checks, snapshots, incidents e alertas. Grafana é
opcional/futuro.

## 6. Email Intelligence

Sync/collector → RAW → rules → classificar apenas o necessário →
task/finance/offer/knowledge. Não fazer Hermes reler toda a caixa
continuamente.

## 7. Customer Agent

Responder dúvidas autorizadas; coletar informações; criar demandas no
Kanban; criar follow-ups; notificar conclusão; enviar e-mail/NF quando
capability e policy permitirem.

## 8. Proposal Engine

Brief por áudio/texto → `ProposalSpec` estruturado → conteúdo assistido
por LLM → template determinístico → PDF/PPTX/HTML → link para aprovação.
Preço/condições não devem ser inventados.

## 9. Social Engine --- futuro

Brand packs isolados, calendário, geração de opções, aprovação humana,
publicação e analytics. Não faz parte do caminho crítico inicial.
