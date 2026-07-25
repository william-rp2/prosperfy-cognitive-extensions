# ADR-001: Fonte Oficial das Extensões Cognitivas

**Status:** Aprovado
**Data:** 2026-07-24
**Contexto:** Prosperfy Cognitive Extensions

## Decisão

O repositório `prosperfy-cognitive-extensions` será a **única fonte
oficial** do código das extensões cognitivas da Prosperfy.

O diretório `~/.hermes/plugins/` é **exclusivamente** um ambiente de
instalação/runtime. Nunca será a fonte oficial do código.

Toda evolução deverá ocorrer no repositório oficial, seguindo o fluxo:

1. Editar código no repositório
2. Executar testes
3. Realizar commit
4. Publicar no GitHub
5. Sincronizar a instalação do plugin
6. Validar no Hermes

## Consequências

- **Positivas:** Código versionado, backup centralizado, rastreabilidade,
  possibilidade de múltiplas instalações
- **Negativas:** Passo adicional de sincronização após alterações

## Notas

- `~/.hermes/plugins/` pode ser editado apenas para diagnóstico temporário
- A instalação deve ser reproduzível por script
- Documentação conceitual permanece no Vault Obsidian
- Supabase continua sendo utilizado para dados estruturados e memória operacional