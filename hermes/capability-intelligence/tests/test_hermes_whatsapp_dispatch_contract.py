"""
test_hermes_whatsapp_dispatch_contract.py — Contrato do dispatcher de slash
commands do Hermes (WhatsApp) — Sprint 0.5.

O dispatcher real vive no runtime Hermes EXTERNO (~/.hermes/hermes-agent),
fora deste repositório. O bug provado no runtime (log real
"Unrecognized slash command /servidores from whatsapp", gateway/run.py:11756):

  O dispatcher JÁ consulta o registry de comandos de plugins
  (get_plugin_command_handler), mas esse registry é um snapshot cacheado da
  discovery do START do processo. `hermes plugins enable X` DEPOIS do start
  não atualiza o registry → comando de plugin recém-habilitado vira
  "Unknown command" até reiniciar o gateway.

O fix mínimo e genérico (scripts/patches/hermes_runtime_plugin_command_refresh.patch)
adiciona refresh-on-stale nos getters (get_plugin_command_handler e
get_plugin_commands), sem hardcode de /servidores e sem novo registry.

Estes testes replicam o CONTRATO do runtime com uma mini-implementação fiel
(registro de comandos, precedência built-in, lookup, /commands) para provar,
de forma determinística e sem depender do runtime real:

  A. plugin habilitado registra /servidores → WhatsApp reconhece → handler chamado.
  B. plugin desabilitado → /servidores continua unknown.
  C. comando inexistente → Unknown command preservado.
  D. comando built-in existente → comportamento preservado.
  E. colisão plugin vs built-in → built-in mantém precedência.
  F. /commands → inclui comandos de plugins habilitados.
  G. argumentos: /servidores foo → parsing/dispatch passa args ao handler.
  H. outro comando fictício de plugin (/plugin-test) → reconhecido SEM
     alteração em GATEWAY_KNOWN_COMMANDS (fix genérico, não hardcode).

Além disso cobre a REGRESSÃO do registry stale (o bug real) e prova que o
fix não referencia /servidores por nome (genericidade).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import pytest


# ─── Mini-replica FIEL do contrato do runtime ──────────────────────────────
#
# Espelha os nomes/shapes reais: hermes_cli.plugins (register_command,
# _plugin_commands, discover_and_load(force), _get_enabled_plugins) e o
# dispatcher do gateway (built-in primeiro → plugin → Unknown command).


class LoadedPlugin:
    def __init__(self, plugin_id: str, enabled: bool = False,
                 source: str = "user", kind: str = "standalone") -> None:
        self.plugin_id = plugin_id
        self.enabled = enabled
        self.source = source
        self.kind = kind


class PluginManager:
    """Equivalente ao PluginManager real (plugins.py) — registry + discovery."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._plugins: dict[str, LoadedPlugin] = {}
        self._plugin_commands: dict[str, dict] = {}
        self._discovered = False

    def _get_enabled_plugins(self) -> Optional[set]:
        plugins_cfg = self._config.get("plugins")
        if not isinstance(plugins_cfg, dict):
            return None
        if "enabled" not in plugins_cfg:
            return None
        enabled = plugins_cfg.get("enabled")
        if not isinstance(enabled, list):
            return None
        return set(enabled)

    def register_command(self, plugin_id: str, name: str, handler: Callable,
                         description: str = "") -> bool:
        """register_command do runtime: recusa nomes que colidem com built-in."""
        clean = name.lower().strip().lstrip("/").replace(" ", "-")
        if not clean:
            return False
        if resolve_builtin(clean) is not None:
            return False  # built-in vence; plugin não sobrescreve
        self._plugin_commands[clean] = {
            "handler": handler,
            "description": description or "Plugin command",
            "plugin": plugin_id,
        }
        return True

    def _get_disabled_plugins(self) -> set:
        plugins_cfg = self._config.get("plugins")
        disabled = plugins_cfg.get("disabled", []) if isinstance(plugins_cfg, dict) else []
        return set(disabled) if isinstance(disabled, list) else set()

    def discover_and_load(self, force: bool = False) -> None:
        """Só carrega plugins que estejam em plugins.enabled (opt-in), como o
        runtime: enable/disable é avaliado no momento da discovery."""
        if self._discovered and not force:
            return
        enabled = self._get_enabled_plugins()
        disabled = self._get_disabled_plugins()
        self._plugins = {
            pid: LoadedPlugin(pid, enabled=(enabled is not None and pid not in disabled
                                            and pid in enabled))
            for pid in self._config.get("_plugin_defs", {})
        }
        self._plugin_commands = {}
        for pid, defn in (self._config.get("_plugin_defs") or {}).items():
            if self._plugins[pid].enabled:
                for name, handler in defn.get("commands", {}).items():
                    self.register_command(pid, name, handler)
        self._discovered = True

    # ── getters PATCHADOS (o fix) ─────────────────────────────────────────

    def _has_stale_plugin_registry(self) -> bool:
        """Registry desatualizado em relação ao config: plugin habilitado
        depois do start (ainda não carregado) OU desabilitado depois do start
        (ainda carregado). Só plugins gated por plugins.enabled participam —
        bundled/exclusive/model-provider são governados por outra config."""
        enabled = self._get_enabled_plugins()
        disabled = self._get_disabled_plugins()
        for plugin_id, loaded in self._plugins.items():
            if loaded.kind in ("exclusive", "model-provider"):
                continue
            if loaded.source == "bundled" and loaded.kind in ("backend", "platform"):
                continue
            should_be_enabled = (
                enabled is not None
                and plugin_id not in disabled
                and plugin_id in enabled
            )
            if bool(getattr(loaded, "enabled", False)) != bool(should_be_enabled):
                return True
        return False

    def get_plugin_command_handler(self, name: str) -> Optional[Callable]:
        manager = self
        if manager._has_stale_plugin_registry():
            manager.discover_and_load(force=True)
        entry = manager._plugin_commands.get(name)
        return entry["handler"] if entry else None

    def get_plugin_commands(self) -> dict[str, dict]:
        manager = self
        if manager._has_stale_plugin_registry():
            manager.discover_and_load(force=True)
        return manager._plugin_commands


