# RELEASE 0.1 — Manifest

Versionamento canônico consolidado da entrega Phase 1A (Infra Read V1) sobre o
Hermes Slim.

## Componentes

```
COGNITIVE_SHA=b70dd73   (prosperfy-cognitive-extensions, master — canônico)
HERMES_SHA=b58c8589     (Hermes runtime, branch prosperfy-canonical)
DEPLOYED_AT=2026-08-25
RUNTIME_PATH=/home/will/.hermes/hermes-clean
EXTENSION_SRC=/home/will/projetos/prosperfy-cognitive-gate-0.5/hermes/capability-intelligence/src
PYTHON_PATH=runtime venv (hermes-clean/venv → hermes-agent/venv)
SYSTEMD_UNIT=hermes-gateway.service
WHATSAPP_PORT=3000
```

## Estado canônico (master)

```
- Slim: normal chat 0 tools / 0 bytes
- capability_router (NORMAL/CRON/SESSION_SEARCH/MEMORY/SKILLS/INFRA_READ)
- infra_read tool narrow (Cognitive-only, read-only)
- /servidores determinístico (paralelo, 12 MCP, 0 LLM)
- display_name closure (Cognitive /v1/resources)
- host execution trust (confirmar:true + NORM parse + fail-closed)
- Cron/CRON tool availability · Session Search · Memory · Skills (on-demand)
- ss -tulpn port parser (Black 11 portas reais)
```

## Não incluído

```
- Memory On-Demand 0.7.8.4 (revertido — dívida no backlog)
- Phase 1B (Infra Actions) — não iniciada
- Browser Harness — bootstrap futuro não bloqueante
- PORTS_SCOPING_DEBT (operation="ports" não escopa — backlog)
```

## Secrets

```
Nenhum secret neste manifesto. Credenciais/env/session permanecem fora do Git
(ver plano de backup/restore).
```