# Integração Pluggy — uso pessoal (Meu Pluggy / Conector 200)

Escopo: **finanças pessoais do William**, não Open Finance para terceiros. Sem
plano PRO, sem webhook comercial, sem fluxo SaaS/multiusuário.

## Arquitetura

```
Bancos
   ↓
Meu Pluggy (o titular conecta a própria conta em meu.pluggy.ai)
   ↓
Conector 200 / MeuPluggy (proxy gratuito que expõe os Items autorizados à nossa app)
   ↓
Pluggy API (pluggy-sdk, client centralizado em src/pluggy.ts)
   ↓
PluggySyncService (src/finance/pluggySyncService.ts) — polling, sem webhook
   ↓
SQLite local (src/finance/db.ts + migrations) — financial_items/accounts/transactions/...
   ↓
API interna /api/finance/* — accounts, transactions, summary, sync, sync/status
   ↓
Dashboard / Hermes / agentes de IA (consumo futuro)
```

Por que **sem webhook**: o Conector 200 (nível gratuito/pessoal do Meu Pluggy) não
expõe webhooks — confirmado na documentação oficial da Pluggy em agosto/2026. A
rota `POST /api/webhooks/pluggy` continua existindo no código (útil se um dia a
conta migrar para plano pago), mas **não é o caminho principal**. O caminho
principal é polling: cron interno + sincronização manual.

Por que **sem "listar Items"**: a Pluggy não expõe um endpoint para listar Items
de uma aplicação (por segurança). O único momento em que um novo `itemId` é
conhecido é no callback de sucesso do Connect Widget (`POST /api/pluggy/items`).
A partir daí, o Item fica persistido em `financial_items` e o sync service
sempre itera sobre os Items que **já conhecemos**, nunca tenta descobrir novos
sozinho.

Por que **SQLite local, não Supabase**: não existia nenhum projeto Supabase
para este app no momento da implementação (só um projeto não relacionado,
"SocialMedia-Homologacao"). Criar um projeto novo é infraestrutura externa que
exigiria confirmação/custo. `.gitignore` já esperava `*.sqlite3` e
`apps/*/data/`. SQLite é 100% local, zero custo, zero dependência externa —
adequado para "banco local" citado como opção válida. As camadas de
repositório (`itemsRepository`, `accountsRepository`, etc.) isolam SQL puro,
então migrar para Postgres/Supabase depois é um trabalho contido caso o
volume de dados ou o caso de uso mude.

## Variáveis de ambiente (nomes apenas — preencher em `.env`, nunca commitar)

| Variável | Uso |
|---|---|
| `PLUGGY_CLIENT_ID` / `PLUGGY_CLIENT_SECRET` | Credenciais da app Pluggy (Dashboard → sua aplicação). Só no backend. |
| `PLUGGY_CLIENT_USER_ID` | Identificador do usuário (default `poc-william`). |
| `PLUGGY_ENV` | `sandbox` ou `production`. |
| `PLUGGY_STORE_PATH` | Store JSON legado (auditoria de webhook, item↔clientUserId). |
| `PLUGGY_WEBHOOK_SECRET` / `PLUGGY_WEBHOOK_HEADER` / `PLUGGY_ALLOW_UNSIGNED_WEBHOOKS` | Canal de webhook opcional (não disponível no Conector 200 pessoal). |
| `PUBLIC_BASE_URL` | Só necessário se algum dia cadastrar webhook via túnel/deploy público. |
| `FINANCE_DB_PATH` | Caminho do SQLite local (default `./data/financeiro-pessoal.sqlite3`). |
| `FINANCE_API_TOKEN` | Token exigido em `Authorization: Bearer <token>` para `POST /api/finance/sync`. Sem ele, o endpoint fica bloqueado. |
| `PLUGGY_SYNC_ENABLED` | Liga/desliga o cron interno (default `false`). |
| `PLUGGY_SYNC_INTERVAL_HOURS` | Intervalo do cron (default `6`). |
| `PLUGGY_SYNC_SAFETY_WINDOW_HOURS` | Sobreposição (horas) subtraída da última transação conhecida por conta, na sincronização incremental (default `24`). |
| `PLUGGY_SYNC_MAX_CONCURRENT_ITEMS` | Limite de Items sincronizados em paralelo (default `3`). |
| `PLUGGY_SYNC_STALE_LOCK_MINUTES` | Após esse tempo, um run "running" travado (processo derrubado no meio) é liberado automaticamente no próximo boot (default `30`). |

## Como conectar uma nova conta bancária

