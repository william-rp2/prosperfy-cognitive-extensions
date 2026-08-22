# Human Acceptance 0.7.6.2 — Performance + Presentation Follow-up

> Runtime hermes-clean LIVE. Regressões diagnosticadas com medição real (sem estimativa).

## 1. Performance — root cause medida + fix

```
ANTES (SERIAL): SERVIDORES_TOTAL_MS=40167 (~40s)
  RESOURCE_DISCOVERY_MS=1516
  black=9124ms · hostinger-one=9534ms · manager1=9744ms · prosperfy=10249ms
  (4 resources × 3 MCP calls = 12 chamadas SEQUENCIAIS)
DEPOIS (PARALELO): SERVIDORES_TOTAL_MS=13313 (~13s, ~3x mais rápido)
  ROOT_CAUSE=SERIAL_EXECUTION (soma das latências por resource)
  RESOURCE_EXECUTION_MODE=PARALLEL (asyncio.gather) · MCP_CALLS_TOTAL=12 (inalterado)
  FIX: infra_service.servidores_status agora executa os resources em paralelo
  (fail-closed por resource preservado; semantics inalteradas)
SLOWEST_STAGE=execução dos 4 infra.inspect (parallel max ≈10s + discovery ≈2.5s)
RETRY_OR_TIMEOUT_FOUND=NO (hostinger: 1 falha real, sem retry; docker ausente)
```

## 2. Friendly name — diagnóstico + fix forward-compatible

```
EVIDÊNCIA (dumps reais):
  /v1/resources retorna somente {resource_key, resource_type} — SEM display name
  payload de falha do infra.inspect (hostinger): data={} — panorama descartado
  display names (Black/Manager1/Prosperfy) vêm do panorama (host) nos OK
  Para resource com FALHA, não existe display estruturado na fonte atual
  (a mensagem de erro contém "Hostinger One" no detalhe, mas não estruturado)
FIX: formatter (server_views.build_servidores_view) agora NUNCA expõe resource_key
  quando existe display/canonical (f.get("display_name") or f.get("host"));
  adapter consome display_name do metadata quando a Cognitive expuser.
  Com a fonte atual, o resource com falha continua exibindo o resource_key
  (não há nome estruturado para usar sem hardcode) → FOLLOW-UP no Cognitive:
  /v1/resources (ou payload de falha) deve expor display_name do resource
  (ex.: "Hostinger One") — a extensão já está pronta para consumir.
```

## 3. Deploy + live

```
Deploy no runtime (gate-0.5/src, path importado pelo hermes-clean):
  infra_service.py (paralelo) · cognitive_api_adapter.py (nota forward-compat)
  server_views.py (formatter display-first)
Restart hermes-gateway.service (single-bridge: port 3000 livre antes)
GW: MainPID=3347400 · NRestarts=0 · active · bridge node 3347443 (:3000, sessão reutilizada)
VERIFY_SLIM=PASS (NORMAL_CHAT_TOOLS=0, SCHEMA_BYTES=0, CAPABILITY_FAIL_CLOSED=PASS)
```

## 4. Métricas finais

```
SERVIDORES_TOTAL_MS=13313 (era ~40167) · RESOURCE_DISCOVERY_MS≈2500
BLACK=~9700 · MANAGER1=~9700 · PROSPERFY=~10300 · HOSTINGER_ONE=~9600 (parallel)
SLOWEST_STAGE=infra.inspect (parallel) · ROOT_CAUSE=SERIAL_EXECUTION
RESOURCE_EXECUTION_MODE=PARALLEL · MCP_EXECUTION_MODE=MIXED (discovery serial + inspect parallel)
RETRY_OR_TIMEOUT_FOUND=NO
FRIENDLY_NAME_FIXED=PARTIAL (formatter corrigido p/ display-first; failed resource depende
  da Cognitive expor display_name — follow-up documentado, sem hardcode)
NORMAL_CHAT_TOOLS=0 · NORMAL_CHAT_SCHEMA_BYTES=0
LIVE_RUNTIME=hermes-clean · GATEWAY_ACTIVE=YES · UNEXPECTED_RESTARTS=0
MCP_CALLS_TOTAL=12 · HERMES_LLM_CALLS=0 · COGNITIVE_LLM_CALLS=0
PRODUCTION_UNTOUCHED=YES · SECRET_EXPOSED=NO
```