#!/usr/bin/env bash
# sync-plugin.sh — Sincroniza plugin do repositório para runtime
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
EXTENSAO="${1:-capability-intelligence}"

echo "🔄 Sincronizando plugin: ${EXTENSAO}"
bash "${REPO_DIR}/scripts/install-plugin.sh" "${EXTENSAO}"
echo "✅ Sincronização concluída."