// Tests of the native plugin host (port/src/plugin_host.h) with real plugin libraries
// (test_plugin.c) and a fake code library: two hook points, a guest memory buffer, and the
// game's allocator played by a stub. Run one test per process: plugin_host_test <name>.
#include <dlfcn.h>

#include <cstdio>
#include <cstring>
#include <map>
#include <string>
#include <vector>

#include "plugin_host.h"

using Port::Plugins::Loader;
using Port::Plugins::PluginHost;
using Port::Plugins::PluginSpec;

extern "C" void rc_call(RCtx*, u32) {}   // recomp.h declares it; the host never calls it here

namespace {

constexpr u32 FRAME = 0x00100000, PAD = 0x00100100;   // hook points, sorted
constexpr u32 TRACE = 0x100, ALLOCATED = 0x180, R4_AFTER = 0x184;
constexpr u32 HEAP_TABLE = 0x2000, ALLOCATOR = 0x2100, VTABLE = 0x2200;
constexpr u32 ALLOC_FN = 0x4000, FREE_FN = 0x4100, BLOCK = 0x8000;

u8 memory[0x10000];
RCtx ctx;
std::map<u32, RHookFn> library;   // what the code library's hook points hold
int failures = 0;

#define CHECK(cond, ...)                                                    \
    do {                                                                    \
        if (!(cond)) {                                                      \
            std::fprintf(stderr, "%s:%d: %s: ", __FILE__, __LINE__, #cond); \
            std::fprintf(stderr, __VA_ARGS__);                              \
            std::fprintf(stderr, "\n");                                     \
            ++failures;                                                     \
        }                                                                   \
    } while (0)

u32 rd(u32 a) {
    u32 v;
    std::memcpy(&v, memory + a, 4);
    return v;
}
void wr(u32 a, u32 v) {
    std::memcpy(memory + a, &v, 4);
}
void trace(char c) {
    const u32 n = rd(TRACE);
    memory[TRACE + 4 + n] = static_cast<u8>(c);
    wr(TRACE, n + 1);
}
std::string traced() {
    return std::string(reinterpret_cast<const char*>(memory + TRACE + 4), rd(TRACE));
}

int set_hook(u32 addr, RHookFn fn) {
    if (addr != FRAME && addr != PAD) {
        return 0;
    }
    library[addr] = fn;
    return 1;
}

void game(RCtx* c) {
    trace('G');
    c->r[0] = 7;
}
void port_hook(RCtx* c, RFunc original) {
    trace('P');
    original(c);
}

const char* const NAMES[] = {"sMhMain::frame", "sMhPad::update"};
const u32 ADDRS[] = {FRAME, PAD};

void* open_lib(const char* path, std::string& error) {
    void* lib = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (!lib) {
        error = dlerror();
    }
    return lib;
}
void* symbol(void* lib, const char* name) {
    return dlsym(lib, name);
}
void close_lib(void* lib) {
    dlclose(lib);
}

// A fresh code library with the port's own hook on PAD, then the plugins loaded in order.
std::vector<std::string> start(std::vector<PluginSpec> plugins) {
    std::memset(memory, 0, sizeof memory);
    std::memset(&ctx, 0, sizeof ctx);
    ctx.mem = memory;
    library.clear();
    RCodeInfo info{};
    info.hook_addrs = ADDRS;
    info.hook_names = NAMES;
    info.hook_count = 2;
    info.set_hook = set_hook;
    info.title_id = 0x0004000000126300;
    PluginHost& host = PluginHost::Get();
    RCodeInfo port = host.Begin(info, Loader{open_lib, symbol, close_lib});
    port.set_hook(PAD, port_hook);
    return host.Load(plugins);
}

void run_pad() {
    library[PAD](&ctx, game);
}

bool logged(const std::vector<std::string>& log, const char* text) {
    for (const auto& line : log) {
        if (line.find(text) != std::string::npos) {
            return true;
        }
    }
    return false;
}

// ── tests ────────────────────────────────────────────────────────────────────

void chain_runs_last_mod_first_then_port_then_game() {
    start({{"A", PLUGIN_1, "/mods/a", {{"tag", "a"}}}, {"B", PLUGIN_2, "/mods/b", {{"tag", "b"}}}});
    run_pad();
    CHECK(traced() == "baPG", "ran in the order %s", traced().c_str());
    CHECK(ctx.r[0] == 7, "r0 is %u, not the game's 7", ctx.r[0]);
}

void skip_original_returns_to_the_caller() {
    start({{"A", PLUGIN_1, "/mods/a", {{"tag", "a"}, {"skip", "1"}}}});
    ctx.r[14] = 0x00123456;
    run_pad();
    CHECK(traced() == "a", "ran %s after a skip", traced().c_str());
    CHECK(ctx.r[0] == 0x5EED, "r0 is %#x, not the plugin's result", ctx.r[0]);
    CHECK(ctx.r[15] == 0x00123456, "returns to %#x, not the caller", ctx.r[15]);
}

void failed_init_takes_its_hooks_back() {
    auto log = start({{"A", PLUGIN_1, "/mods/a", {{"tag", "a"}}},
                      {"F", PLUGIN_2, "/mods/f", {{"tag", "f"}, {"fail", "1"}}}});
    run_pad();
    CHECK(traced() == "aPG", "ran %s: the refused plugin's hook is still there", traced().c_str());
    CHECK(PluginHost::Get().PluginCount() == 1, "%zu plugins kept", PluginHost::Get().PluginCount());
    CHECK(logged(log, "F: its plugin didn't start"), "the log doesn't say F was turned off");
}

void reset_gives_the_port_its_hooks_back() {
    start({{"A", PLUGIN_1, "/mods/a", {{"tag", "a"}}}});
    PluginHost::Get().Reset();
    CHECK(library[PAD] == port_hook, "the hook point doesn't hold the port's hook again");
    run_pad();
    CHECK(traced() == "PG", "ran %s after a reset", traced().c_str());
}

void hooking_a_missing_hook_point_fails_and_says_so() {
    auto log = start({{"A", PLUGIN_1, "/mods/a", {{"tag", "a"}, {"hook", "sNowhere::run"}}}});
    run_pad();
    CHECK(traced() == "PG", "ran %s", traced().c_str());
    CHECK(logged(log, "no hook point for sNowhere::run"), "the log doesn't name the missing hook point");
}

u32 alloc_args[3], freed;
void guest(RCtx* c, u32 target) {
    if (target == ALLOC_FN) {
        std::memcpy(alloc_args, c->r, sizeof alloc_args);
        c->r[0] = BLOCK;
    } else if (target == FREE_FN) {
        freed = c->r[1];
    }
    c->r[4] = 0xDEAD;   // the game's allocator uses callee registers too
}

void alloc_and_free_go_through_the_games_allocator() {
    start({{"A", PLUGIN_1, "/mods/a", {{"tag", "a"}, {"alloc", "1"}}}});
    wr(HEAP_TABLE, ALLOCATOR);
    wr(ALLOCATOR, VTABLE);
    wr(VTABLE + PluginHost::ALLOC_VCALL, ALLOC_FN);
    wr(VTABLE + PluginHost::FREE_VCALL, FREE_FN);
    PluginHost::Get().SetGuestHeap(HEAP_TABLE, guest);
    ctx.r[4] = 0x4444;
    run_pad();
    CHECK(rd(ALLOCATED) == BLOCK, "alloc gave %#x", rd(ALLOCATED));
    CHECK(alloc_args[0] == ALLOCATOR && alloc_args[1] == 24 && alloc_args[2] == 8,
          "alloc called with (%#x, %u, %u)", alloc_args[0], alloc_args[1], alloc_args[2]);
    CHECK(freed == BLOCK, "free got %#x", freed);
    CHECK(rd(R4_AFTER) == 0x4444, "r4 is %#x after alloc: the guest's registers weren't put back", rd(R4_AFTER));
}

}  // namespace

int main(int argc, char** argv) {
    const std::map<std::string, void (*)()> tests = {
        {"chain_runs_last_mod_first_then_port_then_game", chain_runs_last_mod_first_then_port_then_game},
        {"skip_original_returns_to_the_caller", skip_original_returns_to_the_caller},
        {"failed_init_takes_its_hooks_back", failed_init_takes_its_hooks_back},
        {"reset_gives_the_port_its_hooks_back", reset_gives_the_port_its_hooks_back},
        {"hooking_a_missing_hook_point_fails_and_says_so", hooking_a_missing_hook_point_fails_and_says_so},
        {"alloc_and_free_go_through_the_games_allocator", alloc_and_free_go_through_the_games_allocator},
    };
    auto it = argc == 2 ? tests.find(argv[1]) : tests.end();
    if (it == tests.end()) {
        std::fprintf(stderr, "usage: plugin_host_test <test>\n");
        return 2;
    }
    it->second();
    return failures ? 1 : 0;
}
