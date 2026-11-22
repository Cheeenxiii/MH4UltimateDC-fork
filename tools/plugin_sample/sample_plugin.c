/*
 * A sample native plugin (docs/MODS.md, "Native plugins"): it wraps one game function, and
 * counts frames. Everything it does is set in its mod's config (mod.json "config", or the
 * player's config.ini in the mod's folder):
 *
 *   hook        the hook point to wrap (default sMhPad::update)
 *   op, value   after the game's function: "add" value to r0, or "mul" r0 by value
 *   skip        "1": don't run the rest of the chain; return value in r0 instead
 *   frames_at   a guest address: a u32 there counts frames (on_frame), for tests
 *   fail        "1": init hooks, then refuses (the host must undo its hooks)
 *
 * Build: cc -shared -fPIC -I<repo>/include sample_plugin.c -o sample_plugin.so (.dll, .dylib)
 * Licence: GPL-3.0-or-later.
 */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "mh4u_plugin.h"

static const MH4UPluginHost *H;
static int op_mul, skip;
static uint32_t value, frames_at;

static const char *setting(const char *key, const char *fallback) {
    const char *v = H->config(H, key);
    return v ? v : fallback;
}

static void wrap(MH4UCall *call, void *user) {
    (void)user;
    if (skip) {
        H->set_reg(call, 0, value);
        H->skip_original(call);
        return;
    }
    H->call_original(call);
    uint32_t r0 = H->reg(call, 0);
    H->set_reg(call, 0, op_mul ? r0 * value : r0 + value);
}

static void frame(MH4UCall *call, void *user) {
    (void)user;
    if (frames_at) {
        H->write32(call, frames_at, H->read32(call, frames_at) + 1);
    }
}

MH4U_PLUGIN_EXPORT int mh4u_plugin_init(const MH4UPluginHost *host, uint32_t abi) {
    if (abi < MH4U_PLUGIN_ABI || host->size < sizeof(MH4UPluginHost)) {
        return 0;   /* the host is older than this plugin */
    }
    H = host;
    op_mul = strcmp(setting("op", "add"), "mul") == 0;
    value = (uint32_t)strtoul(setting("value", "0"), NULL, 0);
    skip = strcmp(setting("skip", "0"), "1") == 0;
    frames_at = (uint32_t)strtoul(setting("frames_at", "0"), NULL, 0);
    const char *name = setting("hook", "sMhPad::update");
    if (!host->hook(host, name, wrap, NULL)) {
        host->log(host, MH4U_LOG_WARNING, "sample plugin: nothing hooked");
    }
    if (frames_at && !host->on_frame(host, frame, NULL)) {
        host->log(host, MH4U_LOG_WARNING, "sample plugin: no frame calls");
    }
    host->log(host, MH4U_LOG_INFO, "sample plugin ready");
    return strcmp(setting("fail", "0"), "1") != 0;
}
