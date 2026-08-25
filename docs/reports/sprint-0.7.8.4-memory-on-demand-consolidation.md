# Sprint 0.7.8.4 — Memory Snapshot On-Demand (rework)

> MEMORY-ONLY patch. No routing duplication. Cache signature fix. Fail-closed consolidation.

## Patch scope

```
ops/hermes/update/memory_on_demand.patch
  agent/agent_init.py       — skip_memory_snapshot_in_prompt (≠ skip_memory)
  agent/system_prompt.py    — gate MEMORY.md volatile block
  gateway/run.py            — slim kwargs + cache signature + prompt invalidation

NOT in patch:
  _resolve_enabled_toolsets_for_source
  prosperfy_slim_boundary
  _maybe_execute_memory_write
```

## Cache fix

```
CACHE_FIX_STRATEGY=A — skip_memory_snapshot_in_prompt in _agent_config_signature
                   + invalidate_system_prompt() when flag transitions False→True
```

## Deploy (host — NOT executed in repo)

```bash
bash ops/hermes/update/apply_memory_on_demand.sh ~/.hermes/hermes-clean
# single-bridge restart by operator
```

## Consolidation (host)

JSON spec with `expected_sha256` or `expected_text` per entry. Entry 6 forbidden.

```bash
python scripts/consolidate_memory_md.py --replacements spec.json
python scripts/consolidate_memory_md.py --apply --replacements spec.json
```

## Human Acceptance

Pending host pre-deploy reconciliation + deploy.
