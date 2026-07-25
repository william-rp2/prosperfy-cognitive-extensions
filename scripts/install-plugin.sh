#!/usr/bin/env bash
# install-plugin.sh — Instala/sincroniza plugin Hermes
# 
# Este script copia o plugin do repositório oficial para
# ~/.hermes/plugins/ (ambiente de runtime).
#
# Uso: bash scripts/install-plugin.sh [extensao]
#   extensao: nome da extensão (default: capability-intelligence)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HERMES_PLUGINS="${HOME}/.hermes/plugins"
EXTENSAO="${1:-capability-intelligence}"

echo "🔧 Instalando extensão: ${EXTENSAO}"

# 1. Verificar se o diretório da extensão existe
EXT_DIR="${REPO_DIR}/hermes/${EXTENSAO}"
if [ ! -d "${EXT_DIR}" ]; then
    echo "❌ Extensão não encontrada: ${EXT_DIR}"
    exit 1
fi

# 2. Instalar pacote Python (editable)
echo "  📦 Instalando pacote Python..."
pip install -e "${EXT_DIR}" 2>/dev/null || \
    pip3 install -e "${EXT_DIR}" 2>/dev/null || \
    echo "  ⚠️  pip não encontrado. Execute manualmente: pip install -e ${EXT_DIR}"

# 3. Copiar plugin para runtime
PLUGIN_SRC="${EXT_DIR}/plugin"
PLUGIN_DST="${HERMES_PLUGINS}/${EXTENSAO}"

if [ -d "${PLUGIN_SRC}" ]; then
    mkdir -p "${PLUGIN_DST}"
    cp -r "${PLUGIN_SRC}/"* "${PLUGIN_DST}/"
    echo "  ✅ Plugin copiado para ${PLUGIN_DST}"
else
    echo "  ⚠️  Plugin não encontrado em ${PLUGIN_SRC}"
fi

# 4. Verificar resultado
if [ -f "${PLUGIN_DST}/plugin.yaml" ]; then
    echo "✅ Instalação concluída. Execute '/reset' no Hermes para ativar."
else
    echo "❌ Falha na instalação do plugin."
    exit 1
fi