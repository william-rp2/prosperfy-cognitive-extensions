# Browser Worker (Track BH)

Isolated Browser Harness worker. Runs on a dedicated host, never the
operator's personal Chrome (doc 00 Sec.5). Current deploy target: **Hostinger
One** (147.93.67.71) -- "ainda sem destino, talvez teste" per inventory,
approved for this use in the Track BH brief. Never Black (client
production) or Prosperfy (Hermes/Cognitive Homolog host).

## Components

- `worker.py` -- stdlib-only job runner. One job per invocation (JSON on
  stdin, JSON on stdout), isolated `/tmp/browser-jobs/<job_id>/` per job,
  hard timeout, fail-closed content scan before any submit/click.
- `browser-harness-chrome.service` -- systemd unit for a dedicated headless
  Chrome with a CDP endpoint on `127.0.0.1:9222` (loopback only).
- `test_worker.py` -- unit tests for the pure logic (blocker scan, secret_ref
  resolution, fetch-vs-browser heuristic). `python3 ops/browser-worker/test_worker.py -v`.

## Why `BU_CDP_URL` (not the default doctor flow)

`browser-harness --doctor` / the default daemon flow looks for a running
browser by checking `SingletonLock` inside the OS-default profile dirs
(`~/.config/google-chrome`, etc. -- see `browser_harness/daemon.py`,
`supported_browser_running()`). A dedicated, isolated Chrome on a private
`--user-data-dir` (this is exactly what we want -- never the personal
profile) is invisible to that check even though its CDP port answers fine.

The package's own recommended pattern for a dedicated automation Chrome is
`BU_CDP_URL` (see `daemon.py` comment: "avoids the M144 'Allow remote
debugging' dialog and the M136 default-profile lockdown"). Every
`worker.py` invocation of `browser-harness` sets
`BU_CDP_URL=http://127.0.0.1:9222`, which polls `/json/version` on that URL
directly and skips the default-profile scan entirely.

## Deploy (Hostinger One)

```bash
# 1. Runtime (already present at last check: uv 0.12.6, google-chrome, python 3.12.3)
uv tool install --python 3.12 --upgrade --force browser-harness

# 2. Dedicated Chrome, persistent across SSH-exec sessions.
#    NOTE: a plain `nohup ... & disown` from an SSH-exec command dies when
#    that exec's login session/cgroup is torn down (systemd-logind kills
#    stray user-session processes) -- confirmed live on this host. Use a
#    real systemd unit instead (system-level; this host has no unprivileged
#    service user provisioned, so it runs as root -- see REMAINING_GAPS in
#    the Track BH report for the least-privilege follow-up).
cp browser-harness-chrome.service /etc/systemd/system/browser-harness-chrome.service
systemctl daemon-reload
systemctl enable --now browser-harness-chrome.service
systemctl status browser-harness-chrome --no-pager

# 3. Worker script + secrets dir (SecretBroker convention, 0600/0700).
mkdir -p /opt/browser-worker
cp worker.py /opt/browser-worker/worker.py
mkdir -p ~/.hermes/secrets/browser
chmod 700 ~/.hermes/secrets/browser

# 4. Smoke test.
export PATH="/root/.local/bin:$PATH"
export BU_CDP_URL="http://127.0.0.1:9222"
echo '{"job_id":"smoke-1","action":"doctor"}' | python3 /opt/browser-worker/worker.py
```

## Job contract

See the module docstring in `worker.py`. Cognitive's `BrowserAdapter`
(`core/cognitive/cognitive/adapters/browser_harness/client.py`) is the only
caller: it writes the job JSON to a remote tmp file via
`prosperfy_vps_escrever_arquivo`, runs
`python3 /opt/browser-worker/worker.py < <jobfile>` via
`prosperfy_vps_executar`, and parses the single JSON line on stdout.

## Secrets

Convention matches the approved pattern already in production for
Hermes/Cognitive (`EnvironmentFile=`, 0600, outside git and outside logs):
`~/.hermes/secrets/browser/<alias>.env` containing one line,
`SECRET_VALUE=<csprng-token>`. `worker.py` reads this file directly, in its
own process, only at the instant a `secret_ref:<alias>` field is filled --
the value never round-trips through Cognitive/the LLM (see
`cognitive/secrets/broker.py` for the generation side).

## Known limitation

Single shared Chrome/CDP endpoint for the whole host -- concurrent jobs
from different tenants are not yet queued/locked. Fine for the current low
volume + E2E validation; flagged as a REMAINING_GAP for real multi-tenant
concurrency.