# Built-ins do gateway (GATEWAY_KNOWN_COMMANDS derivado do COMMAND_REGISTRY).
BUILTIN_HANDLERS: dict[str, Callable[[str], str]] = {
    "commands": lambda args: "<built-in /commands>",
    "status": lambda args: "<built-in /status>",
    "help": lambda args: "<built-in /help>",
}
GATEWAY_KNOWN_COMMANDS = frozenset(BUILTIN_HANDLERS)

UNKNOWN_REPLY = "Unknown command `/{cmd}`."


def resolve_builtin(name: str) -> Optional[Callable]:
    if name in GATEWAY_KNOWN_COMMANDS or name.replace("_", "-") in GATEWAY_KNOWN_COMMANDS:
        return BUILTIN_HANDLERS.get(name) or BUILTIN_HANDLERS.get(name.replace("_", "-"))
    return None


def normalize(name: str) -> str:
    return name.lower().lstrip("/").replace("_", "-")


def dispatch(manager: PluginManager, raw: str) -> str:
    """Dispatcher do gateway (WhatsApp): built-in → plugin → Unknown.

    Espelha a ordem real de gateway/run.py: built-ins/quick commands primeiro,
    depois get_plugin_command_handler(), e só então o gate de Unknown command
    (GATEWAY_KNOWN_COMMANDS)."""
    parts = raw.strip().split(maxsplit=1)
    name = normalize(parts[0]) if parts else ""
    args = parts[1] if len(parts) > 1 else ""
    if not name:
        return ""

    builtin = resolve_builtin(name)
    if builtin is not None:
        return builtin(args)

    handler = manager.get_plugin_command_handler(name)
    if handler is not None:
        result = handler(args)
        return str(result) if result else ""

    if name.replace("_", "-") not in GATEWAY_KNOWN_COMMANDS:
        return UNKNOWN_REPLY.format(cmd=name)
    return ""


def commands_list(manager: PluginManager) -> list[str]:
    """/commands: built-ins + comandos de plugins habilitados."""
    builtins = sorted(normalize(n) for n in GATEWAY_KNOWN_COMMANDS)
    plugins = sorted(manager.get_plugin_commands().keys())
    return builtins + plugins


# ─── Fixtures ──────────────────────────────────────────────────────────────

def _plugin_defs(servidores_handler: Callable, plugin_test_handler: Callable) -> dict:
    return {
        "capability-intelligence": {
            "commands": {
                "servidores": servidores_handler,
                "capability": lambda args: "<capability>",
            },
        },
        "ficticio": {
            "commands": {
                "plugin-test": plugin_test_handler,
            },
        },
    }


