"""The reference games' tables in config/games/ (no game data: hashes, addresses and names)."""
import csv
import json
import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
GAMES = os.path.join(ROOT, "config", "games")
NAMES = sorted(d for d in os.listdir(GAMES) if os.path.isdir(os.path.join(GAMES, d)))
# A game's folder holds the tables of the version we study; older versions' tables stay in
# subfolders of it with their own game.json (mhxx/v1.0/).
TABLES = NAMES + sorted(os.path.join(g, v) for g in NAMES for v in os.listdir(os.path.join(GAMES, g))
                        if os.path.isfile(os.path.join(GAMES, g, v, "game.json")))
HEX = re.compile(r"0x[0-9a-fA-F]+")


def _rows(path):
    with open(path) as f:
        return list(csv.DictReader((line for line in f if not line.startswith("#")), delimiter="\t"))


def test_there_are_games():
    assert {"mh3u", "mhxx"} <= set(NAMES)


@pytest.mark.parametrize("game", TABLES)
def test_game_json(game):
    with open(os.path.join(GAMES, game, "game.json")) as f:
        g = json.load(f)
    assert g["reference"] is True
    assert re.fullmatch(r"[0-9A-F]{16}", g["program_id"])
    assert re.fullmatch(r"[0-9a-f]{40}", g["code_sha1"]) and re.fullmatch(r"[0-9a-f]{40}", g["exheader_sci_sha1"])
    assert set(g["segments"]) == {"text", "ro", "data", "bss"}
    for addr, size in g["segments"].values():
        assert HEX.fullmatch(addr) and HEX.fullmatch(size)
    text = int(g["segments"]["text"][0], 16), int(g["segments"]["text"][1], 16)
    assert text[0] <= int(g["dti_ctor"], 16) < text[0] + text[1]


@pytest.mark.parametrize("game", TABLES)
def test_class_table(game):
    rows = _rows(os.path.join(GAMES, game, "mt_classes.tsv"))
    assert rows and list(rows[0]) == ["dti", "name", "parent", "parent_name", "size", "id", "source"]
    names = {r["name"] for r in rows}
    assert "MtObject" in names
    for r in rows:
        assert HEX.fullmatch(r["dti"])
        assert r["size"] == "" or HEX.fullmatch(r["size"])   # the static fallback may not find a size
        assert r["parent_name"] in names or r["parent"] in ("", "0x00000000") or r["name"] == "MtObject" \
            or r["parent_name"] == ""


def test_no_game_tables_in_versions_json():
    with open(os.path.join(ROOT, "config", "versions.json")) as f:
        v = json.load(f)
    ids = {e["program_id"] for e in v["versions"]}
    for game in TABLES:
        with open(os.path.join(GAMES, game, "game.json")) as f:
            assert json.load(f)["program_id"] not in ids


def test_mhxx_studies_v14():
    """MHXX's tables come from the v1.4 update's code; v1.0's class registry is kept apart."""
    with open(os.path.join(GAMES, "mhxx", "game.json")) as f:
        g = json.load(f)
    assert g["update_id"] == "0004000E00197100" and g["update_version"] == 4224   # v4.8.0
    assert "mhxx/v1.0" in TABLES
    with open(os.path.join(GAMES, "mhxx", "v1.0", "game.json")) as f:
        assert json.load(f)["code_sha1"] != g["code_sha1"]


@pytest.mark.parametrize("game", [t for t in TABLES if os.path.isfile(os.path.join(GAMES, t, "functions.tsv"))])
def test_function_table(game):
    with open(os.path.join(GAMES, game, "game.json")) as f:
        start, size = (int(v, 16) for v in json.load(f)["segments"]["text"])
    rows = _rows(os.path.join(GAMES, game, "functions.tsv"))
    assert rows and list(rows[0])[:5] == ["address", "size", "mode", "category", "name"]
    addrs = [int(r["address"], 16) for r in rows]
    assert addrs == sorted(set(addrs))
    assert start <= addrs[0] and addrs[-1] < start + size
    assert {r["mode"] for r in rows} <= {"arm", "thumb"}


def test_both_reference_games_have_function_tables():
    assert all(os.path.isfile(os.path.join(GAMES, g, "functions.tsv")) for g in ("mh3u", "mhxx"))
