# Decisão Arquitetural: Suporte a Múltiplos Motores Cognitivos

**Status:** Visão Futura (não implementar agora)
**Data:** 2026-07-24

## Contexto

Atualmente, todas as extensões cognitivas são implementadas
exclusivamente para o Hermes Agent. Caso outros motores cognitivos
sejam suportados no futuro, a estrutura do repositório deve permitir
essa evolução sem reorganização.

## Decisão (Não Implementar Agora)

Registrar como visão arquitetural:

```
prosperfy-cognitive-extensions/
│
├── core/                 ← Componentes reutilizáveis
├── hermes/               ← Extensões para Hermes Agent
├── openhands/            ← Futuro: extensões para OpenHands
├── openclaw/             ← Futuro: extensões para OpenClaw
├── chatgpt/              ← Futuro: extensões para ChatGPT
└── tests/                ← Testes cross-motor
```

## Regra

Esta estrutura **não deve ser criada agora**. Placeholders não serão
criados. Apenas registra-se a direção para que decisões atuais
(como `hermes/` como subdiretório, não raiz) preservem essa
possibilidade futura.

## Próxima Ação

Nenhuma. Aguardar validação prática do Hermes + Prosperfy Skills
antes de expandir para outros motores.