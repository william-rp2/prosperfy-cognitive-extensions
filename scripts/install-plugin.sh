#!/usr/bin/env bash
# install-plugin.sh — Instala/sincroniza plugin Hermes
#
# Este script copia o plugin do repositório oficial para
# ~/.hermes/plugins/ (ambiente de runtime).
#
# Detecta automaticamente o Python/pip do venv do Hermes.
# Nunca depende do pip global do sistema.
#
# Uso: bash scripts/install-plugin.sh [extensao]
#   extensao: nome da extensão (default: capability-intelligence)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HERMES_PLUGINS="${HOME}/.hermes/plugins"
EXTENSAO="${1:-capability-intelligence}"

echo "🔧 Instalando extensão: ${EXTENSAO}"

# ─── Detectar Python/pip do Hermes ────────────────────────────────────
# Ordem de procura: venv do Hermes > ~/.local/bin > sistema
HERMES_VENV_PYTHON=""
for candidate in \
    "${HOME}/.hermes/hermes-agent/venv/bin/python3" \
    "${HOME}/.hermes/hermes-agent/venv/bin/python" \
    "${HOME}/.local/bin/python3" \
; do
    if [ -x "${candidate}" ]; then
        HERMES_VENV_PYTHON="${candidate}"
        break
    fi
done

if [ -z "${HERMES_VENV_PYTHON}" ]; then
    # Fallback: any python3 with hermess-agent accessible
    HERMES_VENV_PYTHON="$(command -v python3)" || {
        echo "❌ Python3 não encontrado. Instale o Hermes Agent primeiro."
        exit 1
    }
fi

HERMES_PIP="${HERMES_VENV_PYTHON/\/python3/\/pip}"
HERMES_PIP="${HERMES_PIP/\/python/\/pip}"

if [ ! -x "${HERMES_PIP}" ]; then
    # tenta python3 -m pip
    HERMES_PIP="${HERMES_VENV_PYTHON} -m pip"
fi

echo "  📍 Python: ${HERMES_VENV_PYTHON}"

# ─── Verificar extensão ────────────────────────────────────────────────
EXT_DIR="${REPO_DIR}/hermes/${EXTENSAO}"
if [ ! -d "${EXT_DIR}" ]; then
    echo "❌ Extensão não encontrada: ${EXT_DIR}"
    exit 1
fi

# ─── Instalar pacote Python (editable) ─────────────────────────────────
echo "  📦 Instalando pacote Python..."
if [ -x "${HERMES_PIP}" ]; then
    "${HERMES_PIP}" install -e "${EXT_DIR}" 2>&1 | tail -3
elif echo "${HERMES_PIP}" | grep -q 'python3 -m pip'; then
    ${HERMES_PIP} install -e "${EXT_DIR}" 2>&1 | tail -3
else
    echo "  ⚠️  pip não encontrado em ${HERMES_PIP}"
    echo "  Execute manualmente: pip install -e ${EXT_DIR}"
fi

# ─── Copiar plugin para runtime ───────────────────────────────────────
PLUGIN_SRC="${EXT_DIR}/plugin"
PLUGIN_DST="${HERMES_PLUGINS}/${EXTENSAO}"

if [ -d "${PLUGIN_SRC}" ]; then
    mkdir -p "${PLUGIN_DST}"
    cp -r "${PLUGIN_SRC}/"* "${PLUGIN_DST}/"
    echo "  ✅ Plugin copiado para ${PLUGIN_DST}"
else
    echo "  ⚠️  Plugin não encontrado em ${PLUGIN_SRC}"
fi

# ─── Validar ───────────────────────────────────────────────────────────
if [ -f "${PLUGIN_DST}/plugin.yaml" ]; then
    echo "✅ Instalação concluída. Execute '/reset' no Hermes para ativar."
else
    echo "❌ Falha na instalação do plugin."
    exit 1
fi