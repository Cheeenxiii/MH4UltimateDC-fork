/*
 * mh4u_plugin.h: the native plugin API of the MH4U port (docs/MODS.md, "Native plugins").
 *
 * A mod may ship one native library (.dll, .so, .dylib) that the port loads with the game's
 * code library. Each plugin gets a host table of its own (pass it back as `self`). It exports
 *
 *     int mh4u_plugin_init(const MH4UPluginHost *host, uint32_t abi);
 *
 * which returns nonzero on success. `abi` is the host's MH4U_PLUGIN_ABI; a plugin built for a
 * newer ABI than the host's returns 0 (the mod is then turned off for this run, with a
 * message). In init the plugin asks for hooks by function name and for per-frame calls; it
 * keeps `host`, which stays valid until the game's code library is unloaded.
 *
 * Hooks: a plugin wraps a game function that the code library was built with as a hook point
 * (config/hooks.txt, plus the names in the mods' mod.json "hooks"). Several mods and the port
 * itself can hook one function: they form a chain. The last mod in the mod order runs first,
 * then the earlier ones, then the port's own hook, then the game's function. A hook calls
 * call_original to run the rest of the chain, or skip_original to return to the game's caller
 * with r0-r3 as it set them.
 *
 * Everything a hook does with the game (registers, memory) goes through the MH4UCall it gets,
 * on the emulation thread. The API never hands out the recompiler's own structures, so the
 * port can change them without breaking plugins.
 *
 * Guest memory: alloc and free (ABI 2) take blocks from the game's own default heap, the
 * allocator the engine's global allocations use, by calling the game's allocator on the
 * emulation thread. They take an MH4UCall, so they are for hooks and frame calls, not init:
 * a plugin that needs memory from the start allocates in its first frame call. A plugin
 * that should also run on an ABI 1 host checks host->size before using them (as
 * tools/plugin_sample/sample_plugin.c does).
 *
 * Native plugins run arbitrary code on the player's PC: the launcher is to warn before turning
 * one on, and the mod catalog to label them (docs/MODS.md).
 *
 * Licence: GPL-3.0-or-later, like the port.
 */
#ifndef MH4U_PLUGIN_H
#define MH4U_PLUGIN_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Raised when a function is added to the end of MH4UPluginHost (plugins check host->size
 * before using a newer member) or when a member's meaning changes (a plugin built for a
 * newer ABI than the host's refuses to start). */
#define MH4U_PLUGIN_ABI 2   /* 2: alloc, free */
#define MH4U_PLUGIN_INIT_SYMBOL "mh4u_plugin_init"

#if defined(_WIN32)
#define MH4U_PLUGIN_EXPORT __declspec(dllexport)
#else
#define MH4U_PLUGIN_EXPORT __attribute__((visibility("default")))
#endif

/* One run of a hooked function: the guest's registers and the rest of the chain. Valid only
 * during the hook (or frame) call it is passed to. */
typedef struct MH4UCall MH4UCall;

typedef void (*MH4UHookFn)(MH4UCall *call, void *user);
typedef void (*MH4UFrameFn)(MH4UCall *call, void *user);

enum { MH4U_LOG_DEBUG = 0, MH4U_LOG_INFO = 1, MH4U_LOG_WARNING = 2, MH4U_LOG_ERROR = 3 };

typedef struct MH4UPluginHost {
    uint32_t abi;            /* MH4U_PLUGIN_ABI of the host */
    uint32_t size;           /* sizeof(MH4UPluginHost) in the host: members past it are absent */

    const char *mod_name;    /* the mod's name (mod.json "name", or its folder's) */
    const char *mod_dir;     /* the mod's folder in the mod library, for its own files */
    uint64_t program_id;     /* the game: 0x0004000000126300 USA, 0x0004000000126100 Europe */

    /* Hooks the game function `name` (a hook point's name, e.g. "sMhPad::update"). Returns 0
     * when the code library has no hook point of that name (it was built without this mod's
     * hooks: the host logs that the library needs building again), 1 otherwise. Init only. */
    int (*hook)(const struct MH4UPluginHost *self, const char *name, MH4UHookFn fn, void *user);
    /* Runs the rest of the chain with the registers as they are now; may be called more than
     * once, or not at all. */
    void (*call_original)(MH4UCall *call);
    /* Returns to the game's caller without running the rest of the chain: set r0-r3 first. */
    void (*skip_original)(MH4UCall *call);

    /* Guest registers r0-r15 (13 sp, 14 lr, 15 pc). */
    uint32_t (*reg)(MH4UCall *call, unsigned n);
    void (*set_reg)(MH4UCall *call, unsigned n, uint32_t value);

    /* Guest memory at guest addresses, little endian, as the game sees it. */
    uint32_t (*read32)(MH4UCall *call, uint32_t addr);
    uint32_t (*read16)(MH4UCall *call, uint32_t addr);
    uint32_t (*read8)(MH4UCall *call, uint32_t addr);
    void (*write32)(MH4UCall *call, uint32_t addr, uint32_t value);
    void (*write16)(MH4UCall *call, uint32_t addr, uint32_t value);
    void (*write8)(MH4UCall *call, uint32_t addr, uint32_t value);
    /* A host pointer to `size` bytes of guest memory at `addr`, or NULL when they aren't one
     * plain mapped span (unmapped, crossing into a page the GPU watches...): use the read and
     * write functions then. Valid during the call only. */
    void *(*guest_pointer)(MH4UCall *call, uint32_t addr, uint32_t size);

    /* One line in the port's log, prefixed with the mod's name. */
    void (*log)(const struct MH4UPluginHost *self, int level, const char *message);
    /* The mod's setting `key`: the player's mod config (config.ini in the mod's folder,
     * `key = value` lines) over mod.json's "config" defaults; NULL when neither has it. */
    const char *(*config)(const struct MH4UPluginHost *self, const char *key);

    /* Calls fn once per game frame, at the start of the engine's frame (sMhMain::frame), on
     * the emulation thread. Returns 0 if the code library has no such hook point. Init only. */
    int (*on_frame)(const struct MH4UPluginHost *self, MH4UFrameFn fn, void *user);

    /* ── ABI 2 ── */

    /* Allocates `size` bytes of guest memory from the game's default heap, aligned to `align`
     * bytes (a power of two; 0 means 16), and returns its guest address, or 0 when the heap is
     * full or unknown (another game, or the game hasn't set its heap up yet: logged once).
     * The block's contents are undefined. The game's own registers are left as they were. */
    uint32_t (*alloc)(MH4UCall *call, uint32_t size, uint32_t align);
    /* Gives back a block from alloc (0 is ignored). */
    void (*free)(MH4UCall *call, uint32_t addr);
} MH4UPluginHost;

typedef int (*MH4UPluginInit)(const MH4UPluginHost *host, uint32_t abi);

#ifdef __cplusplus
}
#endif

#endif /* MH4U_PLUGIN_H */
