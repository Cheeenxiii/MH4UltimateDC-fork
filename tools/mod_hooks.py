#!/usr/bin/env python3
"""The enabled mods' hooks and native plugins, for a build of the code library.

A mod's mod.json may list game functions it hooks (`hooks`) and ship a native library
(`plugin`, per platform) with default settings (`config`): docs/MODS.md, "Native plugins".
build_game.py merges the hooks into the build's hook points (config/hooks.txt), so that the
code library has a hook point for each, and lists the plugins next to the library
(<program id>.plugins.tsv), which the port reads when it loads the library
(port/src/plugin_host.h).

Hooks name functions; the name is looked up in config/hooks.txt, config/symbols.txt and the
names in config/functions.tsv (USA v1.3.0 addresses; another version's come from its shifts,
as for hooks.txt). A function the project hasn't named is given with its USA v1.3.0 address:
{"name": "MyName", "address": "0x00123456"}. A name that two mods (or a mod and the project)
put at different addresses, or two names for one address, is a conflict, and the build stops.
Two mods hooking the same function is fine: their hooks run in a chain.

    python3 tools/mod_hooks.py [--user-dir DIR]   # what the enabled mods hook, and any conflict
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import mods  # noqa: E402

PLUGIN_LIST_SUFFIX = ".plugins.tsv"


class HookError(Exception):
    pass


@dataclass
class ModHooks:
    mod: str                       # its name
    path: str                      # its folder
    hooks: list[dict] = field(default_factory=list)
    plugin: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)


def platform_key(platform: str | None = None) -> str:
    """mod.json's key for this platform's plugin: windows, linux, macos (android: --android)."""
    platform = platform or sys.platform
    if platform.startswith("win"):
        return "windows"
    if platform == "darwin":
        return "macos"
    return "linux"


def known_names(config_dir: str = os.path.join(ROOT, "config")) -> dict[str, int]:
    """Function names the project knows, at USA v1.3.0 addresses."""
    names: dict[str, int] = {}

    def add(name: str, addr: int) -> None:
        names.setdefault(name, addr)

    for fname in ("hooks.txt", "symbols.txt"):
        path = os.path.join(config_dir, fname)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                parts = line.split("#", 1)[0].split()
                if len(parts) >= 2:
                    add(parts[1], int(parts[0], 16))
    path = os.path.join(config_dir, "functions.tsv")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            header = None
            for line in f:
                if line.startswith("#"):
                    continue
                cells = line.rstrip("\n").split("\t")
                if header is None:
                    header = cells
                    continue
                row = dict(zip(header, cells))
                if row.get("name") and row.get("address"):
                    add(row["name"], int(row["address"], 16))
    return names


def enabled_mods(user_dir: str, library: str | None = None) -> list[ModHooks]:
    """The enabled mods of the library, in mod order, with their hooks and plugins (only those
    that have either). Mods made for the other region's game are left out, as deploy leaves them."""
    lib = mods.Library(library or os.path.join(user_dir, mods.LIBRARY))
    found, _ = lib.mods()
    out = []
    for m in found:
        if not m.enabled or m.errors or m.other_region:
            continue
        man = m.manifest
        if man.get("hooks") or man.get("plugin"):
            out.append(ModHooks(m.name, m.path, list(man.get("hooks", [])), dict(man.get("plugin", {})),
                                dict(man.get("config", {}))))
    return out


def merge(base: dict[int, str], wanted: list[ModHooks], names: dict[str, int]) -> tuple[dict[int, str], list[str]]:
    """The build's hook points: `base` (config/hooks.txt, address -> name) and the mods' hooks.
    Returns them and lines for the build log; raises HookError listing every conflict."""
    merged = dict(base)
    by_name = {n: a for a, n in base.items()}
    project = {**by_name, **names}      # what the project's own tables say
    owner = {a: "config/hooks.txt" for a in base}
    lines, errors = [], []
    for m in wanted:
        for h in m.hooks:
            name = h["name"]
            known = project.get(name)
            addr = h.get("address", known)
            if addr is None:
                errors.append(f"{m.mod}: hooks {name}, a name the project doesn't know: give its USA v1.3.0 "
                              f"address in mod.json ({{\"name\": \"{name}\", \"address\": \"0x...\"}})")
                continue
            if known is not None and addr != known:
                errors.append(f"{m.mod}: puts {name} at 0x{addr:08x}, but the project has it at 0x{known:08x}")
                continue
            if name in by_name and by_name[name] != addr:
                errors.append(f"{m.mod}: puts {name} at 0x{addr:08x}, but {owner[by_name[name]]} put it at "
                              f"0x{by_name[name]:08x}")
                continue
            if addr in merged and merged[addr] != name:
                errors.append(f"{m.mod}: calls the function at 0x{addr:08x} {name}, but {owner[addr]} calls it "
                              f"{merged[addr]}")
                continue
            if addr in merged:
                lines.append(f"{m.mod}: hooks {name}, which {owner[addr]} hooks too (they run in a chain)")
                continue
            merged[addr] = name
            by_name[name] = addr
            owner[addr] = m.mod
            lines.append(f"{m.mod}: hooks {name} (0x{addr:08x})")
    if errors:
        raise HookError("\n".join(errors))
    return merged, lines


