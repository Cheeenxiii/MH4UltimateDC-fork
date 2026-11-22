"""The reference games' tables in config/games/ (no game data: hashes, addresses and names)."""
import csv
import json
import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
GAMES = os.path.join(ROOT, "config", "games")
NAMES = sorted(d for d in os.listdir(GAMES) if os.path.isdir(os.path.join(GAMES, d)))
HEX = re.compile(r"0x[0-9a-fA-F]+")


def _rows(path):
    with open(path) as f:
        return list(csv.DictReader((line for line in f if not line.startswith("#")), delimiter="\t"))


def test_there_are_games():
    assert {"mh3u", "mhxx"} <= set(NAMES)


@pytest.mark.parametrize("game", NAMES)
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


@pytest.mark.parametrize("game", NAMES)
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
    for game in NAMES:
        with open(os.path.join(GAMES, game, "game.json")) as f:
            assert json.load(f)["program_id"] not in ids
