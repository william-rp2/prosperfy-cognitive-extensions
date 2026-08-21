# Sprint 0.5 — Fix Dispatcher WhatsApp (plugin commands) + env COGNITIVE_GATEWAY_URL

Checkpoint base: `5568f57` (dev/sprint-0.5).

Runtime real alvo: `~/.hermes/hermes-agent` (repo git do Hermes, host Prosperfy).
Problema A: `/servidores` rejeitado no WhatsApp (`gateway/run.py:11756`,
"Unrecognized slash command /servidores from whatsapp").
Problema B: `/servidores` na WEB chega ao plugin mas falha com
"COGNITIVE_GATEWAY_URL não configurada".

## Contrato existente (Seção 1)

| Item | Achado |
|---|---|
| PLUGIN_COMMAND_REGISTRY | `PluginManager._plugin_commands` em `hermes_cli/plugins.py` — registry canônico (EXISTE; não criamos outro) |
| PLUGIN_REGISTER_API | `PluginContext.register_command(name, handler, description, args_hint)` — API oficial que o plugin já usa (`ctx.register_command("servidores", _handle_servidores, ...)`) |
| WHATSAPP_COMMAND_LOOKUP | `gateway/run.py` JÁ chama `get_plugin_command_handler(command.replace("_","-"))` antes do gate de Unknown (commit fae3ba2c) |
| COMMANDS_LIST_IMPLEMENTATION | `_iter_plugin_command_entries()` → `get_plugin_commands()`; integrado a Telegram/Slack/Discord e `/commands` do gateway |
| resolve_plugin_command API | `hermes_cli.plugins.get_plugin_command_handler(name)` |

Conclusão: o dispatcher JÁ consulta o registry de plugins. O bug NÃO é
"dispatcher não consulta o registry" (ROOT_CAUSE_CLASS=D estava incorreto
para o runtime atual): é **registry stale**.

## Root cause (provado no runtime real)

Evidência (host Prosperfy, read-only + prova in-process):

- Processo gateway: `python -m hermes_cli.main gateway run` (PID 3162559),
  started `Aug 20 23:19:49`.
- `hermes plugins enable capability-intelligence` rodou `23:20` — **após** o
  start do gateway.
- `plugins.enabled: [capability-intelligence]` no config (pós-enable).
- Discovery é cacheada (`_discovered=True`); `get_plugin_command_handler`/
  `get_plugin_commands` usam o snapshot do start. Plugin habilitado depois
  não aparece até restart.
- Prova em processo fresco do runtime: `get_plugin_commands()` retorna
  `["capability","servidores"]` e `PLUGIN_capability-intelligence_ENABLED=True`.
  Com registry limpo (estado do gateway pré-enable), `get_plugin_command_handler("servidores")`
  → `None` (reproduz o "Unknown command"); após `discover_and_load(force=True)` → handler.

**Root cause real:** registry de comandos de plugins do processo gateway é um
snapshot do start; enable pós-start não é refletido até restart.

## Fix (mínimo, genérico)

Patch `scripts/patches/hermes_runtime_plugin_command_refresh.patch` em
`hermes_cli/plugins.py`:

- `_has_stale_plugin_registry(manager)` — detecta registry desatualizado
  (plugin habilitado OU desabilitado após o start) apenas para plugins gated
  por `plugins.enabled` (user/standalone/entry-point); bundled backends/
  platforms e exclusive/model-provider ficam de fora. Sem nome de comando
  hardcoded.
- `get_plugin_command_handler` / `get_plugin_commands` — refresh-on-stale
  (um `discover_and_load(force=True)`) quando o registry não bate com o
  config.

Propriedades preservadas:
- Built-in mantém precedência (dispatcher checa built-in antes; `register_command`
  rejeita colisão com built-in).
- `GATEWAY_KNOWN_COMMANDS` NÃO é alterado (comandos de plugin nunca entram lá).
- Plugin desabilitado: comando some do dispatch e do `/commands`.
- Comando inexistente: continua "Unknown command".
- Genérico: `/plugin-test` (e qualquer plugin futuro) resolve sem alteração
  no gateway.

