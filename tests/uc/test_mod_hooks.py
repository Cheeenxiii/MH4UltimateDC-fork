"""Hooks by name, merged into the build: a wrong address hooks the wrong game function."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
import mod_hooks  # noqa: E402
from mod_hooks import ModHooks  # noqa: E402

PROJECT_HOOKS = {0x00200000: "sMhPad::update"}          # config/hooks.txt, address -> name
KNOWN = {"sMhPad::update": 0x00200000, "uEnemy::move": 0x00300000}


def mod(name: str, *hooks: dict, **kw) -> ModHooks:
    return ModHooks(name, f"/mods/{name}", list(hooks), **kw)


def test_hook_names_resolve_to_the_projects_addresses_and_unknown_ones_take_the_mods():
    merged, _ = mod_hooks.merge(PROJECT_HOOKS, [mod("A", {"name": "uEnemy::move"},
                                                    {"name": "uNew::run", "address": 0x00400000})], KNOWN)
    assert merged == {0x00200000: "sMhPad::update", 0x00300000: "uEnemy::move", 0x00400000: "uNew::run"}


def test_two_mods_hooking_one_function_chain_instead_of_conflicting():
    merged, lines = mod_hooks.merge(PROJECT_HOOKS, [mod("A", {"name": "sMhPad::update"}),
                                                    mod("B", {"name": "sMhPad::update"})], KNOWN)
    assert merged == PROJECT_HOOKS
    assert sum("chain" in line for line in lines) == 2


def test_every_kind_of_conflict_is_reported_in_one_go():
    wanted = [
        mod("Moves", {"name": "uEnemy::move", "address": 0x00300004}),       # a known name elsewhere
        mod("Renames", {"name": "sOther", "address": 0x00200000}),          # a second name for an address
        mod("Unknown", {"name": "uNowhere"}),                               # no address for a new name
    ]
    with pytest.raises(mod_hooks.HookError) as conflict:
        mod_hooks.merge(PROJECT_HOOKS, wanted, KNOWN)
    lines = str(conflict.value).splitlines()
    assert len(lines) == 3
    assert [line.split(":")[0] for line in lines] == ["Moves", "Renames", "Unknown"]


def test_plugin_list_sits_next_to_the_library_with_the_players_settings(tmp_path):
    folder = tmp_path / "mod"
    folder.mkdir()
    (folder / "config.ini").write_text("speed = 3\n")
    library = tmp_path / "0004000000126300.so"
    entry = (mod("Fast", config={"speed": "2", "mode": "a"}), str(folder / "p.so"))
    entry[0].path = str(folder)
    listed = mod_hooks.write_plugin_list(str(library), [entry])
    assert listed == str(tmp_path / "0004000000126300.plugins.tsv")
    lines = open(listed).read().splitlines()
    assert f"plugin\tFast\t{folder / 'p.so'}\t{folder}" in lines
    assert "config\tFast\tspeed\t3" in lines and "config\tFast\tmode\ta" in lines


def test_a_build_without_plugins_removes_a_stale_plugin_list(tmp_path):
    library = tmp_path / "game.so"
    stale = tmp_path / "game.plugins.tsv"
    stale.write_text("plugin\tOld\t/x.so\t/x\n")
    assert mod_hooks.write_plugin_list(str(library), []) is None
    assert not stale.exists()
