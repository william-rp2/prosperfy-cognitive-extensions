#!/usr/bin/env bash
# apply-hermes-runtime-plugin-refresh.sh — Aplica o patch mínimo e genérico
# que faz o dispatcher de slash commands do runtime Hermes enxergar comandos
# de plugins habilitados DEPOIS do start do processo gateway (registry stale).
#
# Root cause (provado no runtime real, Sprint 0.5):
#   gateway/run.py JÁ consulta o registry de plugins via
#   get_plugin_command_handler() — mas esse registry é um snapshot cacheado
#   da discovery do STARTUP. `hermes plugins enable X` depois do start não
#   aparece até reiniciar o gateway. O patch adiciona refresh-on-stale nos
#   getters (get_plugin_command_handler + get_plugin_commands), então
#   comandos de plugins habilitados/atualizados pós-start resolvem sem
#   restart. Genérico: nenhum nome de comando é hardcoded.
#
# Uso (host do Hermes real):
#   bash scripts/apply-hermes-runtime-plugin-refresh.sh [/caminho/do/hermes-agent]
#
# Idempotente: se o patch já estiver aplicado, não faz nada e sai 0.
# Nunca altera config, nunca reinicia o gateway, nunca expõe secret.
# O cutover (restart do gateway) é passo separado do operador.

set -euo pipefail

HERMES_AGENT_DIR="${1:-${HOME}/.hermes/hermes-agent}"
PLUGINS_PY="${HERMES_AGENT_DIR}/hermes_cli/plugins.py"
PATCH_SRC="$(cd "$(dirname "$0")" && pwd)/patches/hermes_runtime_plugin_command_refresh.patch"
MARKER="_has_unloaded_enabled_plugins"

if [ ! -f "${PLUGINS_PY}" ]; then
    echo "❌ plugins.py não encontrado em ${PLUGINS_PY}"
    exit 1
fi
if [ ! -f "${PATCH_SRC}" ]; then
    echo "❌ patch não encontrado: ${PATCH_SRC}"
    exit 1
fi

if grep -q "${MARKER}" "${PLUGINS_PY}"; then
    echo "✅ Patch já aplicado (${MARKER} presente) — nada a fazer."
    exit 0
fi

BACKUP="${PLUGINS_PY}.bak-sprint05-refresh"
cp -p "${PLUGINS_PY}" "${BACKUP}"
echo "🔧 Backup criado: ${BACKUP}"

if command -v patch >/dev/null 2>&1; then
    if patch -p0 --forward < "${PATCH_SRC}"; then
        echo "✅ Patch aplicado via patch(1)."
    else
        echo "⚠️ patch(1) não aplicou limpo — restaurando backup."
        cp -p "${BACKUP}" "${PLUGINS_PY}"
        exit 1
    fi
else
    echo "⚠️ patch(1) indisponível — aplique manualmente (ver docs/reports/sprint-0.5-whatsapp-dispatch-env-fix.md)."
    exit 1
fi

# Validação: sintaxe + heal funcional mínimo
"${HERMES_AGENT_DIR}/venv/bin/python" -m py_compile "${PLUGINS_PY}" 2>/dev/null \
    && echo "✅ py_compile OK." \
    || echo "⚠️ py_compile falhou — inspecione ${PLUGINS_PY} antes do restart."

echo ""
echo "Próximo passo (cutover, operador): reiniciar o gateway Hermes."
echo "Nenhuma mudança de config foi feita por este script."