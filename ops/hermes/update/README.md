# ops/hermes/update — Update Guard (Slim/Minimal)

Mecanismo provisório update-safe para o Hermes Slim (Sprint 0.7.2/0.7.3).

## Por quê

O Slim depende de:
1. `config.yaml` → `platform_toolsets.<gateway platforms>: []` (normal chat 0 tools).
2. `gateway/run.py` → `include_default_mcp_servers=False` (MCP oculto do LLM).
3. `hermes_cli/tools_config.py` → early-return vazio p/ toolset explícito `[]`
   (remove kanban/feishu residuais — Minimal 0.7.3).

Os itens 2/3 são alterações de source no runtime upstream e podem sofrer
impacto de `hermes update`. Este guard detecta e reaplica com segurança.

## Arquivos

- `slim.patch` — patch combinado (run.py + tools_config.py), formato git apply.
- `verify_slim.py` — verifica invariantes (config, patches, NORMAL_CHAT_TOOLS=0,
  schema bytes=0, CAPABILITY_FAIL_CLOSED). Exit 0 = PASS; 1 = FAIL_CLOSED.
- `update_guard.sh` — wrapper do fluxo oficial (`hermes update --backup`) com
  lock, backup, detecção de estado do patch, reaplicação controlada (nunca
  fuzzy), restart se necessário, verify + smoke. `--dry-run` só inspeciona.

## Uso

```bash
# dry-run (somente inspeção; nada é atualizado/reiniciado)
bash ops/hermes/update/update_guard.sh --dry-run

# verificação independente (leitura)
cd ~/.hermes/hermes-agent && venv/bin/python /path/verify_slim.py

# update operacional (AUTORIZADO na Sprint 0.7.3 §29)
bash ops/hermes/update/update_guard.sh
```

## Fail-closed

Se após o update `NORMAL_CHAT_TOOLS > 0` ou `LEGACY_MCP_VISIBLE=YES` ou
`/SERVIDORES_LLM_CALLS > 0` → o update NÃO é aceito. Rollback: restaurar o
backup (`~/.hermes/backups/update-guard-<ts>/`) + restart.

Se `PATCH_CONFLICT` → STOP (não editar automaticamente por fuzzy match).