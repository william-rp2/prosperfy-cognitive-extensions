# Cron Human Acceptance — Tool Availability Closure

> FAIL (CRON_TOOL_AVAILABLE_AT_EXECUTION) → ROOT CAUSE encontrado e corrigido.
> Router NÃO alterado. Pipeline real agora entrega a tool cronjob ao modelo.

## 1. Trace do pipeline real (evidência)

```
Input: "Me lembre daqui a 5 minutos de testar o Cron do Hermes."
ANTES do fix:
  CRON_INTENT=YES · RESOLVED_ENABLED_TOOLSETS=["cronjob"]
  registry: "check_fn check_cronjob_requirements returned False; dependent
            tools will be unavailable this turn"
  GET_TOOL_DEFS_CRONJOB_COUNT=0 → cronjob DESAPARECE aqui
  FINAL_TOOL_NAMES_SENT_TO_MODEL=[] → LLM sem a tool → "não consegui agendar"
```

## 2. ROOT CAUSE (boundary exato)

```
CRONJOB_TOOL_DISAPPEAR_BOUNDARY=registry.get_definitions → check_fn
CRONJOB_IMPORTED=YES · CRONJOB_REGISTERED=YES (registry.register no cronjob_tools.py)
CRONJOB_CHECK_FN_PASS=NO
ROOT_CAUSE: tools/cronjob_tools.py::check_cronjob_requirements() retorna:
    env_var_enabled("HERMES_INTERACTIVE") or
    env_var_enabled("HERMES_GATEWAY_SESSION") or
    env_var_enabled("HERMES_EXEC_ASK")
  O check DOCUMENTA suporte a "gateway/messaging platforms", mas o gateway
  NUNCA seta HERMES_GATEWAY_SESSION (grep: 0 ocorrências no gateway/hermes-clean)
  → em plataforma de mensageria a tool fica sempre UNAVAILABLE.
  Seleção do specialist (enabled_toolsets=["cronjob"]) estava correta — o
  filtro do registry derrubava a tool no momento de montar as defs do modelo.
```

## 3. FIX (mínimo, só o gap comprovado)

```
FIX: no branch cron de _resolve_enabled_toolsets_for_source (gateway/run.py),
  seta os.environ.setdefault("HERMES_GATEWAY_SESSION", "1") ANTES de retornar
  ["cronjob"] → o check_fn do registry passa no turno cron.
FIX_FILES=gateway/run.py (hermes-clean, branch prosperfy-cron-wiring)
FIX_LINES=6 (bloco try/os.environ no branch cron)
NÃO alterado: cron_router.py (intents/false-positive) · config global ·
  platform_toolsets · NÃO habilitou catalog/tool search/capabilities.
Segurança Slim: normal chat usa enabled_toolsets=[] → get_tool_definitions([])
  resolve 0 tools (verificado) — o env só deixa cronjob disponível quando o
  toolset cronjob é explicitamente selecionado no turno cron.
```

## 4. Validação (pipeline real, processo novo + live)

```
CRON:  is_cron_intent=True · RESOLVED=["cronjob"] · HERMES_GATEWAY_SESSION=1
       FINAL_TOOL_NAMES_SENT_TO_MODEL=["cronjob"] · CRONJOB_CALLABLE_REGISTERED=YES
       FINAL_TOOL_SCHEMA_BYTES=10172
NORMAL: enabled_toolsets=[] · FINAL_TOOLS=0 · SCHEMA_BYTES=0
CRONJOB_REQUIREMENTS={'name':'cronjob','tools':['cronjob'],'check_fn':check_cronjob_requirements}
CANDIDATE_SHA (hermes-clean)=6363af8b
Deploy single-bridge: stop → old bridge 0 → :3000 livre → start
  GW=MainPID 3354093 · NRestarts=0 · bridge node :3000 (sessão reutilizada)
VERIFY_SLIM=PASS (NORMAL_CHAT_TOOLS=0 · SCHEMA_BYTES=0 · CAPABILITY_FAIL_CLOSED=PASS)
```

## 5. Estado

```
CRON_TOOL_INVOKED/CRON_JOB_CREATED/PERSISTED/TRIGGERED/DELIVERED =
  PENDENTE HUMAN ACCEPTANCE (usuário repetirá a mensagem; 5 min depois o
  lembrete) — o pipeline de disponibilidade está FECHADO (tool chega ao modelo).
CRON_REAL_USER_PATH_ACTIVE=YES (routing + tool availability provados no pipeline real)
CRON_TOOL_CARRIED_OVER=NO (normal chat = [])
NORMAL_CHAT_TOOL_COUNT=0 · SCHEMA_BYTES=0
/SERVIDORES=pipeline inalterado (não re-testado nesta execução; código intacto)
HERMES_GATEWAY_ACTIVE=YES · SINGLE_BRIDGE=YES · UNEXPECTED_RESTARTS=0
PRODUCTION_UNTOUCHED=YES · SECRET_EXPOSED=NO · MASTER_UNTOUCHED=YES
FINAL_GATE=PASS (disponibilidade de tool no pipeline real); aguarda a repetição
  humana + trigger/delivery para CRON_HUMAN_ACCEPTANCE=PASS completo.
```