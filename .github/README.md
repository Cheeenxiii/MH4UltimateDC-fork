# MH4UltimateDC · Ultimate Collection fork

The engine side of **[MH Ultimate Collection](https://github.com/Cheeenxiii/mh-ultimate-collection)**, a content mod that brings Monster Hunter 3 Ultimate's and Generations Ultimate's maps, monsters and systems, underwater combat included, into Monster Hunter 4 Ultimate.

This is a fork of **[CompaLarios18/MH4UltimateDC](https://github.com/CompaLarios18/MH4UltimateDC)**, the static-recompilation PC port of MH4U. Everything about playing the game itself (setup, multiplayer, mods, FAQ) is upstream's, and its docs apply here unchanged: start with [docs/PLAYING.md](../docs/PLAYING.md) or upstream's [README](../README.md).

> **No game data, ever.** Like upstream, this fork holds no ROM, code, assets or keys, and nothing derived from them. Every tool works from your own dumps, on your machine.

## What this fork adds

| Feature | State | Where |
|---|---|---|
| **Native plugin API.** A mod can ship a `.dll`/`.so`/`.dylib` that hooks game functions by name, chained with the port's own hooks and other mods'. ABI 2 also allocates memory from the game's own heap | built and tested on synthetic code; in-game check pending | [`include/mh4u_plugin.h`](../include/mh4u_plugin.h), [`docs/MODS.md`](../docs/MODS.md) ("Native plugins"), [`tools/plugin_sample/`](../tools/plugin_sample/) |
| **Reference recompiles.** MH3U (3DS) and MHXX v1.4 (3DS), recompiled with the same tools as MH4U, to study the code the mod carries over | MH3U: every function recompiled and gametested, 0 differ. MHXX: recompiled; a 2,000-function sample agrees | [`config/games/`](../config/games/README.md), `tools/recompile.py --game <name>` |
| **Recompiler patterns** found on those games: RVCT's Thumb switch helper, PC-relative callbacks, ARM-to-Thumb thunks, literals reached through data pointers | on `uc/main`; candidates for upstream | [`docs/RECOMPILER.md`](../docs/RECOMPILER.md) |
| **Engine symbols** the mod needs: MT Framework's allocator table and default heap, MH4U's monster factory, and the per-monster tables with their bounds | on `uc/main` | `config/symbols.txt` |

Already merged upstream from this fork: the **European game** (EUR v1.1.0, from release 0.1.7) and the **touch-screen panel research**.

## Branches

| Branch | What it is |
|---|---|
| [`uc/main`](https://github.com/Cheeenxiii/MH4UltimateDC-fork/tree/uc/main) | **This fork's line.** Upstream's `main` plus everything above. The mod builds against it |
| [`main`](https://github.com/Cheeenxiii/MH4UltimateDC-fork/tree/main) | A mirror of upstream's `main`. Branches meant as pull requests to upstream start here |
| `uc/<topic>` | Work in progress, merged into `uc/main` when done |
| [`native`](https://github.com/Cheeenxiii/MH4UltimateDC-fork/tree/native) | Upstream's work towards a build with no Azahar, mirrored |

The other branches are upstream's or older work, kept until someone checks they are merged.

## Building

The same as upstream ([docs/SETUP.md](../docs/SETUP.md), [docs/PLAYING.md](../docs/PLAYING.md)). On `uc/main`:

```bash
# MH4U's code library, with the enabled mods' hooks and plugins merged into the build
python3 tools/build_game.py --dump "MH4U v1.3.0 update.cia" --install --fetch-compiler
```

```bash
# a reference game, from your own dump extracted to <work> (config/games/README.md)
python3 tools/recompile.py --game mh3u --exheader <work>/exheader.bin --code <work>/code.bin -o build/recomp-mh3u
```

```bash
python3 -m pytest
```

## Contributing

Upstream's [CONTRIBUTING.md](../CONTRIBUTING.md) applies. In addition:

- Prefer new files to rewriting upstream's, and keep the plugin layer additive, so that `uc/main` keeps merging cleanly with upstream.
- Small focused commits with one-sentence subjects; docs and tests in the same commit as the code.
- Content work (formats, specs, converters, catalog) belongs in [mh-ultimate-collection](https://github.com/Cheeenxiii/mh-ultimate-collection), not here.

## Licence

[GPL-3.0-or-later](../LICENSE), like upstream.
