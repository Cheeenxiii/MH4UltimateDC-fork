# Reference games

Tables from other MT Framework Mobile games, used to study them next to MH4U (the MH Ultimate Collection's "reference recompiles"). They are not port targets: nothing here changes how MH4U builds, and `config/versions.json` stays MH4U's alone.

Each folder holds:

- `game.json`: which dump the tables come from (program id, exheader and decompressed code hashes, segments, the DTI constructor `mt_dti.py` found). Hashes and addresses only, like `versions.json`.
- `mt_classes.tsv`: the class registry, made with `tools/mt_dti.py` exactly as `config/mt_classes.tsv` is.

| Folder | Dump | Classes |
|---|---|---|
| `mh3u/` | MH3U USA cartridge | 1,218 |
| `mhxx/` | MHXX JPN cartridge, v1.0 | 3,110 |

To regenerate one, from your own dump:

```
python3 tools/extract_ncch.py <dump> -o <work>
python3 tools/verify_dump.py <work>/exheader.bin <work>/code.bin    # compare with game.json
python3 tools/mt_dti.py --exheader <work>/exheader.bin --code <work>/code.bin -o config/games/<game>/mt_classes.tsv
```

MHXX's v1.4 update is left out: the only copy checked was repackaged by a fan translation, so its code couldn't be shown to be Nintendo's.
