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

## MCP_PROSPERFYSKILLS_API_KEY — Provisioning Contract

`MCP_PROSPERFYSKILLS_API_KEY` is the secret `ProsperfySkillsAdapter`
(`core/cognitive/cognitive/adapters/prosperfy_skills/client.py`) sends as the
`Authorization: Bearer` header to `skills.prosperfy.com.br` when
`COGNITIVE_LIVE_MCP=1`. This section documents how it must be provisioned on
the VPS and where it must never appear. No secret was provisioned and no
Production system was touched while writing this — the steps below are for
the VPS operator to carry out later.

### Where to provision it

- Provision via a systemd **`EnvironmentFile=`** pointing at a file with
  permissions **`0600`**, owned by (and readable only by) the service user
  that runs the Cognitive API process. This repo has no `.service` unit
  checked in yet, so this is the recommended generic pattern to follow when
  the unit is created — not a description of an existing file.
  ```ini
  # /etc/prosperfy/cognitive-api.env — mode 0600, owner: cognitive-api service user
  MCP_PROSPERFYSKILLS_API_KEY=<value from secret store>
  ```
  ```ini
  # systemd unit
  [Service]
  EnvironmentFile=/etc/prosperfy/cognitive-api.env
  ```
- **Never** a `.env` file inside the git-tracked repo (`apps/cognitive-console/.env*`
  or any `core/cognitive/.env*`) — those are for non-secret, buildable config only,
  and Console `.env` files are bundled into the browser at build time.
- **Never** baked into a Docker image layer (`ENV MCP_PROSPERFYSKILLS_API_KEY=...`
  in a `Dockerfile`, or `ARG`/`COPY` of a file containing it) — image layers are
  cacheable/inspectable artifacts.
- **Never** passed as a plain CLI argument or inline env prefix
  (`MCP_PROSPERFYSKILLS_API_KEY=xxx uvicorn ...`) — both are visible to any
  local user via `ps`/`/proc/<pid>/cmdline`/`/proc/<pid>/environ`.

### Where it must NEVER appear

- Frontend / Console bundle (`apps/cognitive-console/`) — never as a
  `VITE_*` variable. Vite exposes every `VITE_`-prefixed variable to the
  browser bundle; this key has no `VITE_` counterpart and none should ever
  be added. Audited: `apps/cognitive-console/.env.example`,
  `src/config/env.ts`, `src/vite-env.d.ts` — confirmed clean.
- OpenAPI schema/docs (`/openapi.json`, `/docs`, `/redoc`) — the key is never
  part of any request/response model.
- `GET /health` or `GET /v1/status` response bodies
  (`core/cognitive/cognitive/gateway/routes/health.py`,
  `.../routes/status.py`) — audited: neither route reads or exposes this
  variable, not even as a boolean. `status.py` only reports
  `db_configured` (unrelated DB DSNs). No new field was added for this key
  — the codebase's existing surface is already clean and the smallest safe
  choice is to add nothing.
- Audit events (`core/cognitive/cognitive/audit/`) — `AuditEvent.inputs_redacted`
  passes through `audit/redaction.py`'s `redact()`, which always strips any
  field named `api_key`, `secret`, `token`, `credential`, or `bearer`
  (`_ALWAYS_REDACT`), independent of configuration. `result_summary` in
  `execution/orchestrator.py` only ever carries `{"reason": ...}` or
  `{"tool_calls": ..., "error": ...}` — the orchestrator never reads
  `os.environ` or adapter internals directly.
- Telemetry records (`core/cognitive/cognitive/telemetry/recorder.py`) —
  `TelemetryRecord` is a fixed dataclass (tenant/actor/capability/correlation
  id, latency, tool_calls, token/cost estimates); it has no field capable of
  carrying the key.
- Exception messages — `ProsperfySkillsAdapter.invoke_tool()` lets
  `httpx.HTTPStatusError`/`httpx.HTTPError` propagate unmodified.
  `httpx.HTTPStatusError.__str__()` renders only method, URL, and status
  text (verified: `"Client error '401 Unauthorized' for url '...'\nFor more
  information check: ..."`) — it never includes request headers, so the
  `Authorization: Bearer <key>` value cannot leak through
  `str(exc)`/`logger.exception(...)` anywhere in `client.py`,
  `gateway/app.py`, or `execution/orchestrator.py`.
- Application logs — `client.py`'s `_headers()` builds the Authorization
  header inline per-request and is never logged; `invoke_tool()`'s debug log
  line only includes `tool_name`/`tenant`/`correlation_id`.

### Fail-closed contract (implemented this session)

`core/cognitive/cognitive/gateway/app.py` now runs an eager, startup-time
check in `_build_services()`, **before** `ProsperfySkillsAdapter()` is
constructed:

- `COGNITIVE_LIVE_MCP=1` and `MCP_PROSPERFYSKILLS_API_KEY` unset, empty, or
  whitespace-only ⇒ `_require_live_mcp_secret()` raises:

  ```
  RuntimeError: COGNITIVE_LIVE_MCP=1 exige MCP_PROSPERFYSKILLS_API_KEY configurada
  (env var ausente, vazia ou somente espaços). Configure o secret via
  EnvironmentFile do systemd (0600, service user) antes de iniciar o
  gateway — ver docs/cognitive-v2/COGNITIVE-DEPLOY-READINESS.md.
  ```

  This exception is **uncaught** — it propagates out of `_build_services()`,
  out of `create_app()`, and out of the module-level `app = create_app()` in
  `gateway/app.py`, which fails the entire process before `uvicorn` ever
  binds a port. There is no code path where this becomes a logged warning
  that the process survives.

- `COGNITIVE_LIVE_MCP=1` and the key present (non-empty after `.strip()`) ⇒
  no exception; `ProsperfySkillsAdapter()` is constructed normally.

- `COGNITIVE_LIVE_MCP=0` (or unset — the default) ⇒ this check does not run
  at all; `MockSkillsAdapter()` is used and no real MCP connection is ever
  attempted, regardless of whether `MCP_PROSPERFYSKILLS_API_KEY` is set.
  (Confirmed by reading the existing `_build_services()` branch — this was
  already true before this session's change, unmodified here.)

This is defense in depth alongside the existing, unmodified late check in
`ProsperfySkillsAdapter.invoke_tool()` (`client.py`), which still raises
`RuntimeError("MCP_PROSPERFYSKILLS_API_KEY não configurada")` if the key is
missing at call time — covering the unusual case where an operator unsets
the env var after startup without restarting the process.

Test coverage: `core/cognitive/tests/unit/test_mcp_secret_contract.py`.

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
