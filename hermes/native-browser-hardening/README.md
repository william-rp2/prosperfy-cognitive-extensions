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

Patch de integração: **`scripts/apply_runtime_patch.py`** é a única fonte de verdade para `browser_tool.py` (não há patch `.patch` paralelo).

## E2E (homolog `qaprospersend`, browser nativo)

| Resultado | Status |
|-----------|--------|
| `GAP1_UPLOAD_NATIVE_E2E` | PASS |
| `GAP2_SPA_DYNAMIC_E2E` | PASS |
| `QA_CTS_UPLOAD_UNBLOCKED` | YES |
| `QA_CTS_DYNAMIC_LIST_UNBLOCKED` | YES |

Observação (não blocker): `LAZY_DROPZONE_STRICT_E2E=NOT_EXERCISED` — na aba Documentos medida, `INITIAL_FILE_INPUT_COUNT=1`; ramo `lazy-dropzone-then-upload` coberto por testes unitários.

Pós-deploy: revalidar turnos reais `hermes -p qaprospersend chat` quando o overlay mudar; conferir `SOURCE_RUNTIME_MATCH` (fallback + contratos em `browser_tool.py` via `verify_patched_browser_tool`).

## Rollback runtime

```bash
cp /home/will/.hermes/hermes-v0213-stage/tools/browser_tool.py.bak-native-hardening \
   /home/will/.hermes/hermes-v0213-stage/tools/browser_tool.py
rm -f /home/will/.hermes/hermes-v0213-stage/tools/browser_tool_generic_fallback.py
```
