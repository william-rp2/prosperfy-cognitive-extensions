#!/usr/bin/env bash
# apply_memory_on_demand.sh — Sprint 0.7.8.4 MEMORY-ONLY patch (no deploy).
#
# Idempotent via marker prosperfy-memory-snapshot-0784 in gateway/run.py.
# Aborts on git apply conflict — never auto-resolves.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
RUNTIME="${1:-${HOME}/.hermes/hermes-clean}"
PATCH="${ROOT}/ops/hermes/update/memory_on_demand.patch"
MARKER="prosperfy-memory-snapshot-0784"
FORBIDDEN="resolve_specialist_route|prosperfy_slim_boundary|_maybe_execute_memory_write|resolve_slim_turn"

if [[ ! -d "${RUNTIME}" ]]; then
  echo "RUNTIME_MISSING=${RUNTIME}"
  exit 1
fi

if grep -Eq "${FORBIDDEN}" "${PATCH}"; then
  echo "PATCH_FORBIDDEN_CONTENT=YES"
  exit 1
fi

if grep -q "${MARKER}" "${RUNTIME}/gateway/run.py" 2>/dev/null; then
  echo "PATCH_ALREADY_APPLIED=YES marker=${MARKER}"
else
  if ! grep -q "skip_memory_snapshot_in_prompt" "${PATCH}"; then
    echo "PATCH_INVALID=missing skip_memory_snapshot_in_prompt"
    exit 1
  fi

  BACKUP_DIR="${HOME}/.hermes/backups/memory-on-demand-$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "${BACKUP_DIR}"
  cp -p "${RUNTIME}/agent/agent_init.py" "${BACKUP_DIR}/"
  cp -p "${RUNTIME}/agent/system_prompt.py" "${BACKUP_DIR}/"
  cp -p "${RUNTIME}/gateway/run.py" "${BACKUP_DIR}/"
  echo "BACKUP_DIR=${BACKUP_DIR}"

  cd "${RUNTIME}"
  if ! git apply --check "${PATCH}" 2>/dev/null; then
    echo "PATCH_CONFLICT=YES — restore from ${BACKUP_DIR}; manual host reconciliation required"
    exit 1
  fi
  git apply "${PATCH}"
  # Insert marker comment for idempotency (patch uses descriptive comment already)
  if ! grep -q "${MARKER}" gateway/run.py; then
    echo "MARKER_MISSING_AFTER_APPLY=YES"
    exit 1
  fi
  echo "PATCH_APPLIED=git-apply"
fi

if [[ -x "${RUNTIME}/venv/bin/python" ]]; then
  HERMES_AGENT_DIR="${RUNTIME}" "${RUNTIME}/venv/bin/python" "${ROOT}/ops/hermes/update/verify_memory_on_demand.py" || exit 1
fi

echo "DEPLOY=NO — operator runs single-bridge restart separately"