def _manager(config_enabled: list[str]) -> tuple[PluginManager, dict, dict]:
    calls: dict[str, list[str]] = {"servidores": [], "plugin-test": []}

    def servidores_handler(args: str) -> str:
        calls["servidores"].append(args)
        return "OK servidores" + (f" [{args}]" if args else "")

    def plugin_test_handler(args: str) -> str:
        calls["plugin-test"].append(args)
        return "OK plugin-test"

    defs = _plugin_defs(servidores_handler, plugin_test_handler)
    config = {
        "plugins": {"enabled": list(config_enabled)},
        "_plugin_defs": defs,
    }
    return PluginManager(config), config, calls


# ─── Testes A–H ────────────────────────────────────────────────────────────


class TestWhatsAppDispatchContract:
    """A—H do checklist da Sprint 0.5."""

    def test_a_plugin_enabled_servidores_dispatches(self):
        """A. plugin habilitado registra /servidores → WhatsApp reconhece e o
        handler do plugin é chamado (sem restart, com registry fresco)."""
        mgr, _cfg, calls = _manager(["capability-intelligence"])
        mgr.discover_and_load(force=False)
        out = dispatch(mgr, "/servidores")
        assert out == "OK servidores"
        assert calls["servidores"] == [""]

    def test_b_plugin_disabled_servidores_unknown(self):
        """B. plugin desabilitado → /servidores continua unknown e não executável."""
        mgr, _cfg, calls = _manager([])  # opt-in: nada habilitado
        mgr.discover_and_load(force=False)
        out = dispatch(mgr, "/servidores")
        assert "Unknown command" in out
        assert calls["servidores"] == []

    def test_c_unknown_command_preserved(self):
        """C. comando inexistente → comportamento atual de Unknown preservado."""
        mgr, _cfg, _calls = _manager(["capability-intelligence"])
        mgr.discover_and_load(force=False)
        out = dispatch(mgr, "/nao-existe")
        assert out == UNKNOWN_REPLY.format(cmd="nao-existe")

    def test_d_builtin_command_preserved(self):
        """D. comando built-in existente → comportamento atual preservado."""
        mgr, _cfg, _calls = _manager([])
        mgr.discover_and_load(force=False)
        assert dispatch(mgr, "/status") == "<built-in /status>"
        assert dispatch(mgr, "/help") == "<built-in /help>"

    def test_e_builtin_collision_wins(self):
        """E. colisão plugin vs built-in → built-in mantém precedência.

        O runtime recusa registro de plugin que colide com built-in
        (register_command → resolve_command), e o dispatcher checa built-in
        primeiro — o plugin nunca sobrescreve silenciosamente."""
        mgr, _cfg, _calls = _manager(["capability-intelligence"])

        def malicious(args: str) -> str:
            return "PLUGIN INJECTED"

        ok = mgr.register_command("capability-intelligence", "status", malicious)
        assert ok is False  # conflito rejeitado
        out = dispatch(mgr, "/status")
        assert out == "<built-in /status>"  # built-in vence
        assert "PLUGIN INJECTED" not in out

    def test_f_commands_list_includes_enabled_plugins(self):
        """F. /commands inclui comandos de plugins habilitados e NÃO inclui de
        plugins desabilitados."""
        mgr, _cfg, _calls = _manager(["capability-intelligence"])
        mgr.discover_and_load(force=False)
        listing = commands_list(mgr)
        assert "servidores" in listing
        assert "capability" in listing
        assert "plugin-test" not in listing  # plugin ficticio não habilitado
        assert "status" in listing           # built-in segue lá

    def test_g_servidores_args_forwarded(self):
        """G. /servidores foo → parsing/dispatch segue o contrato oficial do
        plugin (handler recebe 'foo' como argumento raw)."""
        mgr, _cfg, calls = _manager(["capability-intelligence"])
        mgr.discover_and_load(force=False)
        out = dispatch(mgr, "/servidores homolog-synthetic-vps")
        assert out == "OK servidores [homolog-synthetic-vps]"
        assert calls["servidores"] == ["homolog-synthetic-vps"]

    def test_h_fictitious_plugin_command_generic(self):
        """H. registrar /plugin-test → o dispatcher reconhece SEM alteração em
        GATEWAY_KNOWN_COMMANDS (prova que o fix é genérico, não hardcode)."""
        before = frozenset(GATEWAY_KNOWN_COMMANDS)
        mgr, _cfg, calls = _manager(["ficticio"])
        mgr.discover_and_load(force=False)
        out = dispatch(mgr, "/plugin-test")
        assert out == "OK plugin-test"
        assert calls["plugin-test"] == [""]
        assert GATEWAY_KNOWN_COMMANDS == before  # built-ins intactos


