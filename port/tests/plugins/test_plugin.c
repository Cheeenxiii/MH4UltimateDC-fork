/* A plugin for the host's tests. Its mod config says what it does:
 *   tag    a letter its hook appends to the trace in guest memory
 *   hook   the hook point to wrap (default sMhPad::update)
 *   skip   "1": set r0 to 0x5EED and return to the caller instead of running the chain
 *   fail   "1": hook, then refuse to start
 *   alloc  "1": take a 24-byte block (align 8) and give it back, inside the hook */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "mh4u_plugin.h"

#define TRACE 0x100        /* u32 length, then the letters */
#define ALLOCATED 0x180    /* the block alloc returned */
#define R4_AFTER 0x184     /* r4 as the plugin sees it after alloc */

static const MH4UPluginHost *H;
static uint32_t tag;
static int skip, do_alloc;

static const char *setting(const char *key, const char *fallback) {
    const char *v = H->config(H, key);
    return v ? v : fallback;
}

static void wrap(MH4UCall *call, void *user) {
    (void)user;
    uint32_t n = H->read32(call, TRACE);
    H->write8(call, TRACE + 4 + n, tag);
    H->write32(call, TRACE, n + 1);
    if (do_alloc) {
        uint32_t block = H->alloc(call, 24, 8);
        H->write32(call, ALLOCATED, block);
        H->write32(call, R4_AFTER, H->reg(call, 4));
        H->free(call, block);
    }
    if (skip) {
        H->set_reg(call, 0, 0x5EED);
        H->skip_original(call);
        return;
    }
    H->call_original(call);
}

MH4U_PLUGIN_EXPORT int mh4u_plugin_init(const MH4UPluginHost *host, uint32_t abi) {
    (void)abi;
    H = host;
    tag = (uint32_t)setting("tag", "?")[0];
    skip = strcmp(setting("skip", "0"), "1") == 0;
    do_alloc = strcmp(setting("alloc", "0"), "1") == 0;
    if (!host->hook(host, setting("hook", "sMhPad::update"), wrap, NULL)) {
        return 1;   /* started, with nothing hooked: the host has logged why */
    }
    return strcmp(setting("fail", "0"), "1") != 0;
}
