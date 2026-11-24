# MH4UltimateDC, Ultimate Collection fork

This is a fork of [CompaLarios18/MH4UltimateDC](https://github.com/CompaLarios18/MH4UltimateDC), the static-recompilation PC port of Monster Hunter 4 Ultimate. It adds what the content mod [MH Ultimate Collection](https://github.com/Cheeenxiii/mh-ultimate-collection) needs from the engine, and nothing else.

Everything about playing the game is upstream's, and its docs apply unchanged: start with [README.md](../README.md) and [docs/PLAYING.md](../docs/PLAYING.md).

This fork, like upstream, contains no game data.

## What it adds

| Addition | Where |
|---|---|
| Native plugins: a mod's library hooks game functions by name, chained with the port's own hooks, and can allocate from the game's heap | [docs/PLUGINS.md](../docs/PLUGINS.md), `include/mh4u_plugin.h`, `port/src/plugin*`, `tools/mod_hooks.py` |
| Recompiler fixes found on other MT Framework games: RVCT's Thumb switch helper, PC-relative callbacks, ARM-to-Thumb thunks, a deterministic analysis order | `tools/recomp/analysis.py`, `tools/recomp/emit.py`, `tools/recompile.py` |
| A runtime fix: an indirect call to address 1 no longer reaches an empty inline cache | `tools/recomp/runtime/recomp.h` |
| A class-registry fix: each initialiser is emulated from clean memory | `tools/mt_dti.py`, `config/mt_classes.tsv` |
| Engine symbols: MT Framework's heap allocator, MH4U's monster factory and per-monster tables | `config/symbols.txt` |
| The Extra Data folder of a game, read from its exheader | `tools/extdata_path.py` |

The recompiler, runtime and registry fixes apply to MH4U too, and are meant to be offered upstream.

## Branches

- **`uc/main`** is this fork's line: upstream's `main` plus the additions above.
- **`main`** mirrors upstream's `main`. Pull requests to upstream start from it.

## Tests

`tests/uc/run` runs the tests of this fork's additions: pytest for the Python tools, CMake and CTest for the plugin host. Upstream's own suite runs with `python3 -m pytest`, as upstream documents.

## Contributing

Upstream's [CONTRIBUTING.md](../CONTRIBUTING.md) applies. In addition, this fork never edits upstream's code, docs or tests beyond what an addition strictly needs, so `uc/main` keeps rebasing cleanly. Logic specific to the mod belongs in the mod's repository.

## Licence

[GPL-3.0-or-later](../LICENSE), like upstream.
