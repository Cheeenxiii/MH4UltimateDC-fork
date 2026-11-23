"""recompile.py --game: a reference game's defaults (synthetic config folders, no game data)."""
import argparse
import hashlib
import json
import os
import sys

import pytest

TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")
sys.path.insert(0, TOOLS)

import recompile as rc


def _args(**kw):
    base = {"game": "", "exheader": None, "code": None, "functions": None, "extra": None,
            "hooks": None, "tunables": None, "out": None}
    base.update(kw)
    return argparse.Namespace(**base)


def _games(tmp_path, extra_entries=True, functions=True):
    folder = tmp_path / "games" / "toy"
    folder.mkdir(parents=True)
    (folder / "game.json").write_text(json.dumps({"name": "Toy", "reference": True,
                                                  "code_sha1": hashlib.sha1(b"toy code").hexdigest()}))
    if functions:
        (folder / "functions.tsv").write_text("address\tmode\n0x00100000\tarm\n")
    if extra_entries:
        (folder / "extra_entries.txt").write_text("0x00100010\n")
    return str(tmp_path / "games"), folder


def test_without_game_defaults_are_mh4u():
    a = _args(extra=["more.txt"])
    assert rc.resolve_args(a, "/nonexistent") is None
    cfg = os.path.join(rc.ROOT, "config")
    assert a.functions == os.path.join(cfg, "functions.tsv")
    assert a.extra == [os.path.join(cfg, "extra_entries.txt"), "more.txt"]   # as argparse's append did
    assert a.hooks == os.path.join(cfg, "hooks.txt") and a.tunables == os.path.join(cfg, "tunables.txt")
    assert a.exheader.endswith(os.path.join("baserom", "update_v130", "exheader.bin"))
    assert a.out == os.path.join(rc.ROOT, "build", "recomp")


def test_without_game_explicit_values_win():
    a = _args(functions="f.tsv", hooks="", tunables="", out="o", exheader="e", code="c")
    rc.resolve_args(a, "/nonexistent")
    assert (a.functions, a.hooks, a.tunables, a.out, a.exheader, a.code) == ("f.tsv", "", "", "o", "e", "c")


def test_game_defaults(tmp_path):
    games, folder = _games(tmp_path)
    a = _args(game="toy", exheader="e", code="c", extra=["more.txt"])
    game = rc.resolve_args(a, games)
    assert game["name"] == "Toy"
    assert a.functions == str(folder / "functions.tsv")
    assert a.extra == [str(folder / "extra_entries.txt"), "more.txt"]
    assert a.hooks is None and a.tunables is None   # no port hooks in a reference recompile
    assert rc.load_hooks(a.hooks) == {} and rc.load_tunables(a.tunables) == {}
    assert a.out == os.path.join(rc.ROOT, "build", "recomp-toy")


def test_game_without_extra_entries(tmp_path):
    games, _ = _games(tmp_path, extra_entries=False)
    a = _args(game="toy", exheader="e", code="c")
    rc.resolve_args(a, games)
    assert a.extra == []


def test_game_needs_a_dump_and_a_table(tmp_path):
    games, _ = _games(tmp_path, functions=False)
    with pytest.raises(SystemExit, match="--exheader and --code"):
        rc.resolve_args(_args(game="toy"), games)
    with pytest.raises(SystemExit, match="no function table"):
        rc.resolve_args(_args(game="toy", exheader="e", code="c"), games)


def test_unknown_game(tmp_path):
    games, _ = _games(tmp_path)
    for name in ("nope", "../toy", "Toy"):
        with pytest.raises(SystemExit, match="known: toy"):
            rc.resolve_args(_args(game=name, exheader="e", code="c"), games)


def test_code_hash_is_checked():
    game = {"name": "Toy", "code_sha1": hashlib.sha1(b"toy code").hexdigest()}
    rc.check_game_code(game, b"toy code")
    with pytest.raises(SystemExit, match="isn't Toy's"):
        rc.check_game_code(game, b"other code")


def test_real_reference_games_resolve():
    """Every config/games/ folder with a function table resolves (addresses only, no dump needed)."""
    for name in sorted(os.listdir(rc.GAMES)):
        if os.path.exists(os.path.join(rc.GAMES, name, "functions.tsv")):
            a = _args(game=name, exheader="e", code="c")
            assert rc.resolve_args(a)["reference"] is True