def plugin_entries(wanted: list[ModHooks], platform: str) -> tuple[list[tuple[ModHooks, str]], list[str]]:
    """The plugins to load on `platform`, in mod order, as (mod, the library's full path), and
    warnings for mods without one for this platform or whose library is missing."""
    out, warnings = [], []
    for m in wanted:
        if not m.plugin:
            continue
        rel = m.plugin.get(platform)
        if not rel:
            warnings.append(f"{m.mod}: no native plugin for {platform} (it has {', '.join(sorted(m.plugin))}); "
                            "its hooks do nothing here")
            continue
        try:
            parts = mods.relative_parts(rel, f"{m.mod}: plugin")
        except mods.Error as e:
            warnings.append(e.message)
            continue
        path = os.path.join(m.path, *parts)
        if not os.path.isfile(path):
            warnings.append(f"{m.mod}: its plugin {rel} isn't in the mod")
            continue
        out.append((m, os.path.abspath(path)))
    return out, warnings


def _clean(text: str) -> str:
    return text.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def plugin_list_text(entries: list[tuple[ModHooks, str]]) -> str:
    """The plugin list the port reads (port/src/plugin_host.h ParsePluginList)."""
    lines = ["# native plugins of the enabled mods, in mod order (tools/mod_hooks.py)"]
    for m, path in entries:
        lines.append(f"plugin\t{_clean(m.mod)}\t{_clean(path)}\t{_clean(os.path.abspath(m.path))}")
        settings = dict(m.config)
        settings.update(read_user_config(m.path))
        for key, value in settings.items():
            lines.append(f"config\t{_clean(m.mod)}\t{_clean(key)}\t{_clean(value)}")
    return "\n".join(lines) + "\n"


def read_user_config(mod_path: str) -> dict[str, str]:
    """The player's settings for a mod's plugin: config.ini in its folder, `key = value` lines."""
    path = os.path.join(mod_path, "config.ini")
    out: dict[str, str] = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.split("#", 1)[0].split(";", 1)[0].strip()
                if "=" in line and not line.startswith("["):
                    key, _, value = line.partition("=")
                    out[key.strip()] = value.strip()
    return out


def plugin_list_path(library_path: str) -> str:
    """Next to the code library: <program id>.plugins.tsv (port/src/plugins.cpp ListPath)."""
    stem, _ = os.path.splitext(library_path)
    return stem + PLUGIN_LIST_SUFFIX


def write_plugin_list(library_path: str, entries: list[tuple[ModHooks, str]]) -> str | None:
    """Writes the plugin list next to the library, or removes a stale one when there's none."""
    path = plugin_list_path(library_path)
    if not entries:
        if os.path.exists(path):
            os.remove(path)
        return None
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(plugin_list_text(entries))
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--user-dir", default=mods.default_user_dir(), help="Azahar's user folder")
    ap.add_argument("--library", help="the mod library (default: <user dir>/mh4u-mods)")
    ap.add_argument("--hooks", default=os.path.join(ROOT, "config", "hooks.txt"))
    args = ap.parse_args(argv)
    import recompile
    wanted = enabled_mods(args.user_dir, args.library)
    if not wanted:
        print("no enabled mod hooks a function or has a native plugin")
        return 0
    try:
        merged, lines = merge(recompile.load_hooks(args.hooks), wanted, known_names())
    except HookError as e:
        print(e, file=sys.stderr)
        return 1
    for line in lines:
        print(line)
    entries, warnings = plugin_entries(wanted, platform_key())
    for w in warnings:
        print(f"warning: {w}")
    print(f"{len(merged)} hook points, {len(entries)} native plugins")
    return 0


if __name__ == "__main__":
    sys.exit(main())
