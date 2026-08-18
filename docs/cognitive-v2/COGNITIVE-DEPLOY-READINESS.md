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
```

`VITE_COGNITIVE_API_BASE_URL` is **required** in every environment — there is no
hardcoded fallback in code (CONSOLE-003). If it's missing at build/runtime the
Console shows a Configuration Error screen instead of guessing an API target
(it will never silently fall back to the production API).

There is intentionally **no** `VITE_COGNITIVE_TEST_CREDENTIAL` build var (CONSOLE-001).
The Homolog bearer credential is a secret and must never be baked into the
Vite bundle — Vite inlines referenced `VITE_*` vars into the shipped JS,
which is world-readable via view-source/devtools. It is entered at runtime
in the Console UI ("Homolog Test Session" panel, shown when
`VITE_COGNITIVE_ENV=homolog`) and kept only in that browser tab's
`sessionStorage`. See `apps/cognitive-console/src/config/session.ts`.

### Preview / static serve

```bash
npm run build
npm run preview
```

Production static files: `apps/cognitive-console/dist/`

`npm run preview` (Vite's own static server) correctly serves `index.html`
for any unknown path by default (`appType: 'spa'`), so direct loads/refreshes
of `/`, `/capabilities`, `/execute`, etc. all return 200 locally — verified
in Sprint 0.3.

**Production gap (CONSOLE-002, out of Console ownership):** in Homolog the
`dist/` output is served by Traefik on the VPS
(`/opt/traefik/dynamic/cognitive-homolog.yml`), not by `vite preview`. Static
file servers/reverse proxies do **not** get SPA fallback for free — a direct
request or refresh on `/capabilities` or `/execute` will 404 unless the proxy
is configured to serve `index.html` for any path that doesn't match a static
asset. This repo has no filesystem access to the VPS/Traefik config, so this
cannot be fixed from `apps/cognitive-console/`. Whoever owns
`cognitive-homolog.yml` needs to add an SPA-fallback rule, e.g. (Traefik file
provider, conceptually):

```yaml
# /opt/traefik/dynamic/cognitive-homolog.yml (illustrative — actual syntax
# depends on how the console dist/ is currently served, e.g. via a
# file-server middleware, a small static container, or Traefik's own
# staticFile handling)
#
# Requirement: any request path under the console host that does not match
# a real file in dist/ (no file extension, or unresolved dist/<path>) must
# be rewritten/served as dist/index.html with a 200, not a proxy 404.
```

If the console is served by a small static-file container (nginx/caddy/serve)
behind Traefik rather than by Traefik's static handling directly, the
equivalent fix belongs in that container's config (e.g. nginx
`try_files $uri /index.html;`, or `serve -s dist`). Either way, the fix is
outside this worktree's reach — flagging for the Lead Dev / infra owner.

### Security

- Browser talks **only** to Cognitive API
- Never expose DB DSNs or admin credentials to frontend env
- Never expose the Homolog test bearer credential via a build-time `VITE_*`
  var — see CONSOLE-001 above

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
