# Phase 1A — Final RAW Contract Diagnosis (evidências + STOP, sem fix)

> Observação primeiro. O "?" no resultado do usuário PROVA o normalizer novo ativo
> e que o identificador não está nas chaves conhecidas. RAW do MCP não observável
> nesta sessão (ferramenta host sem output p/ execução) — evidências de código/behavior.

## 1. Evidências observáveis

```
GATEWAY_NEW_PROCESS=YES (OLD 3902897 → NEW 3918330, reload confirmado pelo usuário)
RUNTIME_MODULE_CORRECT=YES (server_views unificado deployado — 16965 B)
_NORMALIZE_PORTS_RUNTIME_TEST=PASS (o "?" é o fallback novo — prova o normalizer ativo)
PORT_IDENTIFIER_PRESENT=NO nas chaves conhecidas (_PORT_IDENTIFIER_KEYS) → o normalizer
  caiu no fallback "?".
RESULTADO: 1 porta aberta de 1 · número = "?" (não None, não real)
```

## 2. RAW capture — NÃO OBSERVÁVEL nesta sessão (limitação técnica)

```
Tentativas de capturar COGNITIVE_PORTS_RAW/TOOL_PAYLOAD_PORTS via venv python do
runtime: sem output (ferramenta de acesso ao host não retorna execução de processo).
Caminho mapeado (por código): ProsperfySkill/MCP → Cognitive infra.inspect →
  result.data → _tool_payload(data, PORTS) → _normalize_ports.
RESOURCE_KEY=black-vps-homolog (caminho esperado)
MCP_TOOL / MCP_TOOL_ARGS / EXPECTED_PORT_FROM_INVENTORY: pendentes de observação
  (não capturáveis sem execução do runtime).
```

## 3. Confirmado por inspeção de código

```
INFRA_READ_PORTS_OPERATION_SCOPED=NO:
  infra_read_tools.py linha 93: view = servers_status(resource=resource_key) — executa o
  infra.inspect COMPLETO independente de operation. "operation" só é ecoado no resultado
  (linha 95/104/114) e lido do schema (linha 135) — NUNCA escopa a query.
  → operation="ports" é ignorado; a visão vem completa (não só portas).
```

## 4. Diagnóstico (com base nas evidências disponíveis)

```
FAILURE_BOUNDARY (provável, a confirmar com RAW): estrutura do payload REAL da tool de
  portas — o identificador está em localização não coberta por _PORT_IDENTIFIER_KEYS
  (possivelmente aninhado/outro nome), OU a tool retorna o número apenas em stdout/
  texto não estruturado.
ROOT_CAUSE: PENDENTE da observação do RAW (não é o normalizer — o "?" prova que ele
  está ativo e correto). Sem o RAW não é possível nomear a chave/estrutura real.
  Observação adicional de código: operation não é escopado (servers_status completo) —
  não é a causa do "?", mas é um desenho a considerar após o RAW.
```

## 5. Próximo passo (sem alteração agora)

```
Quando a ferramenta host permitir observação:
  1. capturar COGNITIVE_PORTS_RAW + TOOL_PAYLOAD_PORTS do Black (execução read-only)
  2. identificar a localização real do identificador (chave/estrutura)
  3. ENTÃO corrigir SOMENTE o mapeamento conforme o RAW.
Nenhum código alterado nesta execução. Router/Cognitive/Memory intactos.
```

## 6. Métricas

```
RESOURCE_KEY=black-vps-homolog · MCP_TOOL_ARGS=pendente RAW
COGNITIVE_PORTS_RAW=NOT_OBSERVABLE (tooling host) · TOOL_PAYLOAD_PORTS=NOT_OBSERVABLE
RAW_KEYS=— · PORT_IDENTIFIER_PRESENT=NO (evidência: fallback "?")
EXPECTED_PORT_FROM_INVENTORY=pendente · FAILURE_BOUNDARY=estrutura do payload real (a confirmar)
ROOT_CAUSE=PENDENTE (requer RAW) · INFRA_READ_PORTS_OPERATION_SCOPED=NO (código)
PRODUCTION_UNTOUCHED=YES · MASTER_UNTOUCHED=YES
```