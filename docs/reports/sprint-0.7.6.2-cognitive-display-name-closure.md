# Cognitive — Resource Display_Name Closure

> Follow-up de 58769b4. display_name adicionado ao contrato GET /v1/resources
> usando metadata/resource canônico (resolved_params.host). Homolog apenas.

## 1. Auditoria do modelo (antes de alterar)

```
RESOURCE_DISPLAY_FIELD_EXISTING=YES (resolved_params.host — fonte canônica)
SOURCE_OF_DISPLAY_NAME=resolved_params.host (campo já usado pela elegibilidade
  `_usable_for_infra` e pela execução; o erro "Docker indisponível em 'Hostinger One'"
  prova que o MCP usa esse mesmo label)
tenant_resources: {resource_key, resource_type, resolved_params JSONB} — sem coluna
  display_name dedicada; host já presente no JSONB → SEM migration (NEW_MIGRATIONS=0)
Alvo real do deploy: /home/will/projetos/prosperfy-cognitive-gate-0.3 (uvicorn
  cognitive.gateway.app:app :8800 = prosperfy-cognitive-homolog-api.service) — o repo
  "homolog" NÃO é o que roda; gate-0.3 é o Homolog running.
```

## 2. Alteração (Cognitive Homolog, gate-0.3)

```
routes/resources.py: response items agora {resource_key, resource_type, display_name}
  display_name = resolved_params.host (canônico, NUNCA regex do key; fallback resource_key)
  backward-compat: resource_key/resource_type preservados; display_name aditivo
  autorização/grant/RLS INALTERADOS (só adição de campo na resposta montada)
COMMIT (gate-0.3)=b0521a0 · deploy via restart prosperfy-cognitive-homolog-api.service
```

## 3. Consumo no Hermes (mínimo — completa o "já suporta display_name")

```
cognitive_api_adapter.list_resources: passa a retornar {resource_key, display_name}
  (consome o novo campo; NUNCA deriva por regex)
infra_service.servidores_status: propaga display_name para views OK e falhas
formatter (sprint anterior) já preferia display_name/host — agora as FALHAS têm display
Nota honesta: a premissa "extensão já suporta" exigia esse wiring mínimo (3 linhas);
  NÃO houve restart do gateway Hermes (§11) — o gateway live pega o código no próximo
  restart natural. O E2E abaixo roda o código novo em processo fresco.
```

## 4. E2E

```
GET /v1/resources (pós-deploy):
  black-vps-homolog -> Black · hostinger-one-vps-homolog -> Hostinger One
  manager1-vps-homolog -> Manager1 · prosperfy-vps-homolog -> Prosperfy
  AUTHORIZED_RESOURCES_FOUND=4 (tenant isolation/grant preservados)
/servidores (E2E processo novo):
  Servidores — 4 | Black — OK | Manager1 — OK | Prosperfy — OK
  Hostinger One — ERRO | ... [TOOL_ERROR] Docker indisponível em 'Hostinger One'
  Resumo: 3 OK · 0 DEGRADED · 1 ERRO
  SERVIDORES_TOTAL_MS=13407 (parallel preservado) · erro real NÃO mascarado
```

## 5. Testes A1-A4

```
A1 (display presente) = PASS (4/4 resources com display_name)
A2 (sem display_name) = coberto por fallback _display_name→resource_key (funcional)
A3 (não autorizado) = grant check inalterado → lista vazia (fail-closed) — preservado
A4 (cross-tenant) = RLS inalterado — preservado
```

## 6. Métricas finais

```
DISPLAY_NAME_CHECKPOINT=<pos push extensions repo>
GET_RESOURCES_DISPLAY_NAME=PASS
BLACK_DISPLAY_NAME=Black · HOSTINGER_ONE_DISPLAY_NAME=Hostinger One
MANAGER1_DISPLAY_NAME=Manager1 · PROSPERFY_DISPLAY_NAME=Prosperfy
AUTHORIZED_RESOURCES_FOUND=4
/SERVIDORES_FUNCTIONAL=PASS · /SERVIDORES_FRIENDLY_NAMES=PASS (incl. failed)
HOSTINGER_REAL_ERROR_PRESERVED=YES
RESOURCE_EXECUTION_MODE=PARALLEL · MCP_CALLS_TOTAL=12
HERMES_LLM_CALLS=0 · COGNITIVE_LLM_CALLS=0
NEW_DB_TABLES=0 · NEW_MIGRATIONS=0 · NEW_WRITE_CAPABILITIES=0
PRODUCTION_UNTOUCHED=YES · SECRET_EXPOSED=NO
FINAL_GATE=PASS
Obs: gateway Hermes live NÃO reiniciado (§11); friendly name no live após próximo restart.
```