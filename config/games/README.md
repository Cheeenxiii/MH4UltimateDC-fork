# Reference games

Tables from other MT Framework Mobile games, used to study them next to MH4U (the MH Ultimate Collection's "reference recompiles"). They are not port targets: nothing here changes how MH4U builds, and `config/versions.json` stays MH4U's alone.

Each folder holds:

- `game.json`: which dump the tables come from (program id, exheader and decompressed code hashes, segments, the DTI constructor `mt_dti.py` found). Hashes and addresses only, like `versions.json`.
- `mt_classes.tsv`: the class registry, made with `tools/mt_dti.py` exactly as `config/mt_classes.tsv` is.
- `functions.tsv` (MH3U so far): the function table, made as `config/functions.tsv` is: Ghidra export, `find_missing_functions.py`, a second Ghidra pass, then `build_function_table.py`.

| Folder | Dump | Classes | Functions |
|---|---|---|---|
| `mh3u/` | MH3U USA cartridge | 1,218 | 24,869 |
| `mhxx/` | MHXX JPN cartridge, v1.0 | 3,110 | not yet |

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
    --dti-ctor <game.json's constructor> -o config/games/<game>/functions.tsv
```

To recompile one and test it in the harness (a "reference recompile": never a port build). `--game` takes the game's function table and extra entries from its folder, uses no hooks or tunables, and refuses code whose hash isn't the one in its `game.json`; without `--game` nothing changes:

```
python3 tools/recompile.py --game <game> --exheader <work>/exheader.bin --code <work>/code.bin -o build/recomp-<game>
cd tools && python3 -m recomp.build ../build/recomp-<game> --harness --opt O0 -D RC_CHECK_RETURNS -o game.so
python3 -m recomp.gametest --lib ../build/recomp-<game>/game.so --exheader <work>/exheader.bin --code <work>/code.bin \
    --sample 2000 --cases 3 --report ../build/recomp-<game>/sample.tsv
```

MH3U: the first pass found 20,281 functions, `find_missing_functions.py` 4,510 candidates, the second pass 24,869 (800 DTI initialisers, 493 SDK); 347 candidates are left for a third pass.

MHXX's v1.4 update (v4.8.0, title 0004000E00197100): a clean dump of the official update, decrypted and checked against its own NCCH hashes, has the same exheader and `code.bin` as the copy a fan translation repackaged (the translation changes only RomFS files). Its tables aren't made yet.
