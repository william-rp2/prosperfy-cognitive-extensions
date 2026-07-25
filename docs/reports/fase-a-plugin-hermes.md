# Relatório de Validação — Fase A: Plugin Hermes

**Data:** 2026-07-24
**Responsável:** Hermes Agent
**Fase:** Plugin Hermes (H1-H8)

## Objetivo
Validar que o plugin Capability Intelligence está corretamente instalado,
habilitado e responsivo no Hermes Agent.

## Resultados

| Cenário | Total | Aprovados | Reprovados |
|---|---|---|---|
| Plugin carregado (H1) | 1 | 1 | 0 |
| /capability status (H2) | 1 | 1 | 0 |
| /capability gaps (H3) | 1 | 1 | 0 |
| /capability feedback (H4) | 1 | 1 | 0 |
| /capability run (H5) | 1 | 1 | 0 |
| /capability run com contexto (H6) | 1 | 1 | 0 |
| Domínio desconhecido (H7) | 1 | 1 | 0 |
| /capability help (H8) | 1 | 1 | 0 |
| **Total** | **8** | **8** | **0** |

## Bugs Encontrados

| ID | Severidade | Descrição | Status |
|---|---|---|---|
| BUG-001 | 🟡 Alto | `_handle_slash` usava `split()` para parsing, não suportava aspas em intenções com múltiplas palavras. Ex: `"deploy evolution api"` virava `"deploy`. | 🔧 Corrigido |
| BUG-002 | 🟢 Baixo | `shlex.split` removia aspas de argumentos JSON, impedindo `json.loads`. | 🔧 Corrigido |

## Correções Realizadas

1. **Plugin:** Substituído `raw.strip().split(maxsplit=2)` por `shlex.split()` com fallback
2. **Plugin:** Adicionado tratamento para JSON sem aspas (após shlex) — fallback com regex para restaurar aspas em chaves e valores
3. **Runtime:** Plugin sincronizado em ~/.hermes/plugins/

## Pendências

Nenhuma. Plugin funcional e responsivo.

## Riscos Conhecidos

- O plugin responde apenas em sessões Hermes interativas (não em `hermes chat -q`)
- O pipeline "run" ainda é simulado (MCPTransport não conectado ao Catalog real)

## Evidências

- Plugin listado como `enabled` em `hermes plugins list`
- `register()` function importável via `importlib`
- Todos os 8 slash commands responderam conforme esperado
- Parsing de argumentos com quotes: `"deploy evolution api"` → intent="deploy evolution api" ✅
- Parsing de JSON context: `{"target":"staging"}` → `{"target": "staging"}` ✅

## Decisão Final

✅ **Aprovada**

A Fase A está concluída. Plugin Capability Intelligence está operacional
no Hermes. Nenhum bug crítico ou regressão identificada.