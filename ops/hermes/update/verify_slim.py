#!/usr/bin/env python3
"""
verify_slim.py — Verificador das invariantes Slim/Minimal no Hermes operacional.

Sprint 0.7.3 Update Guard. Rode no host Hermes (runtime venv), APÓS um
`hermes update`, para confirmar que as invariantes Slim sobreviveram.

Checa (saída de 0 se tudo PASS; exit code 1 = fail-closed):
  SLIM_CONFIG_PRESENT            — platform_toolsets das plataformas do gateway vazio
  NORMAL_CHAT_TOOLS=0            — resolve_toolset por plataforma → 0 tools
  NORMAL_CHAT_TOOL_SCHEMA_BYTES=0
  PATCH_RUN_PY_PRESENT           — gateway/run.py com include_default_mcp_servers=False
  PATCH_TOOLS_CONFIG_PRESENT     — tools_config.py com early-return p/ toolset vazio
  CAPABILITY_FAIL_CLOSED         — extension MCPAdapter.authorize NÃO é authorized=True no-op

Sem escrita. Sem secrets. Uso:
  cd ~/.hermes/hermes-agent && venv/bin/python /path/verify_slim.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERMES = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes")))
AGENT = HERMES / "hermes-agent"
RESULT: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULT.append(f"{name}={'PASS' if ok else 'FAIL'} {detail}")
    print(f"{name}={'PASS' if ok else 'FAIL'} {detail}")


def patch_present(path: Path, needle: str) -> bool:
    return path.exists() and needle in path.read_text(encoding="utf-8", errors="replace")


def main() -> int:
    cfg = (HERMES / "config.yaml").read_text(encoding="utf-8") if (HERMES / "config.yaml").exists() else ""
    pt = cfg.split("platform_toolsets:", 1)
    has_empty = False
    if len(pt) == 2:
        block = pt[1].split("\n", 1)[0]  # primeira linha
        has_empty = "[]" in pt[1]
    check("SLIM_CONFIG_PRESENT", has_empty,
          "platform_toolsets configurado" if has_empty else "AUSENTE (config.yaml pode ter sido sobrescrito)")

    check("PATCH_RUN_PY_PRESENT",
          patch_present(AGENT / "gateway/run.py", "include_default_mcp_servers=False"),
          "gateway/run.py")
    check("PATCH_TOOLS_CONFIG_PRESENT",
          patch_present(AGENT / "hermes_cli/tools_config.py", "if toolset_names == []"),
          "hermes_cli/tools_config.py")

    # NORMAL_CHAT_TOOLS=0 (resolve toolset por plataforma do gateway)
    tools_ok = True
    schema_total = 0
    try:
        sys.path.insert(0, str(AGENT))
        import model_tools  # noqa: F401
        from hermes_cli.tools_config import _get_platform_tools
        from hermes_cli.config import load_config
        from toolsets import resolve_toolset
        from tools.registry import registry
        cfg_d = load_config() or {}
        for platform in ("whatsapp", "gateway", "api_server"):
            names = []
            for ts in _get_platform_tools(cfg_d, platform) or []:
                names.extend(resolve_toolset(ts))
            names = sorted(set(names))
            if names:
                tools_ok = False
                RESULT.append(f"PLATFORM_{platform}_TOOLS={len(names)} (deve ser 0)")
                print(f"PLATFORM_{platform}_TOOLS={len(names)} (deve ser 0)")
            for n in names:
                try:
                    s = registry.get_schema(n)
                    if s:
                        schema_total += len(json.dumps(s).encode("utf-8"))
                except Exception:
                    pass
    except Exception as exc:
        tools_ok = False
        print("MEASURE_ERROR=%s" % type(exc).__name__)
    check("NORMAL_CHAT_TOOLS", tools_ok, "0 tools nas plataformas do gateway")
    check("NORMAL_CHAT_TOOL_SCHEMA_BYTES", schema_total == 0, "bytes=%d" % schema_total)

    # CAPABILITY_FAIL_CLOSED (extension MCPAdapter.authorize não é no-op authorized=True)
    ext = AGENT / "plugins" / "capability-intelligence"
    cap_ok = False
    for cand in (ext / "__init__.py", Path("/home/will/.hermes/plugins/capability-intelligence/__init__.py")):
        if cand.exists() and "authorized=True" not in cand.read_text(encoding="utf-8", errors="replace"):
            cap_ok = True
    check("CAPABILITY_FAIL_CLOSED", cap_ok, "MCPAdapter.authorize não retorna authorized=True (no-op)")

    failed = any("=FAIL" in r or "=False" in r for r in RESULT)
    print("SLIM_VERIFY=" + ("PASS" if not failed else "FAIL_CLOSED"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())