# QA Browser ProsperSend — fechamento de hardening (2026-09-28)

## Arquitetura

```text
Hermes (perfil qaprospersend)
  → plugin prospersend-qa-browser
  → Cognitive Gateway /v1/browser/qa (homolog)
  → Browser Worker remoto (primary, Hostinger One :9122)
  → fallback browser local (failover)
```

## Componentes versionados

| Área | Caminhos |
|------|----------|
| Worker | `ops/browser-worker/worker.py`, `http_service.py`, `field_resolver.py` |
| Contrato | `ops/browser-worker/test_qa_contract.py` |
| Homolog live | `qa_stack_gate.py`, `qa_stack_spa.py`, `qa_regression_homolog.py` |

Deploy runtime worker: `/opt/browser-worker/` (Hostinger One). O source de referência é o branch `feat/qa-browser-prospersend-hardening` (PR #1).

## Capacidades entregues

- **Login:** `secret_ref` via gateway/worker; sem eco de senha/JWT nos payloads de diagnóstico.
- **Cliques Vue/Radix:** resolução semântica, ancestral customizado, CDP por coordenadas.
- **Upload Documentos:** input hidden, dropzone por texto (`selecione do computador`), file chooser dinâmico, eventos `input`/`change`, screenshot de evidência, tempfile `0600` em workdir isolado por job (removido ao fim do job).
- **Field resolver:** label (`for`, wrapper shadcn), `aria-label`, placeholder, `near_text`, `editable_any`, `active`, contenteditable; tabpanel Radix vazio faz fallback para `main`/document.
- **Wizard Estratégia:** rota `/estrategias/nova`, fluxo oferta → objetivo → intenção (`editable_any` + `wait_enabled` em Continuar); sem concluir criação desnecessária.
- **Inspect:** `inputs`, `editable_candidates`, `interactive_candidates`, `file_inputs`, `buttons`, URL atual; omitir `url` preserva aba/step; redaction de JWT/sensíveis.
- **CT-03:** self-service de perfil QA documentado operacionalmente (fora deste repo).

## Segurança (boundaries)

- `PROSPERSEND_CHANGED=NO`, `PROSPERFYSKILL_CHANGED=NO`
- Allowlist de host; sem shell/DB para o bot QA
- Sem commit de secrets; relatórios sem senhas/tokens

## Regressão homolog

Executar no host Prosperfy (perfil Hermes configurado):

```bash
cd /home/will/projetos/prosperfy-qa-browser-closure/ops/browser-worker
python3 qa_regression_homolog.py
```

Fases SPA (`QA_SPA_PHASE`):

- `inspect_contract` — shape do inspect + current tab
- `document_upload` — Documentos + upload + screenshot
- `field_product_radix` — aba Quem compra + label
- `strategy_wizard` — wizard validado
- `vue_custom` — cliques customizados
- `cleanup_qa_products` — URLs registradas em `/tmp/qa_browser_cleanup_urls.json`

Unitários (sem browser):

```bash
QA_CONTRACT_UNIT=1 python3 test_qa_contract.py
```

## Evidência E2E (2026-09-28)

```text
LOGIN_OK True
UPLOAD True hidden-input
FIELD_LABEL True
WIZARD True
E2E_DONE
```

Commits de referência: `27495f2` (Vue click), `2ce2846` (upload/fields), `58a4d95`/`2d2b95e` (field resolver + fix).

## Rollback

1. Worker: restaurar `/opt/browser-worker/` a partir do commit anterior (`git show <sha>:ops/browser-worker/...` + restart `prosperfy-browser-worker.service`).
2. Cognitive homolog: restaurar `browser_qa.py` no gate homolog e restart `prosperfy-cognitive-homolog-api.service`.
3. Hermes: plugin/SOUL operacionais — reverter apenas se contrato antigo for necessário.

## Manutenção

- Não reabrir gaps já PASS sem regressão comprovada.
- GitHub Actions: usar `[skip ci]` enquanto cota de minutos estiver esgotada.
- Após cada alteração em `field_resolver.py` ou `worker.py`, sincronizar Hostinger e validar `qa_regression_homolog.py`.
