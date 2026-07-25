# Developer Guide

## Setup

```bash
git clone https://github.com/william-rp2/prosperfy-cognitive-extensions.git
cd prosperfy-cognitive-extensions

# Install an extension
pip install -e hermes/capability-intelligence/

# Install plugin
bash scripts/install-plugin.sh
```

## Testing

```bash
cd hermes/capability-intelligence
pytest -v
```

## Adding a New Extension

1. Create `hermes/<extension-name>/`
2. Structure: `src/`, `plugin/`, `tests/`, `pyproject.toml`
3. Implement the contract
4. Write tests
5. Create plugin
6. Update `scripts/install-plugin.sh` if needed
7. Submit PR