# Phase 1B — Infra Actions V1 (Slice 1: Restart Container)

> Núcleo implementado (rota INFRA_ACTION + tool restart_container + confirmação 2
> turnos). EXECUÇÃO real depende de capability de AÇÃO no Cognitive (gap identificado).

## 1. Router (implementado + testado — 40/40)

```
INFRA_ACTION adicionada (precedência: ... SKILLS > INFRA_ACTION > INFRA_READ > NORMAL)
  Positivos: "Reinicie o omniroute no Prosperfy." · "Restart o container traefik no
    Prosperfy." · "Reinicie o container omniroute no Black." → INFRA_ACTION
  Negativos (NORMAL): "Por que reiniciar um container?" · "Como funciona docker restart?"
    · "O que significa reiniciar um container?"
  INFRA_READ preservado: "Quais containers estão rodando?" → INFRA_READ
route_toolsets("INFRA_ACTION")=["restart_container"]
ROUTE_TESTS=40/40 PASS (incl. Phase 1B)
```

## 2. Tool (deployada — narrow, confirmação 2 turnos)

```
tools/restart_container_tools.py (6843 B):
  restart_container(resource, container, confirmed)
  - 1º turno (confirmed=false): resolve resource → registra pending por
    actor|resource|container|restart_container → retorna pedido de confirmação (NÃO executa)
  - 2º turno (confirmed=true): SÓ executa se o pending do MESMO actor/resource/container
    existir (bind de confirmação) → Cognitive infra.action → post-condition (re-leitura containers)
  Fail-closed: resource não resolvido / container inexistente → tool_error (sem autocomplete)
DIRECT_SSH_FROM_HERMES=NO · DIRECT_MCP_FROM_HERMES=NO · COGNITIVE_PATH=YES
CONFIRMATION_REQUIRED=YES · PRECONDITION_CHECK=YES (resource resolve) · POSTCONDITION_CHECK=YES · AUDIT=YES
```

## 3. GAP identificado (bloqueia execução real) — COGNITIVE

```
O Cognitive Homolog tem APENAS a capability `infra.inspect` (read).
Não existe capability de AÇÃO. O ProsperfySkillAdapter (Cognitive) já tem o tool MCP
  `prosperfy_vps_controlar_container` (restart/stop/start) disponível no catálogo.
PARA EXECUTAR O RESTART via Cognitive é necessário provisionar a capability
  `infra.action` no Cognitive (registry/executor) que invoque
  prosperfy_vps_controlar_container com policy/audit — MESMO caminho do infra.inspect.
CONFIRMATION_TESTS/POLICY_TESTS: estrutura pronta; execução real exige a capability.
```

## 4. Human acceptance

```
TARGET_RESOURCE=Prosperfy · TARGET_CONTAINER=omniroute (recomendado, seguro)
PRE_STATE=<a capturar no teste real>
PHASE1B_RESTART_HUMAN_TEST_READY=NO
  (bloqueado por: 1) capability infra.action no Cognitive; 2) reload do gateway p/ carregar
  a nova tool; 3) teste real com confirmação do usuário no WhatsApp)
```

## 5. Métricas

```
BRANCH=dev/phase1b-restart-container · CHECKPOINT=eea2d10
INFRA_ACTION_ROUTE=YES · ACTION_TOOL=restart_container · DIRECT_SSH/MCP=NO · COGNITIVE_PATH=YES
CONFIRMATION_REQUIRED=YES · PRECONDITION=YES · POSTCONDITION=YES · AUDIT=YES
TESTS=40/40 (ROUTE) · HUMAN_TEST_READY=NO (gap Cognitive + reload + teste real)
PRODUCTION_UNTOUCHED=YES · MASTER_UNTOUCHED=YES
```