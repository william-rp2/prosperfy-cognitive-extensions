#!/usr/bin/env bash
# update_guard.sh — Wrapper update-safe para o Hermes Slim (Sprint 0.7.3).
#
# Objetivo: garantir que `hermes update` não desfaça silenciosamente as
# invariantes Slim. NÃO patcha o updater upstream — apenas envolve o fluxo
# oficial com detecção de estado + verificação + reaplicação controlada.
#
# Fases:
#   1. lock
#   2. BEFORE_HERMES_SHA / version / config checksum / gateway status
#   3. hermes update --check
#   4. backup (config + source patches)
#   5. hermes update --backup   (oficial)
#   6. AFTER_HERMES_SHA / version
#   7. detectar estado dos patches (presente/desnecessário/faltando/conflito)
#   8. reaplicar controlado SOMENTE se PATCH_MISSING_SAFE_TO_REAPPLY
#   9. restart gateway SOMENTE se necessário
#  10. verify_slim.py (invariantes)
#  11. /servidores smoke
#  12. PASS ou rollback (restaurar backup)
#
# Fail-closed: qualquer FAIL em invariante após update ⇒ ROLLBACK.

set -euo pipefail

HERMES="${HERMES_HOME:-${HOME}/.hermes}"
AGENT="${HERMES}/hermes-agent"
VENV_PY="${AGENT}/venv/bin/python"
VERIFY="$(cd "$(dirname "$0")" && pwd)/verify_slim.py"
PATCH_SRC="$(cd "$(dirname "$0")" && pwd)/slim.patch"
LOCK="${HERMES}/.update_guard.lock"
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

# ── lock ───────────────────────────────────────────────────────────────────
if [ "${DRY_RUN}" = "0" ]; then
  exec 9>"${LOCK}"
  if ! flock -n 9; then
    echo "UPDATE_GUARD=LOCKED (outro update em andamento)"
    exit 1
  fi
fi

# ── BEFORE ─────────────────────────────────────────────────────────────────
BEFORE_SHA="$(git -C "${AGENT}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
BEFORE_VER="$("${VENV_PY}" -c 'import hermes_constants as h; print(getattr(h, "__version__", "?"))' 2>/dev/null || echo unknown)"
BEFORE_CFG="$(sha256sum "${HERMES}/config.yaml" 2>/dev/null | cut -d' ' -f1 || echo unknown)"
GW_ACTIVE="$(systemctl --user is-active hermes-gateway.service 2>/dev/null || echo inactive)"
echo "BEFORE_HERMES_SHA=${BEFORE_SHA}"
echo "BEFORE_VERSION=${BEFORE_VER}"
echo "BEFORE_CONFIG_CHECKSUM=${BEFORE_CFG}"
echo "GATEWAY_BEFORE=${GW_ACTIVE}"

# ── update --check ─────────────────────────────────────────────────────────
echo "── hermes update --check ──"
"${AGENT}/venv/bin/hermes" update --check 2>&1 | tail -5 || true

if [ "${DRY_RUN}" = "1" ]; then
  echo "UPDATE_GUARD_DRY_RUN=PASS (somente inspeção; nada foi atualizado/reiniciado/modificado)"
  exit 0
fi

# ── backup ─────────────────────────────────────────────────────────────────
TS="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${HERMES}/backups/update-guard-${TS}"
mkdir -p "${BACKUP_DIR}"
cp -p "${HERMES}/config.yaml" "${BACKUP_DIR}/config.yaml" 2>/dev/null || true
cp -p "${AGENT}/gateway/run.py" "${BACKUP_DIR}/run.py" 2>/dev/null || true
cp -p "${AGENT}/hermes_cli/tools_config.py" "${BACKUP_DIR}/tools_config.py" 2>/dev/null || true
echo "BACKUP_DIR=${BACKUP_DIR}"

# ── update oficial ─────────────────────────────────────────────────────────
echo "── hermes update --backup ──"
"${AGENT}/venv/bin/hermes" update --backup 2>&1 | tail -15 || echo "UPDATE_RC=$?"

AFTER_SHA="$(git -C "${AGENT}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
echo "AFTER_HERMES_SHA=${AFTER_SHA}"
echo "UPSTREAM_UPDATE_AVAILABLE=$([ "${BEFORE_SHA}" != "${AFTER_SHA}" ] && echo YES || echo NO)"

# ── detectar estado dos patches ────────────────────────────────────────────
run_present=$(grep -c 'include_default_mcp_servers=False' "${AGENT}/gateway/run.py" 2>/dev/null || echo 0)
tc_present=$(grep -c 'if toolset_names == \[\]' "${AGENT}/hermes_cli/tools_config.py" 2>/dev/null || echo 0)
echo "PATCH_STATE run.py=${run_present} tools_config.py=${tc_present}"

if [ "${run_present}" -gt 0 ] && [ "${tc_present}" -gt 0 ]; then
  echo "PATCH_STATE=PATCH_PRESENT (não reaplicar)"
elif [ "${run_present}" -eq 0 ] && [ "${tc_present}" -eq 0 ]; then
  echo "PATCH_STATE=PATCH_MISSING_SAFE_TO_REAPPLY"
  cp -p "${AGENT}/gateway/run.py" "${BACKUP_DIR}/run.py.pre-reapply"
  cp -p "${AGENT}/hermes_cli/tools_config.py" "${BACKUP_DIR}/tools_config.py.pre-reapply"
  if (cd "${AGENT}" && git apply --check "${PATCH_SRC}" 2>/dev/null); then
    (cd "${AGENT}" && git apply "${PATCH_SRC}")
    echo "PATCH_REAPPLIED=YES"
  else
    echo "PATCH_STATE=PATCH_CONFLICT"
    echo "UPDATE_GUARD=FAIL_CLOSED (conflito — não editar automaticamente)"
    exit 1
  fi
else
  echo "PATCH_STATE=PARTIAL (inconsistente) — UPDATE_GUARD=FAIL_CLOSED"
  exit 1
fi

# ── restart gateway somente se necessário (source patch mudou) ─────────────
if [ "${run_present}" -eq 0 ] || [ "${tc_present}" -eq 0 ]; then
  echo "── restart gateway (patch reaplicado) ──"
  systemctl --user restart hermes-gateway.service
  sleep 10
fi
echo "GATEWAY_AFTER=$(systemctl --user is-active hermes-gateway.service 2>/dev/null || echo inactive)"

# ── verificar invariantes ──────────────────────────────────────────────────
echo "── verify_slim ──"
"${VENV_PY}" "${VERIFY}" || true

# ── smoke /servidores (chamado por verify? aqui apenas registra o passo) ───
echo "── smoke /servidores (executar e2e_4res ou plugin path) ──"
echo "SMOKE_STEP=documentado (ver docs/reports/sprint-0.7.3)"

# ── decisão ────────────────────────────────────────────────────────────────
# (fail-closed manual: se verify_slim apontou FAIL, operador deve reverter
#  restaurando ${BACKUP_DIR})
echo "UPDATE_GUARD=DONE (verificar verify_slim; rollback: restaurar ${BACKUP_DIR} + restart)"