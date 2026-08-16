# Prosperfy Cognitive Core V2

Gateway independente do Hermes. Implementa a fundação multi-tenant:
`AUTH → TENANT/ACTOR → RESOURCE → CAPABILITY → GRANT → POLICY → EXECUTOR → ADAPTER`

## Stack

- Python 3.11+ / FastAPI / Pydantic v2
- YAML-based Capability Registry
- MockSkillsAdapter (dev/CI) | ProsperfySkillsAdapter (COGNITIVE_LIVE_MCP=1)

## Instalação

```bash
cd core/cognitive
pip install -e ".[dev]"
```

## Executar o Gateway

```bash
COGNITIVE_GATEWAY_CREDENTIAL=dev-secret \
COGNITIVE_DEV_TENANT_ID=prosperfy \
COGNITIVE_DEV_ACTOR_ID=william \
uvicorn cognitive.gateway.app:app --host 0.0.0.0 --port 8800 --reload
```

## Testes

```bash
pytest tests/ -v --tb=short
```

## Smoke test

```bash
curl -s \
  -H "Authorization: Bearer dev-secret" \
  -H "X-Tenant-Id: prosperfy" \
  -H "X-Actor-Id: william" \
  http://localhost:8800/v1/status | python -m json.tool

curl -s -X POST \
  -H "Authorization: Bearer dev-secret" \
  -H "X-Tenant-Id: prosperfy" \
  -H "X-Actor-Id: william" \
  -H "Content-Type: application/json" \
  -d '{"params": {"resource": "prosperfy-main"}}' \
  http://localhost:8800/v1/capabilities/infra.inspect/execute | python -m json.tool
```

## Status

Sprint 0.1 — Core in-memory. Ver `docs/cognitive-v2/SESSION-HANDOFF.md`.

### O que NÃO está incluído (Sprint 0.1)

- Banco de dados / Postgres / migrations (Sprint 0.2)
- RLS real (Sprint 0.2)
- MCP live (Sprint 0.3, flag `COGNITIVE_LIVE_MCP=1`)
- Projects/Tasks, RAW, Workflow (Fases 1–3)
