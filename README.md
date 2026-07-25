# Prosperfy Cognitive Extensions

Extensões cognitivas proprietárias desenvolvidas pela Prosperfy.

## Visão

Este repositório contém o código-fonte oficial de todas as extensões
cognitivas da Prosperfy. Atualmente, a implementação disponível é
para o **Hermes Agent**.

No futuro, componentes reutilizáveis (em `core/`) poderão ser
adaptados para outros motores cognitivos sem alterar a base conceitual.

## Estrutura

```
prosperfy-cognitive-extensions/
│
├── core/                  ← Componentes reutilizáveis entre extensões
│   ├── contracts/         ← Contratos compartilhados
│   ├── prompts/           ← Prompts reutilizáveis
│   ├── schemas/           ← Schemas de dados
│   └── utilities/         ← Utilitários comuns
│
├── hermes/                ← Extensões para o Hermes Agent
│   └── capability-intelligence/
│       ├── src/           ← Código-fonte (pip install -e src/)
│       ├── plugin/        ← Plugin Hermes (instalado em ~/.hermes/plugins/)
│       ├── tests/         ← Testes automatizados
│       ├── docs/          ← Documentação técnica
│       └── pyproject.toml
│
├── examples/              ← Exemplos de uso e integração
├── scripts/               ← Scripts de instalação/sincronização
├── docs/                  ← Documentação agregada do repositório
│   ├── Architecture/
│   ├── ADR/
│   ├── RFC/
│   ├── Developer/
│   └── Examples/
│
├── .gitignore
└── README.md
```

## Extensões Atuais

| Extensão | Motor | Versão | Status |
|---|---|---|---|
| Capability Intelligence | Hermes | 1.0.0 | ✅ Operacional |

## Fluxo de Desenvolvimento

1. **Editar** código na extensão correspondente
2. **Testar** com `pytest -v`
3. **Commit** no repositório oficial
4. **Push** para o GitHub
5. **Sincronizar** plugin com `scripts/install-plugin.sh`
6. **Validar** no Hermes (`/reset` → `/capability status`)

## Instalação

```bash
# 1. Clonar o repositório
git clone https://github.com/william-rp2/prosperfy-cognitive-extensions.git
cd prosperfy-cognitive-extensions

# 2. Instalar pacote Python
pip install -e hermes/capability-intelligence/

# 3. Instalar plugin no Hermes
bash scripts/install-plugin.sh
```

## Licença

Proprietária — Prosperfy. Todos os direitos reservados.