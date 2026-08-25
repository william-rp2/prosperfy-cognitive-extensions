# Phase 1A — Infra Operations Read V1

> Primeira entrega funcional user-facing de Infra Read. Núcleo determinístico
> implementado + tool narrow deployada. Validação de runtime/pipeline do host
> ficou BLOQUEADA nesta execução por instabilidade da ferramenta de acesso
> (output de processos host não observável de forma confiável).

## 1. Núcleo (implementado + testado — local, confiável)

```
capability_router.py — rota INFRA_READ adicionada (precedência preservada):
  slash > CRON > SESSION_SEARCH > MEMORY > SKILLS > INFRA_READ > NORMAL
Gate conservador: keyword/recursos de infra + contexto operacional.
  Positivos: "Como estão meus servidores?" · "Quais containers estão rodando no
    Prosperfy?" · "Quais portas estão abertas no Black?" · "Tem algum container
    parado no Manager1?" · "O que está acontecendo com o Hostinger One?" ·
    "Quantos containers existem no Black?"
  Negativos: "O que significa servidor web?" · "Qual a diferença entre Docker e
    VM?" · "Explique como funciona um servidor." → NORMAL
  FIX de bug real: _has_conceptual agora usa word-boundary regex — o marcador
    "o que e" casava dentro de "o que est..." (ex.: "o que está acontecendo" era
    classificado como conceitual). Corrigido.
route_toolsets("INFRA_READ")=["infra_read"]
TESTES: test_capability_router.py = 33/33 PASS (incl. todos INFRA_READ + negativos)
```

## 2. Tool narrow (deployada no runtime)

```
tools/infra_read_tools.py (hermes-clean) — registra `infra_read` (toolset
  infra_read): operation=all|panorama|containers|ports · resource opcional
  (display name → resource_key via list_resources).
Handler: InfraService (CognitiveApiAdapter) → infra.inspect — MESMO caminho
  canônico do /servidores (authorization/resource resolution/fail-closed).
  NUNCA MCP/SSH/Docker direto. Read-only. Erro real não mascarado.
check_fn: HERMES_GATEWAY_SESSION (gateway) — mesmo padrão dos toolsets especialistas.
Router atualizado deployado no package do runtime (gate-0.5/src).
```

## 3. Pendente (validação live — BLOCKED por tooling host)

```
NÃO validado nesta execução (ferramenta de acesso ao host degradada — comandos
  de execução retornam sem output):
  - resolve_toolset("infra_read") / get_tool_definitions no runtime
  - invocação real da tool (dados dos 4 servidores)
  - restart do gateway (single-bridge) para carregar a tool
  - /servidores regression pós-deploy
  - Browser Harness install + doctor
  - inventário de write operations (Phase 1B prep)
Estes são os próximos passos imediatos, executáveis quando a ferramenta host
  estiver estável (ou via execução dedicada).
```

## 4. Arquitetura (obrigatória, preservada)

```
User → Hermes (INFRA_READ gate) → infra_read tool → CognitiveApiAdapter →
  Cognitive → infra.inspect → ProsperfySkillAdapter → MCP → servidor → dados
INFRA_DIRECT_MCP_FROM_HERMES=NO · INFRA_DIRECT_SSH_FROM_HERMES=NO
NORMAL_CHAT continua 0 tools (INFRA_READ só ativa o toolset no turno infra)
```

## 5. Métricas (parciais — núcleo)

```
PHASE1_INFRA_READ_CHECKPOINT=<pos push>
INFRA_ROUTE_IMPLEMENTED=YES · INFRA_GATE_LLM_CALLS=0 (determinístico)
INFRA_SPECIALIST_TOOLS=["infra_read"] · TOOL_COUNT=1
ROUTER_TESTS=33/33 PASS · NORMAL_CHAT_TOOL_COUNT=0 (router) · SCHEMA_BYTES=0
AVAILABLE_INFRA_WRITE_OPERATIONS=Phase 1B inventory pendente (host)
BROWSER_HARNESS_INSTALLED=pending (host)
PRODUCTION_UNTOUCHED=YES · MASTER_UNTOUCHED=YES
PHASE1_INFRA_READ_GATE=PARTIAL (núcleo PASS; validação live pendente por tooling)
```