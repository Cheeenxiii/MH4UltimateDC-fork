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

To recompile one and test it in the harness (a "reference recompile": never a port build). `--game` takes the game's function table and extra entries from its folder, uses no hooks or tunables, and refuses code whose hash isn't the one in its `game.json`; without `--game` nothing changes:

```
python3 tools/recompile.py --game <game> --exheader <work>/exheader.bin --code <work>/code.bin -o build/recomp-<game>
cd tools && python3 -m recomp.build ../build/recomp-<game> --harness --opt O0 -D RC_CHECK_RETURNS -o game.so
python3 -m recomp.gametest --lib ../build/recomp-<game>/game.so --exheader <work>/exheader.bin --code <work>/code.bin \
    --sample 2000 --cases 3 --report ../build/recomp-<game>/sample.tsv
```

MH3U: the first pass found 20,281 functions, `find_missing_functions.py` 4,510 candidates, the second pass 24,869 (800 DTI initialisers, 493 SDK); 347 candidates are left for a third pass.

MHXX v1.4: the first pass found 31,372 functions, `find_missing_functions.py` 7,413 candidates (7,412 created, 1 failed), the second pass 38,932, of which the table keeps the 38,931 in `.text` (1,462 DTI initialisers, 377 SDK); 256 candidates are left for a third pass. 1,833 functions are Thumb (MH4U has 257, MH3U 1): real code, most open with a Thumb `push` and ARM code reaches them with 4,333 `blx` calls.

MHXX's v1.4 update (v4.8.0, title 0004000E00197100, version 4224): a clean dump of the official update, decrypted and checked against its own NCCH hashes, has the same exheader and `code.bin` as the copy a fan translation repackaged (the translation changes only RomFS files). The update replaces the code, so `mhxx/` holds v1.4's tables. Its class registry against v1.0's: the same 3,110 names and parents at other addresses; sizes differ for `MtFile::FileInfo` (0x158 → 0x160) and `sFestaNetwork` (0x47c8 → 0x47d0), and v1.4's emulation also recovers `cUIOArenaDown`'s size and id, which v1.0's table has only from the static fallback.

## MHXX's code modules (CRO)

MHXX keeps much of its code outside `code.bin`: 109 CRO modules in RomFS `/modules_MasterRelease/` (one per large monster `roEmNNN` and small monster `roEmsNNN`, the 16 weapon types `roPlayerQuest00`–`15`, `roOtomo`, `roQuest`, `roVillage`, `roTitle`, `roResult`, `roSwkbd`), with `static.crs` holding the static executable's tables and `/.crr/static_MasterRelease.crr` the module list. Together they hold 0x6384b8 bytes of code (6.5 MB, against `code.bin`'s 11 MB of `.text`). A recompile of `code.bin` alone has none of that code: the static side calls into modules through 699 veneers (`ldr pc, [pc, #-4]`) whose word the loader overwrites, and that until then all point at one stub. MH4U and MH3U have no modules.

`tools/cro.py` reads a module, places it at a chosen base, applies its relocations and its imports from the static executable, and lists its entry points for the recompiler's `Analyzer`. Every one of the 109 modules loads: 135,931 patches, all `R_ARM_ABS32`; 31,734 imports from static.

```
python3 tools/cro.py info <romfs>/modules_MasterRelease/roEm001.cro
python3 tools/cro.py imports roEm001.cro --crs static.crs        # the static addresses it imports
```

`roEm001.cro` (Rathian): code 0x21c14 bytes, 392 imports from static (330 functions, 22 data, the rest veneers sharing a target), 1,271 relocations. The analyser finds 265 functions and 32,700 instructions in it with no problems. Recompiling modules, and linking them to the static library at run time, is not done yet.

## Class vtables

`tools/mt_vtables.py` finds every MT class's instance vtable. It emulates the DTI initialisers (as `mt_dti.py` does) to read each DTI's own vtable. Then it emulates each DTI's `newInstance` (slot 2) with the allocator getter replaced by a fake allocator, and records every vtable the constructors store in the new object: the last is the class's, the earlier ones its bases'. Classes with no instance of their own (abstract ones) take the nearest vtable that all their emulated subclasses' chains store. With `--module`, CRO modules are loaded beside `code.bin` with the static veneers into them resolved, so classes whose constructors live in a module (MHXX's monsters) resolve too.

```
python3 tools/mt_vtables.py --exheader <work>/exheader.bin --code <work>/code.bin -o mh4u.vt
python3 tools/mt_vtables.py --exheader ... --code ... --crs static.crs --module <romfs>/*.cro -o mhxx.vt
```

| Game | Classes | Vtables found | by emulation | from subclasses' chains | static fallback |
|---|---|---|---|---|---|
| MH4U v1.3.0 | 991 | 982 | 940 | 36 | 6 |
| MHXX v1.4 (with its 109 modules) | 3,109 | 3,103 | 2,964 | 128 | 11 |
| MH3U | 1,218 | 1,208 | 1,167 | 34 | 7 |

Slots run to the next known vtable; empty slots (0) count, trailing ones don't. The output lists addresses only, but it's derived from game code: keep it outside the repository.

## Function maps between games

`tools/fnmap.py` maps functions between two games (or a game and a module) from their recompiler analysis: anchors where a function's normalised instructions are unique and identical in both, then calls at aligned positions in mapped pairs, then, for a given list, clear best matches by similarity. The outputs are derived from game code and stay outside the repository.

```
python3 tools/fnmap.py side --game mh4u --exheader <work>/exheader.bin --code <work>/code.bin -o mh4u.side
python3 tools/fnmap.py side --game mhxx --exheader ... --code ... -o mhxx.side
python3 tools/fnmap.py side --module roEm001.cro --crs static.crs -o roEm001.side
python3 tools/fnmap.py map mh4u.side mhxx.side [--similar addresses.txt] -o map.tsv
```

Accuracy, measured on MH4U v1.3.0 against MHXX v1.4 and MH3U: propagation recovers 29–31% of anchors held out from it, 100% (MHXX) and 99.1% (MH3U) of them correctly; a clear similarity match (ratio ≥ 0.7, 0.1 ahead of the next) agrees with propagation for 94% (MHXX, 151/160) and 99% (MH3U, 132/133) of a 300-pair sample. The content repository's `docs/design/monster-port.md` has what this gives for Rathian.
