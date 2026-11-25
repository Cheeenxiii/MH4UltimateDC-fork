# Native plugins

A mod can hook the game's functions with native code: one library per platform, loaded by the port next to the game's code library. This page is the reference for the plugin API, `include/mh4u_plugin.h`, at ABI 4.

## mod.json

```json
{
  "name": "My Plugin Mod",
  "hooks": ["sMhPad::update", {"name": "uMyFind::run", "address": "0x00123456"}],
  "plugin": {"windows": "bin/my_mod.dll", "linux": "bin/my_mod.so", "macos": "bin/my_mod.dylib", "android": "bin/my_mod.so"},
  "config": {"speed": 2}
}
```

- **`hooks`** lists the functions the plugin wraps, by name, so one mod works on every version the port runs. A name comes from `config/hooks.txt`, `config/symbols.txt` or `config/functions.tsv`. A function the project hasn't named needs its USA v1.3.0 address, which the build moves for Europe's v1.1.0.
- **`plugin`** names the library for each platform. A mod with a plugin and no game files is valid.
- **`config`** holds default settings. The player's `config.ini` in the mod's folder overrides them.

## Build

`tools/build_game.py` adds the enabled mods' hooks to the hook points it recompiles with. It then writes `recomp/<program id>.plugins.tsv` next to the code library, listing each plugin in mod order with its settings. `tools/mod_hooks.py` shows what the enabled mods hook.

These stop the build, all reported at once:

- one name at two addresses;
- two names for one address;
- a name the project doesn't know, given without an address.

Two mods hooking the same function is not a conflict: they chain. Turning a plugin mod on or off, or changing its `hooks`, needs a rebuild. `tools/mods.py status` doesn't yet notice a plugin list older than the enabled mods.

## Run

When the port loads the code library, it loads each listed plugin and calls `mh4u_plugin_init(host, abi)`. A plugin that can't be loaded, lacks that function, or returns 0 is turned off for the run: the log says why, its hooks are removed, and the game still starts.

Hooks on one function run as a chain: the last mod in the mod order first, then the earlier ones, then the port's own hook, then the game's function. Each hook calls `call_original` to run the rest, or `skip_original` to return to the game's caller. At most 256 functions can carry plugin chains at once.

## The host table

Each plugin gets its own `MH4UPluginHost` and passes it back as `self`. Members are only ever appended: `abi` and `size` say what a host offers.

| Member | Does |
|---|---|
| `hook(self, name, fn, user)` | wraps a hook point, during init only; 0 if the build lacks it |
| `call_original(call)`, `skip_original(call)` | runs the rest of the chain, or returns to the caller |
| `reg`, `set_reg` | reads and writes guest registers r0 to r15 |
| `read8/16/32`, `write8/16/32` | reads and writes guest memory |
| `guest_pointer(call, addr, size)` | a host pointer to a span inside one mapped page, or NULL |
| `alloc(call, size, align)`, `free(call, addr)` | guest memory from the game's own default heap (ABI 2), from a hook or a frame call |
| `call(call, addr, a0, a1, a2)` | runs the game function at `addr` with r0-r2, returns its r0 (ABI 3), from a hook or a frame call |
| `call2(call, addr, r0_r3, s0_s1, s0_out)` | runs the game function at `addr` with r0-r3 and s0-s1, returns its r0 and, when `s0_out` is set, its float return in s0 (ABI 4) |
| `on_frame(self, fn, user)` | runs once per engine frame, at `sMhMain::frame` |
| `config(self, key)` | reads a setting |
| `log(self, level, text)` | writes to the port's log |
| `mod_name`, `mod_dir`, `program_id` | which mod, where, and which region's game |

`call` is what lets a plugin implement behaviour the game doesn't have (a translated monster action) on top of the engine's own functions: a motion start, an effect, a shell. It puts the guest's registers and flags back afterwards, as `alloc` and `free` do, and uses the guest's stack below its current sp. It returns 0 for `addr` 0 or when the host can't run guest code yet; a plugin that may meet an ABI 2 host checks `host->abi` and `host->size` first.

`call2` is `call` for the engine functions that take a fourth argument or a float. `r0_r3` holds r0 to r3, `s0_s1` holds s0 and s1, and either may be NULL for zeroes. When `s0_out` is not NULL it gets the function's s0, so a float return comes back through it. It puts the guest's core registers, VFP registers and flags back exactly as `call` does, and a plugin that may meet an ABI 3 host checks `host->abi` and `host->size` first.

`alloc` and `free` call MT Framework's own allocator (`MtCtrHeapAllocator` "Heap", named in `config/symbols.txt`), so a plugin's blocks never collide with the game's. They return 0 when the heap is full, or when the game isn't MH4U.

The API never exposes the recompiler's own structures, so they can change without breaking plugins.

## Safety

A plugin is arbitrary code running with the player's permissions. Install plugins only from authors you trust. The launcher doesn't warn about them yet.

## Example

`tools/plugin_sample/sample_plugin.c` is a complete plugin:

```bash
cc -shared -fPIC -Iinclude tools/plugin_sample/sample_plugin.c -o sample_plugin.so
```
