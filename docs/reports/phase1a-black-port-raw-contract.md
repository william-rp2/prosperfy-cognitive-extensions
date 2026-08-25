# Phase 1A — Black Port RAW Contract (corrigido — root cause provada)

> RAW capturado via host executor corrigido. O tool de portas é um SCAN
> (`ss -tulpn`); o número real está no stdout (texto). Fix no normalizer.

## 1. RAW observado (Black, via infra.inspect)

```
RESOURCE_KEY=black-vps-homolog · CAPABILITY=infra.inspect · MCP_TOOL=prosperfy_vps_verificar_portas
MCP_TOOL_ARGS (interno)=sudo ss -tulpn 2>/dev/null || ss -tuln
COGNITIVE_RESULT_DATA keys=[panorama, listar_containers, verificar_portas]
TOOL_PAYLOAD_PORTS={"host":"Black","comando":"sudo ss -tulpn ...","exit_status":0,
  "sucesso":true,"duracao_ms":77,"stdout":"<ss -tulpn text>","porta":null}
RAW_KEYS=['host','comando','exit_status','sucesso','duracao_ms','stdout','stderr','porta']
PORT_KEY_AT=.../verificar_portas/data/data/porta = null
```

## 2. Identificador

```
PORT_IDENTIFIER_PRESENT=YES (no stdout, não estruturado)
PORT_IDENTIFIER_IN_STRUCTURED_DATA=NO (porta=null)
PORT_IDENTIFIER_IN_STDOUT=YES · STDOUT_FORMAT=ss -tulpn (Netid/State/Local Address:Port)
REQUESTED_PORT: a tool NÃO verifica uma porta — é um scan de todas
REQUESTED_PORT_SOURCE=MCP default interno (comando fixo ss -tulpn)
```

## 3. FAILURE BOUNDARY / ROOT CAUSE

```
FAILURE_BOUNDARY=B (MCP OUTPUT): o tool retorna o scan em stdout com `porta: null`;
  o normalizer tratava como verificação única → "?".
ROOT_CAUSE: `_normalize_ports` não lidava com o contrato SCAN (portas em stdout texto).
```

## 4. Fix mínimo (server_views, boundary real)

```
_normalize_ports: quando o payload tem stdout com LISTEN, parseia `ss -tulpn`
  (Local Address:Port = token 4) → itens {port, open, success} por porta de escuta.
_parse_ss_stdout: extrai portas LISTEN (0.0.0.0:80→80, [::]:443→443, *:8080→8080).
Testes locais: ss sample → ['80','443','8080'] · nunca "?"/"None".
LIVE (Black): NORMALIZED_PORTS=22,25,3000,3001,443,53,5432,6504,80,8000,8025 · OPEN_COUNT=11
```

## 5. Reload observado (host trust)

```
OLD_PID=3927862 → STOP (MainPID=0) → START → NEW_PID=3929664 (≠ OLD)
ActiveState=active · bridge node 3929701 (SINGLE_BRIDGE=YES)
```

## 6. Métricas

```
RESOURCE_KEY=black-vps-homolog · MCP_TOOL=prosperfy_vps_verificar_portas · MCP_TOOL_ARGS=ss -tulpn
COGNITIVE_PORTS_RAW=capturado · TOOL_PAYLOAD_PORTS=capturado
PORT_IDENTIFIER_PRESENT=YES · PORT_IDENTIFIER_PATH=$.stdout (ss text) · VALUE=11 portas reais
REQUESTED_PORT=scan (todas) · REQUESTED_PORT_SOURCE=MCP interno
FAILURE_BOUNDARY=B(MCP OUTPUT) · ROOT_CAUSE=scan em stdout não parseado
FIX=_parse_ss_stdout + branch scan no _normalize_ports · TESTS=PASS (local + live 11 portas)
OLD_PID=3927862 · NEW_PID=3929664 · LIVE_RESULT_PORT=22..8025 (11) · PORTS_SCOPING_DEBT=YES(backlog)
COMMIT=ee4903b · PUSHED=YES (dev/phase1-infra-read-v1 + hotfix)
BLACK_PORT_HUMAN_TEST_READY=YES (fix deployado + reload observado + live provado)
PRODUCTION_UNTOUCHED=YES · MASTER_UNTOUCHED=YES
```