1. A conta é conectada **no Meu Pluggy** (https://meu.pluggy.ai), pelo próprio
   titular — não pela nossa aplicação diretamente. É lá que fica a
   senha/MFA do banco; nossa app nunca vê essas credenciais.
2. No Meu Pluggy, o titular **autoriza** o compartilhamento desses dados com
   a nossa aplicação (via Conector 200 / MeuPluggy).
3. Na nossa aplicação (tela `/poc/pluggy` do frontend, ou qualquer chamada
   equivalente ao fluxo Connect Token → Widget), a Pluggy retorna um
   `item.id` — é o único momento em que esse Item passa a existir para nós.
4. `POST /api/pluggy/items { itemId }` persiste esse Item em
   `financial_items` (com detalhes do connector já enriquecidos via
   `fetchItem`).
5. **Não é necessário plano PRO** para nada disso — é exatamente o fluxo
   gratuito Meu Pluggy + Conector 200.
6. Os dados (contas, saldos, transações) só aparecem no banco local depois de
   uma sincronização (manual ou pelo cron) — ver abaixo.

## Como sincronizar manualmente

```bash
curl -X POST http://127.0.0.1:8787/api/finance/sync \
  -H "Authorization: Bearer $FINANCE_API_TOKEN"
```

Resposta:

```json
{
  "success": true,
  "status": "success",
  "items": 2,
  "accounts": 6,
  "transactionsCreated": 15,
  "transactionsUpdated": 3,
  "errorCount": 0,
  "durationMs": 1834
}
```

- `status` pode ser `success`, `partial` (algum Item falhou, os outros
  seguiram) ou `failed` (todos falharam).
- Sem o header `Authorization`, a resposta é `401`.
- Se já existir uma sincronização em andamento, a resposta é `409
  sync_already_running` — é o lock (índice único parcial em
  `financial_sync_runs`, `WHERE status = 'running'`).
- A **primeira** sincronização de um Item recém-conectado já é a
  "sincronização inicial": como não existe transação prévia para a conta, o
  sync busca o histórico completo (sem `dateFrom`). Não há um gatilho
  automático disparado no momento do connect — dispare manualmente (comando
  acima) ou aguarde o próximo tick do cron.

## Como funciona o cron

Não há infraestrutura nova (sem BullMQ/Vercel Cron/Redis) — é um
`setInterval` dentro do próprio processo Fastify
(`src/finance/scheduler.ts`), habilitado por `PLUGGY_SYNC_ENABLED=true`.
A cada `PLUGGY_SYNC_INTERVAL_HOURS`, chama `syncService.syncAll('cron')`. Se
uma sincronização manual já estiver rodando naquele instante, o cron apenas
loga e pula o tick (mesmo lock do endpoint manual).

## Como diagnosticar erro

```bash
curl http://127.0.0.1:8787/api/finance/status
curl http://127.0.0.1:8787/api/finance/sync/status
```

- `financial_items.error_summary` guarda o último erro por Item (limpo
  automaticamente quando o Item volta a sincronizar com sucesso).
- `financial_sync_runs.error_summary` guarda um resumo por run:
  `[{ itemId, message }]` para cada Item que falhou naquela execução.
- Falhas de rede/HTTP 429/5xx são retentadas automaticamente (1ª tentativa,
  +5s, +30s, +2min — 4 tentativas no total, respeitando `Retry-After` quando
  o servidor manda). Erros não-transitórios (400, credenciais ausentes) não
  são retentados.
- Um Item com `status = LOGIN_ERROR` é pulado (sem tentar Accounts/Transactions)
  até que o titular refaça a conexão no Meu Pluggy.

## Como revogar uma conexão

A revogação acontece **no Meu Pluggy**, pelo titular (é lá que a autorização
foi concedida). Depois de revogada, a próxima sincronização vai falhar para
aquele Item (erro de autenticação) — o registro em `financial_items` fica,
mas marcado com erro; os dados já sincronizados continuam no banco local
(histórico), só param de ser atualizados. Se quiser apagar o histórico
também, isso é uma operação manual direta no SQLite (fora do escopo desta
integração — nenhuma rota de "esquecer Item" foi construída aqui).

## Limitações do Conector 200 (uso pessoal/gratuito)

Confirmado na documentação oficial (pluggy.ai/meu-pluggy, docs.pluggy.ai) em
agosto/2026:

- **Sem webhook** — por isso a arquitetura é 100% polling.
- **Sem SLA/contrato comercial** — se o Meu Pluggy sair do ar, a sincronização
  para até ele voltar; não há garantia de disponibilidade.
- **Dependente do que o titular já conectou no Meu Pluggy** — a app não
  controla quais bancos aparecem, só consome o que foi autorizado lá.
- **Sem PIX, sem categorização automática comercial, sem KYC** — fora do
  escopo de uso pessoal mesmo.
- `category`/`merchant` em transações: alguns relatos da comunidade indicam
  que esses campos de enriquecimento podem depender de assinatura Pro em
  certas contas Pluggy. O SDK expõe os campos incondicionalmente
  (`Transaction.category`, `Transaction.merchant`) — **não foi possível
  confirmar isso com certeza sem um teste real** (não há credenciais Pluggy
  neste ambiente de desenvolvimento). O sync service já grava o que vier
  (nulo se não vier); ver seção "Pendências" no relatório final.
- Investimentos e faturas de cartão: o SDK expõe os endpoints
  (`fetchInvestments`, `fetchCreditCardBills`) e o sync service os chama,
  mas **swallow-and-log** se a chamada falhar — trata como
  "não disponível no modo pessoal" sem derrubar o resto da sincronização.
  Também carece de confirmação com um Item real.

## Pluggy MCP

A Pluggy oferece integração MCP. Recomendação: **não usar como substituto**
da ingestão estruturada — o MCP é útil para consulta/diagnóstico ad-hoc (ex.:
Hermes perguntando "qual o saldo do Nubank agora" via ferramenta autorizada),
mas o histórico e os dados estruturados do sistema devem continuar vindo do
SQLite local via `PluggySyncService`, não de chamadas MCP em tempo real —
mantém a "regra de ouro" (banco local como fonte operacional, Pluggy como
fonte externa). Isso fica registrado como recomendação; nada de MCP foi
implementado nesta fase (fora de escopo).

## Fora de escopo (deliberado)

Pagamentos, PIX, iniciação de pagamento, cobrança, transferência, Open
Finance para clientes externos, onboarding de terceiros, SaaS, plano PRO,
webhook comercial, categorização paga, KYC, enriquecimento comercial,
dashboard financeiro avançado. Auth real (Supabase Auth) também ficou fora
desta fase — o endpoint de sync manual usa um token compartilhado simples
(`FINANCE_API_TOKEN`), suficiente para um app pessoal rodando em
`127.0.0.1`.