Aplicado no runtime real com backup `hermes_cli/plugins.py.bak-sprint05-refresh`
(inerte até restart). Verificação no runtime: heal de enable-pós-start OK,
listing OK, py_compile OK, suíte `tests/hermes_cli/test_plugins.py` +
`test_commands.py` = 288 passed / 1 failed pré-existente
(`TestSlackNativeSlashes::test_telegram_parity` — falha igual no backup).

## Env (Problema B)

- `COGNITIVE_GATEWAY_URL_EXPECTED=https://api-cognitive-homolog.prosperfy.com.br`
  (allowlist do repo + Gate 0.5).
- `COGNITIVE_GATEWAY_URL_SOURCE=~/.hermes/.env` — fonte única canônica,
  carregada por `hermes_cli/env_loader.py` no processo; web e WhatsApp do
  gateway compartilham o mesmo processo/env.
- Estado atual no host: NENHUMA chave `COGNITIVE_*` no `.env` nem no env do
  processo gateway (`/proc/<pid>/environ`) — confirma o erro B.
- Credencial/tenant/actor do slice: não estão no host (usados no Gate 0.5 pelo
  operador). Configurar com `scripts/configure-hermes-cognitive-env.sh`
  (valores do operador; nunca inventar; nunca imprimir).

## Cutover (operador)

1. Aplicar patch (se ainda não): `bash scripts/apply-hermes-runtime-plugin-refresh.sh`.
2. Configurar env: `bash scripts/configure-hermes-cognitive-env.sh` (com os 4
   valores exportados) → `--check` deve mostrar `PRESENT` para os 4.
3. Reiniciar o gateway Hermes.
4. Retestar `/servidores` na WEB e no WhatsApp + `/commands` (deve listar
   `/servidores` com capability-intelligence habilitado).

NÃO declarado Human Acceptance PASS — teste final é do usuário.

## Cutover EXECUTADO (2026-08-21)

Contexto estável provisionado no Homolog (criado 03:14 UTC, validado read-only):
- Tenant `prosperfy-homolog` (UUID 11a26649-91d0-4971-8d1f-2afc57f8b5ae) — STABLE (não sintético).
- Service identity `hermes-homolog`, profile `infra-read`, ACTIVE (Sprint 0.4 lifecycle).
- Grant único: `infra.inspect` (GRANT_COUNT=1 → EXTRA_GRANTS=NO).
- Resource `prosperfy-vps-homolog` → resolved_params `{host: Prosperfy, type: vps}`.

Env `~/.hermes/.env` (mode 600): 5 chaves COGNITIVE_* PRESENTES.

Auth precheck (adapter Hermes → Homolog):
- AUTH_INFRA_INSPECT=ALLOW · execute completa (3 tools) · UNGRANTED=DENY (404 fail-closed; DB GRANT_COUNT=1).

Gateway restart `hermes-gateway.service` (user systemd): 3170904 → 3240842 → 3241916
(final, active, NRestarts=0). Runtime patch + plugin fix ativos.

**Bug real extra encontrado e corrigido no PLUGIN:** `_handle_servidores` usava
`asyncio.run()` → no gateway async falhava ("asyncio.run() cannot be called from
a running event loop", log real 00:19). Corrigido para `async def` + `await`
(dispatcher do gateway aguarda coroutines). Commit `b1ee358`.

**Achado (decisão do operador):** a API Homolog está com `COGNITIVE_LIVE_MCP=0`
(Modo MOCK) — o caminho completo funciona (auth/policy/dispatch/env/handler) e
retorna dados `mock-host`. Dados REAIS da VPS exigem `COGNITIVE_LIVE_MCP=1` no
env da API (`api-runtime-sprint03.env`) + restart de `prosperfy-cognitive-homolog-api.service`
(passo documentado do Gate; fora do escopo desta sessão).

Veredito: READY_FOR_REAL_HUMAN_RETEST (teste final do usuário).