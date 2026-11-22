"""tools/mod_hooks.py and mod.json's native plugin fields (docs/MODS.md, "Native plugins"):
hooks by name merged into the build's hook points, conflicts reported, plugins listed for the
port. Synthetic mods and made-up addresses only."""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import mod_hooks  # noqa: E402
import mods  # noqa: E402


@pytest.fixture(autouse=True)
def usa_game(monkeypatch):
    monkeypatch.setattr(mods, "PROGRAM_ID", 0x0004000000126300)
    monkeypatch.setattr(mods, "UPDATE_ID", 0x0004000E00126300)


NAMES = {"sMhPad::update": 0x00694C98, "uEnemy::move": 0x00200000, "sMhMain::frame": 0x00AF5250}
BASE = {0x00694C98: "sMhPad::update", 0x00AF5250: "sMhMain::frame"}


def mh(mod, *hooks, plugin=None, config=None, path="/mods/x"):
    return mod_hooks.ModHooks(mod, path, [h if isinstance(h, dict) else {"name": h} for h in hooks],
                              plugin or {}, config or {})


# ── merging ────────────────────────────────────────────────────────────────

def test_merge_adds_named_hooks():
    merged, lines = mod_hooks.merge(BASE, [mh("Mod A", "uEnemy::move")], NAMES)
    assert merged == {**BASE, 0x00200000: "uEnemy::move"}
    assert lines == ["Mod A: hooks uEnemy::move (0x00200000)"]


def test_merge_shared_hook_is_a_chain():
    merged, lines = mod_hooks.merge(BASE, [mh("Mod A", "sMhPad::update"), mh("Mod B", "uEnemy::move"),
                                           mh("Mod C", "uEnemy::move")], NAMES)
    assert len(merged) == 3
    assert "Mod A: hooks sMhPad::update, which config/hooks.txt hooks too (they run in a chain)" in lines
    assert "Mod C: hooks uEnemy::move, which Mod B hooks too (they run in a chain)" in lines


def test_merge_by_address():
    merged, _ = mod_hooks.merge(BASE, [mh("Mod A", {"name": "uFish::swim", "address": 0x00300000})], NAMES)
    assert merged[0x00300000] == "uFish::swim"


def test_merge_conflicts():
    with pytest.raises(mod_hooks.HookError, match="a name the project doesn't know"):
        mod_hooks.merge(BASE, [mh("Mod A", "uNobody::knows")], NAMES)
    with pytest.raises(mod_hooks.HookError, match="the project has it at 0x00200000"):
        mod_hooks.merge(BASE, [mh("Mod A", {"name": "uEnemy::move", "address": 0x00200004})], NAMES)
    with pytest.raises(mod_hooks.HookError, match="but Mod A put it at 0x00300000"):
        mod_hooks.merge(BASE, [mh("Mod A", {"name": "uFish::swim", "address": 0x00300000}),
                               mh("Mod B", {"name": "uFish::swim", "address": 0x00300004})], NAMES)
    with pytest.raises(mod_hooks.HookError, match="config/hooks.txt calls it sMhPad::update"):
        mod_hooks.merge(BASE, [mh("Mod A", {"name": "Pad", "address": 0x00694C98})], NAMES)


def test_merge_lists_every_conflict():
    with pytest.raises(mod_hooks.HookError) as e:
        mod_hooks.merge(BASE, [mh("Mod A", "nope1"), mh("Mod B", "nope2")], NAMES)
    assert "Mod A" in str(e.value) and "Mod B" in str(e.value)


def test_known_names(tmp_path):
    (tmp_path / "hooks.txt").write_text("# c\n0x00694c98 sMhPad::update   # why\n")
    (tmp_path / "symbols.txt").write_text("0x005bf888 crc32_string   # note\n0x00694c98 other\n")
    (tmp_path / "functions.tsv").write_text("# t\naddress\tsize\tmode\tcategory\tname\tstatus\n"
                                            "0x00100000\t0x2c\tarm\tunknown\tentry\ttodo\n"
                                            "0x00100100\t0x2c\tarm\tunknown\t\ttodo\n")
    names = mod_hooks.known_names(str(tmp_path))
    assert names == {"sMhPad::update": 0x00694C98, "crc32_string": 0x005BF888, "other": 0x00694C98,
                     "entry": 0x00100000}


def test_repository_names_include_hook_points():
    names = mod_hooks.known_names()
    assert names["sMhPad::update"] == 0x00694C98


# ── mod.json ───────────────────────────────────────────────────────────────

def manifest(data):
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(data, f)
    try:
        return mods.read_manifest(f.name)
    finally:
        os.unlink(f.name)


