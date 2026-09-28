# Hermes — hardening do browser nativo (overlay Prosperfy)

Implementação genérica dos gaps **upload**, **click customizado** e **modal/editable**, conforme `PROMPT-HERMES-NATIVE-BROWSER-HARDENING.md`.

## Source of truth

- **Repositório:** `prosperfy-cognitive-extensions` → `hermes/native-browser-hardening/`
- **Runtime alvo:** `/home/will/.hermes/hermes-v0213-stage` (branch `prosperfy-v0213`, Hermes v0.21.3)
- **Component owner upstream:** [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) (`tools/browser_tool.py`)

## Aplicar no VPS (Prosperfy)

```bash
# 1) Sincronizar este diretório no host (git pull ou rsync)
# 2) Aplicar overlay + patch idempotente
export HERMES_NATIVE_OVERLAY=/home/will/projetos/prosperfy-cognitive-extensions/hermes/native-browser-hardening/tools
python3 /home/will/projetos/prosperfy-cognitive-extensions/hermes/native-browser-hardening/scripts/apply_runtime_patch.py

# 3) Validar tools do profile QA (sem reiniciar gateway)
cd /home/will/.hermes/profiles/qaprospersend
set -a; . ./.env; set +a
export BROWSER_CDP_URL=http://127.0.0.1:9223
/home/will/.hermes/hermes-v0213-stage/venv/bin/hermes -p qaprospersend tools list | grep browser_upload
```

## Testes locais (contrato)

```bash
python -m unittest discover -s hermes/native-browser-hardening/tests -p "test_*.py" -v
```

## E2E (obrigatório pós-deploy)

Turnos reais `hermes -p qaprospersend chat` conforme seções 14–18 do prompt (upload, click, modal, segunda app, regressão). **Não fechados nesta sessão** até o overlay estar no runtime.

## Rollback runtime

```bash
cp /home/will/.hermes/hermes-v0213-stage/tools/browser_tool.py.bak-native-hardening \
   /home/will/.hermes/hermes-v0213-stage/tools/browser_tool.py
rm -f /home/will/.hermes/hermes-v0213-stage/tools/browser_tool_generic_fallback.py
```
