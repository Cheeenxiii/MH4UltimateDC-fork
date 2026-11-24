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

`roEm001.cro` (Rathian): code 0x21c14 bytes, 392 imports from static (330 functions, 22 data, the rest veneers sharing a target), 1,271 relocations. The analyser finds 265 functions in it with no problems.

### Recompiling the modules

`tools/recompile_module.py` places the modules one after another from a fixed base (0x02000000 by default, each at a 64 KiB boundary) and loads each as the system's loader would: its relocations, its imports from the static executable, and its imports from other modules (17 of the 126 import tables point at another module: 14 at `roOtomo`, one each at `roEm008`, `roEm076`, `roEm084` and `roEm087`). Each module is recompiled like any code. A branch into the static code or another module, through a veneer, becomes a call through `rc_call`, not a bad jump. The static code is recompiled with them, from `code.bin` with its own veneers into the modules filled in: a recompile of `code.bin` as shipped folds those veneers into jumps to the loader's placeholder, which ends in `svcBreak`. The output holds the modules' C, that static C and one function table for both, so one library has it all. `modules.tsv` records each module's base: the C folds literal pools into constants, so it runs a module only at the base it was recompiled for.

`recomp.modtest` is gametest for the modules: both machines get the static code (its veneers into the modules filled in) and every module at its base, and each module function runs from the same random states in both.

```
python3 tools/recompile_module.py --static-entries config/games/mhxx/extra_entries.txt --crs static.crs <romfs>/modules_MasterRelease/*.cro
python3 tools/recompile_module.py --game mhxx --exheader ... --code ... --crs static.crs -o build/recomp-mhxx-modules <romfs>/modules_MasterRelease/*.cro
cd tools && python3 -m recomp.build ../build/recomp-mhxx-modules --harness --opt O0 -D RC_CHECK_RETURNS -o game.so
python3 -m recomp.modtest --build ../build/recomp-mhxx-modules --exheader ... --code ... --crs static.crs <romfs>/modules_MasterRelease/*.cro
```

The first command matters for the static recompile too: 4,256 static functions are branched to from modules, and 956 of them aren't in MHXX's function table, because only modules call them. `config/games/mhxx/extra_entries.txt` lists them all (addresses only), and `recompile.py --game mhxx` (and `recompile_module.py`) reads it: the static recompile goes from 63,087 to 63,892 functions. Only imports a module branches to count (a veneer's word or a branch relocation); the others are data, some of it in the static `.text`. Nine of those branch targets (from `roEm003`, `roEm069`, `roEm070`, `roEms045` and `roOtomo`) sit inside a known Thumb function and are reached in ARM state, most likely through veneers that never run: the recompile traps there, where the game would run garbage.

All 109 modules, after the fixes for the first run's 40 leftovers (functions other modules import are entry points, a veneer entry is always ARM, the static code's patched veneers are tail calls): 36,669 functions, 4 random cases each, in 13 minutes. 20,718 pass, 15,770 fault the same way in both, 178 are inconclusive, and none differ in state, memory or exit. `roPlayerQuest05` has no functions (0xac bytes of code and no entry points). Three functions were left, none of them a recompiler fault: one in `roEm060` is a veneer whose static target made an indirect call through a pointer from the random state into the middle of another module's function (it passes, or faults the same way in both, in 64 more cases); two in `roTitle` were not code at all, but data words pointing at a veneer's address word and into a veneer. `module_entries` now drops such pointers (4 in all 109 modules, all in `roTitle`); the full run hasn't been repeated for that change. `roEm001` alone, in an earlier run: 289 pass, 160 shared faults, 0 differ.

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

`tools/fnmap.py` maps functions between two games (or a game and a module) from their recompiler analysis: anchors where a function's normalised instructions are unique and identical in both, then calls at aligned positions in mapped pairs. With `--vtables`, the slots of every class both games name are aligned in order (slots get added between versions) and mapped where the functions look alike (ratio ≥ 0.6). Next, slots between two mapped slots at equal distances in both games are mapped by position, if they still look a little alike (ratio ≥ 0.3). Last, for a given list, clear best matches by similarity. The outputs are derived from game code and stay outside the repository.

```
python3 tools/fnmap.py side --game mh4u --exheader <work>/exheader.bin --code <work>/code.bin -o mh4u.side
python3 tools/fnmap.py side --game mhxx --exheader ... --code ... -o mhxx.side
python3 tools/fnmap.py side --module roEm001.cro --crs static.crs -o roEm001.side
python3 tools/fnmap.py map mh4u.side mhxx.side [--vtables mh4u.vt mhxx.vt] [--class-pair uEm001=uEm001_00] [--similar addresses.txt] -o map.tsv
```

