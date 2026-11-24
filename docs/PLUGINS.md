# Native plugins

A mod can hook the game's functions with native code: one library per platform, loaded by the port next to the game's code library. This page is the reference for the plugin API, `include/mh4u_plugin.h`, at ABI 2.

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
| `on_frame(self, fn, user)` | runs once per engine frame, at `sMhMain::frame` |
| `config(self, key)` | reads a setting |
| `log(self, level, text)` | writes to the port's log |
| `mod_name`, `mod_dir`, `program_id` | which mod, where, and which region's game |

`alloc` and `free` call MT Framework's own allocator (`MtCtrHeapAllocator` "Heap", named in `config/symbols.txt`), so a plugin's blocks never collide with the game's. They return 0 when the heap is full, or when the game isn't MH4U.

The API never exposes the recompiler's own structures, so they can change without breaking plugins.

## Safety

A plugin is arbitrary code running with the player's permissions. Install plugins only from authors you trust. The launcher doesn't warn about them yet.

## Example

`tools/plugin_sample/sample_plugin.c` is a complete plugin:

```bash
cc -shared -fPIC -Iinclude tools/plugin_sample/sample_plugin.c -o sample_plugin.so
```
