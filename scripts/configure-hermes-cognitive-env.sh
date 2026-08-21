#!/usr/bin/env bash
# configure-hermes-cognitive-env.sh — Configura o env canônico do Hermes real
# (~/.hermes/.env) para o caminho Hermes → Cognitive (COGNITIVE_GATEWAY_*).
#
# Sprint 0.5 — problema B (runtime web/whatsapp): o plugin /servidores falhava
# com "COGNITIVE_GATEWAY_URL não configurada". O runtime Hermes carrega
# ~/.hermes/.env no processo (hermes_cli/env_loader.py) e os processos web e
# WhatsApp do gateway compartilham esse env — fonte ÚNICA, sem duplicar por
# canal.
#
# Segurança:
#   - Nunca imprime valores; valida apenas PRESENÇA.
#   - Nenhuma URL/secret hardcoded no repositório: os valores vêm do ambiente
#     do operador (os mesmos usados no Gate 0.5) ou de um arquivo fornecido.
#   - Idempotente; nunca sobrescreve valor já presente no .env.
#
# Uso (no host do Hermes real, antes de reiniciar o gateway):
#   export COGNITIVE_GATEWAY_URL=https://api-cognitive-homolog.prosperfy.com.br
#   export COGNITIVE_GATEWAY_CREDENTIAL=<service identity do slice>
#   export COGNITIVE_TENANT_ID=<uuid do tenant do slice>
#   export COGNITIVE_ACTOR_ID=sprint05-actor
#   bash scripts/configure-hermes-cognitive-env.sh
#
# Após: reinicie o gateway (passo de cutover do operador) e valide:
#   bash scripts/configure-hermes-cognitive-env.sh --check
#
# --check valida presença (sem imprimir valores) e só então o gateway deve
# ser reiniciado/retestado.

set -euo pipefail

HERMES_HOME="${HERMES_HOME:-${HOME}/.hermes}"
ENV_FILE="${HERMES_HOME}/.env"
REQUIRED_KEYS="COGNITIVE_GATEWAY_URL COGNITIVE_GATEWAY_CREDENTIAL COGNITIVE_TENANT_ID COGNITIVE_ACTOR_ID"
ALLOWLIST_HOSTS="api-cognitive-homolog.prosperfy.com.br"

check_mode=0
[ "${1:-}" = "--check" ] && check_mode=1

if [ "${check_mode}" = "1" ]; then
    echo "── Presença (sem valores) em ${ENV_FILE} ──"
    for key in ${REQUIRED_KEYS}; do
        if grep -qE "^${key}=.+" "${ENV_FILE}" 2>/dev/null; then
            echo "${key}=PRESENT"
        else
            echo "${key}=MISSING"
        fi
    done
    exit 0
fi

if [ ! -f "${ENV_FILE}" ]; then
    echo "❌ ${ENV_FILE} não existe — crie-o (ou use o mecanismo oficial do Hermes)."
    exit 1
fi
# .env deve ter permissões restritas (contém secrets).
if [ -n "$(find "${ENV_FILE}" -perm /077 2>/dev/null)" ]; then
    echo "⚠️  ${ENV_FILE} está com permissões abertas — recomenda-se 0600."
fi

missing=""
for key in ${REQUIRED_KEYS}; do
    value="$(printenv "${key}" || true)"
    if [ -z "${value}" ]; then
        missing="${missing} ${key}"
        continue
    fi
    if grep -qE "^${key}=" "${ENV_FILE}"; then
        echo "• ${key} já configurado no .env — preservando (não sobrescrevo)."
        continue
    fi
    printf '%s=%s\n' "${key}" "${value}" >> "${ENV_FILE}"
    echo "• ${key} adicionado ao .env (valor nunca impresso)."
done

if [ -n "${missing}" ]; then
    echo "❌ Valores ausentes no ambiente do operador:${missing}"
    echo "   Exporte-os (mesmos do Gate 0.5) e rode novamente. Nenhum valor foi inventado."
    exit 1
fi

# Validação final de presença (sem expor valores).
echo "── Resultado ──"
bash "$0" --check

echo ""
echo "Próximo passo (cutover, operador): reiniciar o gateway Hermes para o"
echo "processo carregar o novo env, depois retestar /servidores (web e WhatsApp)."