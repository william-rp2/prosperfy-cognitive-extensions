#!/usr/bin/env bash
# install-release-0.1.sh — Bootstrap reproduzível (Ubuntu novo).
# SEM secrets. Separa SOURCE / CONFIG / SECRETS / RUNTIME_STATE.
set -euo pipefail

echo "== Hermes Prosperfy Release 0.1 bootstrap =="
echo "Usage: sudo bash $0 [hermes_agent_dir]"

AGENT_DIR="${1:-$HOME/hermes-agent}"

# 1. SOURCE — extensão canônica (prosperfy-cognitive-extensions, master)
EXT_REPO="${HOME}/prosperfy-cognitive-extensions"
if [ ! -d "$EXT_REPO/.git" ]; then
  git clone https://github.com/william-rp2/prosperfy-cognitive-extensions.git "$EXT_REPO"
fi
git -C "$EXT_REPO" fetch origin master
git -C "$EXT_REPO" checkout -f origin/master

# 2. Hermes upstream (base reconciliada: b6bcb3e7 + slim overlay)
if [ ! -d "$AGENT_DIR/.git" ]; then
  git clone https://github.com/NousResearch/hermes-agent.git "$AGENT_DIR"
fi
git -C "$AGENT_DIR" fetch origin main

# 3. Dependências (uv/venv)
command -v uv >/dev/null 2>&1 || pip install --user uv
python3 -m venv "$AGENT_DIR/venv" 2>/dev/null || true

# 4. Overlay Slim + capability router (patches canônicos no repo da extensão)
cd "$AGENT_DIR"
git apply "$EXT_REPO/ops/hermes/update/slim.patch.candidate-b6bcb3e7" 2>/dev/null || \
  echo "slim patch: apply manual (candidate para b6bcb3e7)"
# gateway/run.py capability router wiring: ver hermes/phase1-infra-read e
# docs/reports (overlay aplicado manualmente ou via patch canônico).

# 5. Extension install (capability_intelligence no PYTHONPATH do runtime)
EXT_SRC="$EXT_REPO/hermes/capability-intelligence/src"
echo "PYTHONPATH inclui: $EXT_SRC (deploy em /home/will/projetos/prosperfy-cognitive-gate-0.5/... no live)"

# 6. CONFIG / SECRETS / RUNTIME_STATE — NÃO estão no Git.
cat <<'EOF'
Após o bootstrap, provisione MANUALMENTE (não versionado):
  CONFIG   -> ~/.hermes/config.yaml  (platform_toolsets=[] + mcp_servers + model)
  SECRETS  -> ~/.hermes/.env         (COGNITIVE_*, MCP_PROSPERFYSKILLS_API_KEY, ...)
  STATE    -> ~/.hermes/platforms/whatsapp/session (creds.json — sessão pareada)
              ~/.hermes/memories · ~/.hermes/cron · ~/.hermes/sessions · ~/.hermes/skills
EOF

# 7. systemd user service (exemplo; ajustar ExecStart)
cat <<'EOF'
systemd user unit (hermes-gateway.service):
  ExecStart=/path/venv/bin/python -m hermes_cli.main gateway run
  WorkingDirectory=/home/USER
  Environment=HERMES_HOME=/home/USER/.hermes
  Restart=always
EOF

# 8. Validação
cd "$AGENT_DIR"
venv/bin/python -c "import hermes_cli; print('IMPORT_OK')"
echo "BOOTSTRAP_STAGE=SOURCE_READY (config/secrets/state são provisionados à parte)"