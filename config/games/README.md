# Reference games

Tables from other MT Framework Mobile games, used to study them next to MH4U (the MH Ultimate Collection's "reference recompiles"). They are not port targets: nothing here changes how MH4U builds, and `config/versions.json` stays MH4U's alone.

Each folder holds:

- `game.json`: which dump the tables come from (program id, exheader and decompressed code hashes, segments, the DTI constructor `mt_dti.py` found). Hashes and addresses only, like `versions.json`.
- `mt_classes.tsv`: the class registry, made with `tools/mt_dti.py` exactly as `config/mt_classes.tsv` is.
- `functions.tsv`: the function table, made as `config/functions.tsv` is: Ghidra export, `find_missing_functions.py`, a second Ghidra pass, then `build_function_table.py`.

A game's folder holds the version we study. Tables of another version of the same game go in a subfolder with their own `game.json` (`mhxx/v1.0/`).

| Folder | Dump | Classes | Functions |
|---|---|---|---|
| `mh3u/` | MH3U USA cartridge | 1,218 | 24,869 |
| `mhxx/` | MHXX JPN v1.4 (update v4.8.0) | 3,110 | 38,931 |
| `mhxx/v1.0/` | MHXX JPN cartridge, v1.0 | 3,110 | none |

To regenerate one, from your own dump:

```
python3 tools/extract_ncch.py <dump> -o <work>
python3 tools/verify_dump.py <work>/exheader.bin <work>/code.bin    # compare with game.json
python3 tools/mt_dti.py --exheader <work>/exheader.bin --code <work>/code.bin -o config/games/<game>/mt_classes.tsv
```

The function table (Ghidra 12.1.4 headless; exports go outside the repository):

```
python3 tools/codebin2elf.py --exheader <work>/exheader.bin --code <work>/code.bin -o <work>/game.elf
analyzeHeadless <proj> <game> -import <work>/game.elf -processor ARM:LE:32:v6 \
    -scriptPath tools/ghidra -postScript ExportForAgents.java <work>/export1 none
python3 tools/find_missing_functions.py --exheader ... --code ... --functions <work>/export1/functions.tsv -o <work>/missing.txt
analyzeHeadless <proj> <game> -process game.elf -scriptPath tools/ghidra \
    -preScript CreateFunctionsFromList.java <work>/missing.txt -postScript ExportForAgents.java <work>/export2 none
python3 tools/build_function_table.py --exheader ... --code ... --functions <work>/export2/functions.tsv \
    --dti-ctor <game.json's constructor> --symbols "" --text-only -o config/games/<game>/functions.tsv
```

`--symbols ""` matters: the default, `config/symbols.txt`, names MH4U's addresses, and the first MH3U table carried two of them onto unrelated functions. `--text-only` drops what Ghidra made a function outside `.text` (such as one-byte entries in `.rodata`).

Ghidra's heap can be capped with `GHIDRA_HEADLESS_MAXMEM=3G`; MHXX's passes ran within it (12 and 4 minutes).

MH3U: the first pass found 20,281 functions, `find_missing_functions.py` 4,510 candidates, the second pass 24,869 (800 DTI initialisers, 493 SDK); 347 candidates are left for a third pass.

MHXX v1.4: the first pass found 31,372 functions, `find_missing_functions.py` 7,413 candidates (7,412 created, 1 failed), the second pass 38,932, of which the table keeps the 38,931 in `.text` (1,462 DTI initialisers, 377 SDK); 256 candidates are left for a third pass. 1,833 functions are Thumb (MH4U has 257, MH3U 1): real code, most open with a Thumb `push` and ARM code reaches them with 4,333 `blx` calls.

MHXX's v1.4 update (v4.8.0, title 0004000E00197100, version 4224): a clean dump of the official update, decrypted and checked against its own NCCH hashes, has the same exheader and `code.bin` as the copy a fan translation repackaged (the translation changes only RomFS files). The update replaces the code, so `mhxx/` holds v1.4's tables. Its class registry against v1.0's: the same 3,110 names and parents at other addresses; sizes differ for `MtFile::FileInfo` (0x158 → 0x160) and `sFestaNetwork` (0x47c8 → 0x47d0), and v1.4's emulation also recovers `cUIOArenaDown`'s size and id, which v1.0's table has only from the static fallback.
