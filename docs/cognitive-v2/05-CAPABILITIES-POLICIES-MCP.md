# Capabilities, Policies e MCP

## Objetivo

Reduzir a tool surface do Hermes e reutilizar ProsperfySkill/MCPs
existentes.

## Regra de desenvolvimento

Antes de implementar: 1. procurar capability no ProsperfySkill; 2.
procurar MCP de mercado maduro; 3. procurar API/SDK oficial; 4. criar
adapter; 5. só criar integração própria quando necessário.

## Capability composta

Exemplo:

``` text
infra.inspect
  -> vps panorama
  -> containers
  -> services
  -> disk
  -> ports
```

A LLM não escolhe cada primitive. O workflow/capability faz isso
deterministicamente.

## Registry mínimo

Cada capability registra: - id/version; - domínio; - descrição curta; -
input/output schema; - adapter; - required scopes; - policy default; -
idempotency behavior; - timeout/retry; - cost class; - tenant support; -
audit/redaction rules.

## Bundles

Profiles recebem bundles curtos, por exemplo: - owner-core; - finance; -
customer-support; - infra-read; - proposal; - email-intelligence.

## ProsperfySkill

Manter como camada externa. Não duplicar VPS, e-mail, Supabase admin,
notifications, social e demais integrações já maduras.

## Tool discovery

Preferência: catálogo compacto primeiro; schema completo apenas da
capability escolhida. Tool administrativa não deve ser apresentada ao
Hermes comum.
