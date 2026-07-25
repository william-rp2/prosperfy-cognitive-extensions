#!/usr/bin/env bash
# validate-install.sh — Valida a instalação de uma extensão
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HERMES_PLUGINS="${HOME}/.hermes/plugins"
EXTENSAO="${1:-capability-intelligence}"

echo "🔍 Validando instalação: ${EXTENSAO}"
PASS=0
FAIL=0

check() {
    local desc="$1"
    local test_cmd="$2"
    if eval "$test_cmd" 2>/dev/null; then
        echo "  ✅ ${desc}"
        PASS=$((PASS + 1))
    else
        echo "  ❌ ${desc}"
        FAIL=$((FAIL + 1))
    fi
}

# 1. Diretório do repositório
check "Diretório do repositório" "[ -d '${REPO_DIR}/hermes/${EXTENSAO}' ]"

# 2. Código-fonte
check "Código-fonte (src/)" "[ -d '${REPO_DIR}/hermes/${EXTENSAO}/src' ]"

# 3. Plugin
check "Plugin (plugin.yaml)" "[ -f '${REPO_DIR}/hermes/${EXTENSAO}/plugin/plugin.yaml' ]"

# 4. Plugin instalado no runtime
check "Plugin instalado (runtime)" "[ -f '${HERMES_PLUGINS}/${EXTENSAO}/plugin.yaml' ]"

# 5. Pyproject
check "pyproject.toml" "[ -f '${REPO_DIR}/hermes/${EXTENSAO}/pyproject.toml' ]"

# 6. Testes
check "Diretório de testes" "[ -d '${REPO_DIR}/hermes/${EXTENSAO}/tests' ]"

# 7. Pacote Python instalado
PYTHON_CHECK=$(which python3 2>/dev/null && python3 -c 'import capability_intelligence; print("ok")' 2>/dev/null || echo "fail")
HERMES_PYTHON="/home/will/.hermes/hermes-agent/venv/bin/python3"
HERMES_CHECK=$("${HERMES_PYTHON}" -c 'import capability_intelligence; print("ok")' 2>/dev/null || echo "fail")
if [ "$HERMES_CHECK" = "ok" ]; then
    check "Pacote Python instalado (Hermes venv)" "true"
else
    check "Pacote Python instalado" "false"
fi

echo ""
echo "📊 Resultado: ${PASS} passaram, ${FAIL} falharam"
[ "${FAIL}" -eq 0 ] || exit 1