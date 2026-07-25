#!/usr/bin/env bash
# uninstall-plugin.sh — Remove plugin Hermes
set -euo pipefail

HERMES_PLUGINS="${HOME}/.hermes/plugins"
EXTENSAO="${1:-capability-intelligence}"

echo "🗑️  Removendo plugin: ${EXTENSAO}"

# Desabilitar via Hermes CLI
hermes plugins disable "${EXTENSAO}" 2>/dev/null || true

# Remover diretório
rm -rf "${HERMES_PLUGINS}/${EXTENSAO}"
echo "✅ Plugin removido de ${HERMES_PLUGINS}/${EXTENSAO}"

# Nota: o pacote Python permanece instalado
echo "ℹ️  O pacote Python permanece instalado."
echo "   Para remover: pip uninstall prosperfy-${EXTENSAO//-/_}"