def test_manifest_plugin_fields():
    out, warnings = manifest({"name": "M", "hooks": ["sMhPad::update", {"name": "X", "address": "0x00300000"}],
                              "plugin": {"windows": "bin/m.dll", "linux": "bin/m.so"},
                              "config": {"speed": 2, "on": True, "label": "fast"}})
    assert warnings == []
    assert out["hooks"] == [{"name": "sMhPad::update"}, {"name": "X", "address": 0x00300000}]
    assert out["plugin"] == {"windows": "bin/m.dll", "linux": "bin/m.so"}
    assert out["config"] == {"speed": "2", "on": "1", "label": "fast"}


def test_manifest_bad_plugin_fields():
    out, warnings = manifest({"hooks": ["ok", 3, {"name": "Y", "address": "zz"}], "plugin": {"amiga": "x"},
                              "config": [1]})
    assert out["hooks"] == [{"name": "ok"}]
    assert len(warnings) == 3


# ── the library ────────────────────────────────────────────────────────────

def make_mod(lib, folder, manifest_data, files):
    root = lib / folder
    root.mkdir(parents=True)
    (root / "mod.json").write_text(json.dumps(manifest_data))
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return root


def library(tmp_path):
    user = tmp_path / "azahar"
    lib = user / mods.LIBRARY
    make_mod(lib, "a", {"name": "Mod A", "hooks": ["uEnemy::move"], "plugin": {"linux": "a.so", "windows": "a.dll"},
                        "config": {"value": "1"}}, {"a.so": b"so", "a.dll": b"dll"})
    make_mod(lib, "b", {"name": "Mod B"}, {"romfs/data/x.txt": b"x"})
    make_mod(lib, "c", {"name": "Mod C", "plugin": {"windows": "c.dll"}}, {"c.dll": b"dll"})
    make_mod(lib, "d", {"name": "Mod D", "hooks": ["sMhPad::update"], "plugin": {"linux": "missing.so"}}, {})
    (lib / "c" / "config.ini").write_text("[c]\nvalue = 9   ; the player's\n")
    lb = mods.Library(str(lib))
    found, _ = lb.mods()
    by_id = {m.id: m for m in found}
    for m in found:
        m.enabled = True
    by_id["b"].enabled = True
    lb.save([by_id[i] for i in ("a", "b", "c", "d")])
    return user


def test_plugin_only_mod_is_valid(tmp_path):
    user = library(tmp_path)
    found, _ = mods.Library(str(user / mods.LIBRARY)).mods()
    a = next(m for m in found if m.id == "a")
    assert a.errors == [] and a.layout == "plugin"


def test_enabled_mods(tmp_path):
    user = library(tmp_path)
    wanted = mod_hooks.enabled_mods(str(user))
    assert [m.mod for m in wanted] == ["Mod A", "Mod C", "Mod D"]   # Mod B has neither


def test_plugin_entries_and_list(tmp_path):
    user = library(tmp_path)
    wanted = mod_hooks.enabled_mods(str(user))
    entries, warnings = mod_hooks.plugin_entries(wanted, "linux")
    assert [(m.mod, os.path.basename(p)) for m, p in entries] == [("Mod A", "a.so")]
    assert any("Mod C: no native plugin for linux" in w for w in warnings)
    assert any("Mod D: its plugin missing.so isn't in the mod" in w for w in warnings)
    entries, _ = mod_hooks.plugin_entries(wanted, "windows")
    text = mod_hooks.plugin_list_text(entries)
    rows = [line.split("\t") for line in text.splitlines() if not line.startswith("#")]
    assert rows[0][:2] == ["plugin", "Mod A"] and rows[0][2].endswith("a.dll")
    assert ["config", "Mod A", "value", "1"] in rows
    assert ["config", "Mod C", "value", "9"] in rows                # config.ini over mod.json


def test_write_plugin_list(tmp_path):
    lib = tmp_path / "0004000000126300.so"
    m = mh("Mod A", path=str(tmp_path))
    path = mod_hooks.write_plugin_list(str(lib), [(m, "/x/a.so")])
    assert path == str(tmp_path / "0004000000126300.plugins.tsv")
    assert "plugin\tMod A\t/x/a.so\t" in open(path).read()
    assert mod_hooks.write_plugin_list(str(lib), []) is None
    assert not os.path.exists(path)                                 # a stale list goes


def test_build_game_merges_mod_hooks(tmp_path, monkeypatch):
    import build_game
    user = library(tmp_path)
    monkeypatch.setattr(mod_hooks, "known_names", lambda *a: NAMES)
    monkeypatch.setattr(mod_hooks, "platform_key", lambda *a: "linux")
    hooks, plugins = build_game.mod_plugins(str(user), 0x0004000000126300, dict(BASE))
    assert hooks[0x00200000] == "uEnemy::move" and len(hooks) == 3
    assert [m.mod for m, _ in plugins] == ["Mod A"]


def test_build_game_stops_on_conflict(tmp_path, monkeypatch):
    import build_game
    user = library(tmp_path)
    monkeypatch.setattr(mod_hooks, "known_names", lambda *a: {})
    with pytest.raises(SystemExit, match="hooks conflict"):
        build_game.mod_plugins(str(user), 0x0004000000126300, dict(BASE))
