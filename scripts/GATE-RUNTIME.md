# Sprint 0.2 Remote Gate — Python Runtime Requirements

## Minimum Python

- **Python 3.11+** (project `requires-python >=3.11`)
- VPS testado: Ubuntu 24.04 / Python 3.12

## Packages (gate + tests)

Instalar a partir de `core/cognitive/`:

```bash
pip install -e ".[dev]"
```

Dependências diretas do gate:

- `asyncpg>=0.29`
- `pytest>=8`
- `pytest-asyncio>=0.23`

## Ambiente isolado na VPS

### Opção A — venv (requer pacote de sistema no Ubuntu)

```bash
sudo apt install python3.12-venv
python3 -m venv .venv-gate
source .venv-gate/bin/activate
pip install -e "core/cognitive[dev]"
```

### Opção B — pip user / virtualenv sem ensurepip

Se `python3 -m venv` falhar por `ensurepip` ausente, instale `python3.12-venv` **uma vez** no host (decisão operacional da VPS).

### Opção C — container efêmero (CI)

Testcontainers permanece opcional; **não** é requisito do gate Homolog.

## Não acoplar ao Hermes

O gate deve rodar em checkout isolado (`prosperfy-cognitive-gate-0.2`) com env próprio.
Não reutilizar venv/site-packages do Hermes.

## Env mínimo para full-gate

| Variável | Obrigatório |
|----------|-------------|
| `COGNITIVE_DB_ADMIN_URL` | Sim |
| `COGNITIVE_APP_PASSWORD` | Sim |
| `COGNITIVE_WORKER_PASSWORD` | Sim |
| `COGNITIVE_DB_URL` | Não (gerado pós-bootstrap) |
| `COGNITIVE_DB_WORKER_URL` | Não (gerado pós-bootstrap) |

Bootstrap v2 usa `quote_literal($1)` — **não** `ALTER ROLE PASSWORD $1`.

## Comando

```bash
python scripts/sprint_0_2_remote_gate.py full-gate
```
