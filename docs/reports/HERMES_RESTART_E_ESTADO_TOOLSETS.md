# Restart do Hermes + estado real dos toolsets (29/08/2026)

## Restart — protocolo cumprido

```
ANTES   MainPID=4099356  active/running  1 instancia  bridge pid 4099393 :3000
DEPOIS  MainPID=220736   active/running  1 instancia  bridge pid 220795  :3000
NRestarts=0   EADDRINUSE=0   RESTART_CLEAN=YES
```

## Roteamento — PASS no artefato deployado

Executado com o Python do runtime, importando de
`/home/will/projetos/prosperfy-cognitive-gate-0.5/.../capability_router.py`
(caminho vivo confirmado: e o unico com `__pycache__` do modulo; o
`prosperfy-cognitive-operator-1b` nunca foi importado).

```
"Oi"                              -> NORMAL          (toolsets = [])
"Como estao meus Supabases?"      -> SUPABASE_OPS
"Quais tarefas estao bloqueadas?" -> WORK_MANAGEMENT
"Sincronize meus bancos"          -> FINANCE
"Leia e resuma https://example.com" -> BROWSER
FALHAS=0
```

O router esta wirado no caminho real do WhatsApp: `run.py`
`_resolve_enabled_toolsets_for_source` importa `resolve_specialist_route`,
`route_toolsets` e `is_specialist`.

## Toolsets no runtime — o gargalo real

O router resolve a rota, mas o Hermes DESCARTA nomes de toolset que nao
existem no registry. Estado apos deploy de `supabase_ops_tools.py`:

```
registry._tools          supabase_ops, work_idea, work_project, work_task,
                         work_summary, work_sync_status, infra_read
registry._toolset_checks supabase_ops, work_management, infra_read
```

| rota | toolset | existe no runtime |
|---|---|---|
| SUPABASE_OPS | supabase_ops | SIM (deployado agora) |
| WORK_MANAGEMENT | work_management | SIM |
| INFRA_READ / INFRA_ACTION | infra_read / restart_container | SIM |
| **FINANCE** | finance | **NAO — nunca construido pela track P2** |
| **BROWSER** | browser_harness | **NAO — nunca construido pela track BH** |

P2 e BH entregaram capability YAML + adapter no Cognitive, mas nao a tool
Hermes que o toolset da rota exige. Isso e core faltando, nao deploy
pendente.

## hermes_chat NAO serve para validar E2E

O MCP Live Bridge (`hermes_chat`) NAO passa pelo `capability_router`.
Prova: "Quais tarefas estao bloqueadas?" respondeu consultando as tabelas
`tasks`/`workflows` do Supabase de PRODUCAO, e nao `work_tasks` do Homolog —
ou seja, usou tools genericas, nao a rota WORK_MANAGEMENT.

Consequencia: WHATSAPP_E2E so pode ser validado por mensagem real no
WhatsApp, o que exige o titular do numero. E um passo humano legitimo, nao
um bloqueio tecnico.