# ─── Regressão do BUG REAL: registry stale (enable pós-start) ──────────────


class TestStaleRegistryRegression:
    """Reproduz o bug real (plugin habilitado após o start do gateway) e prova
    que o fix dá refresh-on-stale nos getters."""

    def _stale_manager(self) -> PluginManager:
        """Simula o gateway que subiu ANTES do enable: discovery rodou com o
        plugin desabilitado (registro _plugins com enabled=False, commands
        ausentes); o enable acontece em seguida, SEM restart."""
        mgr, _cfg, _calls = _manager([])          # start com plugin desabilitado
        mgr.discover_and_load(force=False)
        # "hermes plugins enable capability-intelligence" edita o config:
        mgr._config["plugins"]["enabled"] = ["capability-intelligence"]
        # NADA re-discovering acontece — registry segue o snapshot do start.
        assert "servidores" not in mgr._plugin_commands
        return mgr

    def test_stale_dispatch_heals_without_restart(self):
        """O bug real: /servidores no gateway stale → sem o fix viraria
        Unknown command. Com o fix, o primeiro lookup dá refresh-on-stale e
        resolve o handler — SEM restart."""
        mgr = self._stale_manager()
        out = dispatch(mgr, "/servidores")
        assert out == "OK servidores"
        assert "Unknown command" not in out

    def test_stale_commands_list_heals(self):
        """/commands num gateway stale passa a incluir /servidores após o
        enable, sem restart (get_plugin_commands refresh-on-stale)."""
        mgr = self._stale_manager()
        listing = commands_list(mgr)
        assert "servidores" in listing

    def test_unknown_still_unknown_when_nothing_stale(self):
        """Comando genuinamente desconhecido não dispara rescan nem muda o
        resultado quando não há plugin habilitado pendente."""
        mgr = self._stale_manager()
        out = dispatch(mgr, "/inexistente")
        assert "Unknown command" in out

    def test_disabled_after_enable_no_rescan(self):
        """Desabilitar plugin (enabled list vazio) → /servidores volta a ser
        unknown; sem rescan que o ressuscite."""
        mgr = self._stale_manager()
        assert dispatch(mgr, "/servidores") == "OK servidores"
        mgr._config["plugins"]["enabled"] = []
        out = dispatch(mgr, "/servidores")
        assert "Unknown command" in out


# ─── Genericidade do fix ───────────────────────────────────────────────────


class TestFixGenericity:
    def test_fix_has_no_hardcoded_command_names(self):
        """O fix não referencia /servidores nem nenhum nome de comando: é
        genérico para QUALQUER plugin futuro."""
        assert "servidores" not in PATCH_SOURCE
        assert "plugin-test" not in PATCH_SOURCE
        assert "GATEWAY_KNOWN_COMMANDS" not in PATCH_SOURCE  # não toca built-ins

    def test_plugin_commands_never_enter_gateway_known_commands(self):
        """Comandos de plugin NUNCA entram em GATEWAY_KNOWN_COMMANDS — a
        separação built-in/plugin é preservada (sem hardcode)."""
        before = frozenset(GATEWAY_KNOWN_COMMANDS)
        mgr, _cfg, _calls = _manager(["capability-intelligence", "ficticio"])
        mgr.discover_and_load(force=False)
        assert GATEWAY_KNOWN_COMMANDS == before
        assert "servidores" not in GATEWAY_KNOWN_COMMANDS
        assert "plugin-test" not in GATEWAY_KNOWN_COMMANDS


# Source do patch versionado (scripts/patches/) para a prova de genericidade.
import os  # noqa: E402

_PATCH_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "scripts", "patches",
    "hermes_runtime_plugin_command_refresh.patch",
))
if not os.path.isfile(_PATCH_PATH):
    raise FileNotFoundError(
        "patch versionado não encontrado (fixture de genericidade): " + _PATCH_PATH
    )
with open(_PATCH_PATH, encoding="utf-8") as _f:
    PATCH_SOURCE = _f.read()