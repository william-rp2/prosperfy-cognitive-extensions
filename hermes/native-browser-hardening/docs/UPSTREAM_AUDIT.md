# Auditoria upstream — browser nativo Hermes

Registro exigido pelo prompt de hardening (§12).

```text
HERMES_BROWSER_IMPLEMENTATION=agent-browser CLI + CDP supervisor (tools/browser_tool.py)
HERMES_VERSION=v0.21.3 (2026.9.14) — install /home/will/.hermes/hermes-v0213-stage
BROWSER_HARNESS_INSTALLED_VERSION=0.1.13 (browser-harness CLI local venv; não é o backend do profile qaprospersend)
BROWSER_USE_COMPONENTS_PRESENT=plugin browser-browser-use no core; não configurado (sem cloud)

UPSTREAM_UPLOAD_SUPPORT=agent-browser@0.26.0 expõe comando `upload <sel> <files...>`; Hermes v0.21.3 não registra tool browser_upload
UPSTREAM_CUSTOM_CLICK_SUPPORT=agent-browser: `find` (role/text/label/…), `get box`, `click @ref`; sem fallback automático no Hermes quando click falha
UPSTREAM_MODAL_EDITABLE_SUPPORT=agent-browser: `find role textbox|… fill`; supervisor CDP `Runtime.evaluate` (browser_console); Hermes browser_type só usa fill @ref

UPSTREAM_NEWER_VERSION_AVAILABLE=YES (hermes update disponível; main adiciona browser_cdp_tool, browser_vault_tool, browser_dialog_tool)
UPGRADE_RECOMMENDED=PARTIAL — avaliar merge main para tools CDP/vault; gaps desta entrega fechados via adapter fino + fallback genérico (este diretório)
```

Component owner: **NousResearch/hermes-agent** (`tools/browser_tool*.py`, `tools/browser_supervisor.py`).

Prosperfy overlay: branch runtime `prosperfy-v0213`; source versionado neste repo em `hermes/native-browser-hardening/`.