A module's calls into the static code go through veneers, so a module's side records them apart, with their positions. `map --module-side roEm001.side` merges the module into the static side B, and those calls become call sites: propagation from a mapped module function reaches the static functions it imports. `--seed pairs.tsv` adds pairs known by other means before anything else (one `A B` per line; a map's own output works), such as the action handlers `monster_actions.py pairs` gives. `side --entries file` adds function entries the analysis can't find, such as handlers only tail calls reach (a dispatcher's `b handler` otherwise folds the handler into the dispatcher).

Accuracy, measured on MH4U v1.3.0 against MHXX v1.4 and MH3U: propagation recovers 29–31% of anchors held out from it, 100% (MHXX) and 99.1% (MH3U) of them correctly; a clear similarity match (ratio ≥ 0.7, 0.1 ahead of the next) agrees with propagation for 94% (MHXX, 151/160) and 99% (MH3U, 132/133) of a 300-pair sample.

With `--vtables` (30% of anchors held out, seed 1): MHXX recovers 281 of 541 held-out anchors (172 without vtables), MH3U 515 of 774 (273 without), all of them correctly; the whole maps grow from 3,540 to 7,542 pairs (MHXX) and from 3,967 to 6,866 (MH3U). Held-out anchors are 12 tokens or longer, so this doesn't test the many one- and two-instruction slot stubs, which align by position. Slots placed by position alone are right for 97.9% (MHXX) and 99.5% (MH3U) of mapped slots, left out one at a time. The content repository's `docs/design/monster-port.md` has what this gives for Rathian.

## Monster actions

MH4U, MH3U and MHXX run a monster's current action the same way. A dispatcher reads two bytes, a category and an index, and jumps through a table on the category. Each category then switches on the index, through a jump table or a compare chain, to a case block. Most case blocks tail-call the action's handler, some with constants in r1-r3. `tools/monster_actions.py list` walks a dispatcher down to every (category, index) and its handler. `pairs` lines up two games' inventories by action id and keeps a handler pair when each handler of A meets exactly one handler of B.

```
python3 tools/monster_actions.py list --exheader <work>/exheader.bin --code <work>/code.bin --dispatcher 0x6e9cac --range 0x6d4f80 0x6ec8e0 -o mh4u_uEm001.tsv
python3 tools/monster_actions.py list --module roEm001.cro --crs static.crs --dispatcher 0x2009704 -o mhxx_roEm001.tsv
python3 tools/monster_actions.py pairs mh4u_uEm001.tsv mhxx_roEm001.tsv -o pairs.tsv
```

Rathian's dispatchers:

| Game | Class | Dispatcher | Category, index | Categories |
|---|---|---|---|---|
| MH4U v1.3.0 | `uEm001` (vtable slot 44) | 0x006e9cac | bytes 0x1ca, 0x1cb of the struct at `this+0xe28` | 14 |
| MH3U | `uEm002` (vtable slot 47) | 0x00687d30 | bytes 0xdf, 0xe0 of the struct at `this+0x1a48` | 14 |
| MHXX v1.4 | `uEm001_00`, in `roEm001` loaded at 0x02000000 | 0x02009704 | bytes at `this+0x6bf0`, `this+0x6bf1` | 18 |

| | MH4U | MH3U | MHXX |
|---|---|---|---|
| actions | 342 | 191 | 301 |
| distinct handlers | 97 | 66 | 83 |
| case blocks that tail-call a handler | 307 | 182 | 274 |

The action ids are shared. Of MHXX's 301 actions, 273 have an MH4U action with the same id. Of the 197 shared actions whose case blocks pass constants, 194 pass the same ones in both games. Each of MH4U's 80 handlers that a shared action reaches meets exactly one MHXX handler, including the 57 MH4U handlers that serve several actions. With MH3U, 174 ids are shared, 104 pass the same constants, and 63 handlers pair (one MH4U handler meets two). That's consistency. The independent check is a function map built without the pairs (`fnmap.py map --module-side`, vtables and similarity, no `--seed`): it holds 42 of the 80 MHXX handler pairs, and all 42 agree. One pair conflicts, with a static engine function that MH4U reaches through Rathian's own code. Seeded with the 80, the map gains 45 pairs (36 seeds, 9 propagated), and one existing pair changes. Whether each pair is the same move in game needs an in-game check.
