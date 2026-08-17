# Cognitive Deploy Readiness (Homolog + Console)

No deploy performed by this document. DNS/VPS unchanged.

## Hostnames

| Surface | Homolog | Production (future) |
|---------|---------|---------------------|
| API | `api-cognitive-homolog.prosperfy.com.br` | `api-cognitive.prosperfy.com.br` |
| Console | `cognitive.prosperfy.com.br` | same (env-driven API target) |

## API (Cognitive Gateway)

### Build / install

```bash
cd core/cognitive
pip install -e ".[dev]"
```

### Start (Homolog example)

```bash
export COGNITIVE_ENV=homolog
export COGNITIVE_MODE=database
export COGNITIVE_API_VERSION=0.2.0
export COGNITIVE_HOST=0.0.0.0
export COGNITIVE_PORT=8800
# secrets from remote store — never in Git:
# COGNITIVE_DB_ADMIN_URL, COGNITIVE_APP_PASSWORD, COGNITIVE_WORKER_PASSWORD
# COGNITIVE_DB_URL, COGNITIVE_DB_WORKER_URL (post-bootstrap)

uvicorn cognitive.gateway.app:app --host $COGNITIVE_HOST --port $COGNITIVE_PORT
```

### Health check

- `GET /health` — public liveness
- `GET /v1/status` — authenticated operational status

### Reverse proxy

- Terminate TLS at nginx/caddy
- Proxy to `127.0.0.1:8800`
- Forward headers: `Authorization`, `X-Tenant-Id`, `X-Actor-Id`, `X-Correlation-Id`

### CORS (Console → API)

```bash
export COGNITIVE_CORS_ORIGINS=https://cognitive.prosperfy.com.br
```

### OpenAPI

- Swagger UI: `/docs`
- Schema: `/openapi.json`

## Console (React)

### Build

```bash
cd apps/cognitive-console
npm install
npm run check
```

### Env (Homolog)

```bash
VITE_COGNITIVE_ENV=homolog
VITE_COGNITIVE_API_BASE_URL=https://api-cognitive-homolog.prosperfy.com.br
VITE_COGNITIVE_TEST_TENANT=...
VITE_COGNITIVE_TEST_ACTOR=...
VITE_COGNITIVE_TEST_CREDENTIAL=...
```

### Preview / static serve

```bash
npm run build
npm run preview
```

Production static files: `apps/cognitive-console/dist/`

### Security

- Browser talks **only** to Cognitive API
- Never expose DB DSNs or admin credentials to frontend env

## Gate (post-deploy validation)

```bash
python scripts/sprint_0_2_remote_gate.py full-gate
```

See also `scripts/GATE-RUNTIME.md`.

## Python on Ubuntu 24.04

If `python3 -m venv` fails:

```bash
sudo apt install python3.12-venv
```

Minimum Python: **3.11+**
