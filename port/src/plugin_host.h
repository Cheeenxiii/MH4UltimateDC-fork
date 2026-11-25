// The native plugin host (include/mh4u_plugin.h, docs/PLUGINS.md): hook chains
// over the code library's hook points, and the host table each plugin gets. Kept free of
// Azahar, like hook_address.h, so tests build it on its own (tests/test_plugin_host.py);
// plugins.cpp gives it Azahar's library loading and log.
//
// A hook point has one slot in the code library (rc_hooks[]), and an RHookFn gets no pointer
// of its own, so each hooked point that plugins use gets one of SLOTS fixed dispatchers,
// Slot<K>, which runs chain K: the plugins' hooks (the last mod first), then the port's own
// hook, then the game's function. Points that no plugin hooks keep the port's hook as it is,
// at no cost. The port's hooks reach the code library through Begin()'s set_hook, which
// records them here, so they keep working under a chain.
//
// Guest memory (alloc/free, ABI 2) comes from the game's default heap: SetGuestHeap gives the
// address of MT Framework's allocator table (one MtAllocator* per allocator category; entry
// 0 is the default heap) and the function that runs guest code (rc_call in the port). The
// host calls the allocator's virtual alloc (+0x20) and free (+0x38) like the game does, and
// puts the guest's registers back afterwards.
#pragma once

#include <array>
#include <cstring>
#include <deque>
#include <map>
#include <memory>
#include <string>
#include <utility>
#include <vector>

extern "C" {
#include "recomp.h"
}
#include "../../include/mh4u_plugin.h"
#include "hook_address.h"

struct MH4UCall {
    RCtx* ctx;
    void* chain;      // PluginHost::Chain*, or nullptr for a frame call (no chain to run)
    size_t next;      // the chain's next link
    RFunc original;
};

namespace Port::Plugins {

/// One mod's plugin, as build_game.py lists it (<program id>.plugins.tsv next to the library).
struct PluginSpec {
    std::string mod;        // the mod's name
    std::string library;    // the plugin's path
    std::string dir;        // the mod's folder
    std::map<std::string, std::string> config;
};

/// How the host opens libraries: Azahar's DynamicLibrary in the port, dlopen in tests.
struct Loader {
    void* (*open)(const char* path, std::string& error) = nullptr;
    void* (*symbol)(void* library, const char* name) = nullptr;
    void (*close)(void* library) = nullptr;
};

class PluginHost {
public:
    static constexpr size_t SLOTS = 256;
    static constexpr const char* FRAME_HOOK = "sMhMain::frame";
    // MtAllocator's virtual functions (USA v1.3.0 and EUR v1.1.0, docs: config/symbols.txt).
    static constexpr u32 ALLOC_VCALL = 0x20;   // void* alloc(this, u32 size, u32 align)
    static constexpr u32 FREE_VCALL = 0x38;    // void free(this, void* p), p may be null
    using GuestCall = void (*)(RCtx* ctx, u32 target);

    static PluginHost& Get() {
        static PluginHost host;
        return host;
    }

    /// A new code library: forgets everything from the last one (closing its plugins) and returns
    /// the RCodeInfo to give the port's own hooks, whose set_hook goes through the host.
    RCodeInfo Begin(const RCodeInfo& info, Loader loader = {}) {
        Reset();
        info_ = info;
        loader_ = loader;
        RCodeInfo port = info;
        port.set_hook = info.set_hook ? &PortSetHook : nullptr;
        return port;
    }

    /// Loads the plugins in mod order. Returns lines for the log.
    std::vector<std::string> Load(const std::vector<PluginSpec>& specs) {
        std::vector<std::string> log;
        for (const PluginSpec& spec : specs) {
            LoadOne(spec, log);
        }
        log_ = nullptr;
        return log;
    }

    /// Where log lines from plugins go while the game runs (Load's lines come back from Load).
    void SetLog(void (*sink)(int level, const std::string& line)) {
        sink_ = sink;
    }

    /// Where the game keeps its allocator table, and how to run guest code (0 / null: the
    /// game's heap is unknown, alloc returns 0). Set after Begin, which forgets it.
    void SetGuestHeap(u32 allocator_table, GuestCall call) {
        heap_table_ = allocator_table;
        guest_call_ = call;
        heap_warned_ = false;
    }

    size_t PluginCount() const {
        return plugins_.size();
    }

    void Reset() {
        for (auto& [addr, chain] : chains_) {
            if (chain->slot >= 0 && info_.set_hook) {
                info_.set_hook(addr, chain->port);
            }
        }
        for (auto& p : plugins_) {
            if (p->library && loader_.close) {
                loader_.close(p->library);
            }
        }
        chains_.clear();
        plugins_.clear();
        slots_.fill(nullptr);
        used_slots_ = 0;
        frame_fns_.clear();
        frame_hooked_ = false;
        info_ = {};
        heap_table_ = 0;
        guest_call_ = nullptr;
        heap_warned_ = false;
    }

private:
    struct Link {
        MH4UHookFn fn;
        void* user;
    };
    struct Chain {
        u32 addr = 0;
        std::vector<Link> links;   // first runs first
        RHookFn port = nullptr;
        int slot = -1;
    };
    struct Plugin {
        MH4UPluginHost host;       // first: the plugin hands it back as `self`
        PluginSpec spec;
        void* library = nullptr;
        bool loading = false;
    };

    PluginHost() = default;

    static Plugin* Self(const MH4UPluginHost* self) {
        return reinterpret_cast<Plugin*>(const_cast<MH4UPluginHost*>(self));
    }

    Chain& ChainAt(u32 addr) {
        auto& slot = chains_[addr];
        if (!slot) {
            slot = std::make_unique<Chain>();
            slot->addr = addr;
        }
        return *slot;
    }

    // ── running a chain ───────────────────────────────────────────────────────

    static void Run(Chain* chain, RCtx* ctx, RFunc original, size_t at) {
        if (at < chain->links.size()) {
            MH4UCall call{ctx, chain, at + 1, original};
            chain->links[at].fn(&call, chain->links[at].user);
        } else if (chain->port) {
            chain->port(ctx, original);
        } else {
            original(ctx);
        }
    }

    template <size_t K>
    static void Slot(RCtx* ctx, RFunc original) {
        Run(Get().slots_[K], ctx, original, 0);
    }

    template <size_t... K>
    static std::array<RHookFn, SLOTS> MakeSlots(std::index_sequence<K...>) {
        return {&Slot<K>...};
    }
    static const std::array<RHookFn, SLOTS>& SlotFns() {
        static const std::array<RHookFn, SLOTS> fns = MakeSlots(std::make_index_sequence<SLOTS>{});
        return fns;
    }

    // The port's hooks: recorded, and put in the library directly unless a chain runs there.
    static int PortSetHook(u32 addr, RHookFn fn) {
        PluginHost& h = Get();
        auto it = h.chains_.find(addr);
        if (it != h.chains_.end() && it->second->slot >= 0) {
            it->second->port = fn;
            return 1;
        }
        const int ok = h.info_.set_hook(addr, fn);
        if (ok) {
            h.ChainAt(addr).port = fn;
        }
        return ok;
    }

    bool AddLink(u32 addr, Link link) {
        Chain& chain = ChainAt(addr);
        if (chain.slot < 0) {
            if (used_slots_ >= SLOTS || !info_.set_hook(addr, SlotFns()[used_slots_])) {
                return false;
            }
            chain.slot = static_cast<int>(used_slots_);
            slots_[used_slots_++] = &chain;
        }
        chain.links.insert(chain.links.begin(), link);   // later mods run first
        return true;
    }

    // ── loading ───────────────────────────────────────────────────────────────

    void LoadOne(const PluginSpec& spec, std::vector<std::string>& log) {
        log_ = &log;
        if (!loader_.open) {
            log.push_back(spec.mod + ": native plugins can't be loaded here");
            return;
        }
        std::string error;
        void* lib = loader_.open(spec.library.c_str(), error);
        if (!lib) {
            log.push_back(spec.mod + ": its plugin " + spec.library + " can't be loaded (" + error +
                          "); the mod's plugin is off");
            return;
        }
        auto init = reinterpret_cast<MH4UPluginInit>(loader_.symbol(lib, MH4U_PLUGIN_INIT_SYMBOL));
        if (!init) {
            log.push_back(spec.mod + ": " + spec.library + " has no " + MH4U_PLUGIN_INIT_SYMBOL +
                          "; the mod's plugin is off");
            loader_.close(lib);
            return;
        }
        auto p = std::make_unique<Plugin>();
        p->spec = spec;
        p->library = lib;
        MH4UPluginHost& t = p->host;
        t = {};
        t.abi = MH4U_PLUGIN_ABI;
        t.size = sizeof(MH4UPluginHost);
        t.mod_name = p->spec.mod.c_str();
        t.mod_dir = p->spec.dir.c_str();
        t.program_id = info_.title_id;
        t.hook = &ApiHook;
        t.call_original = &ApiCallOriginal;
        t.skip_original = &ApiSkipOriginal;
        t.reg = &ApiReg;
        t.set_reg = &ApiSetReg;
        t.read32 = &ApiRead32;
        t.read16 = &ApiRead16;
        t.read8 = &ApiRead8;
        t.write32 = &ApiWrite32;
        t.write16 = &ApiWrite16;
        t.write8 = &ApiWrite8;
        t.guest_pointer = &ApiGuestPointer;
        t.log = &ApiLog;
        t.config = &ApiConfig;
        t.on_frame = &ApiOnFrame;
        t.alloc = &ApiAlloc;
        t.free = &ApiFree;
        t.call = &ApiCall;
        // Hooks a failed init asked for are taken back: remember the chains as they were.
        std::map<u32, size_t> before;
        for (auto& [addr, chain] : chains_) {
            before[addr] = chain->links.size();
        }
        const size_t frames_before = frame_fns_.size();
        const bool frame_hooked_before = frame_hooked_;
        p->loading = true;
        Plugin* raw = p.get();
        plugins_.push_back(std::move(p));
        const int ok = init(&raw->host, MH4U_PLUGIN_ABI);
        raw->loading = false;
        if (!ok) {
            for (auto& [addr, chain] : chains_) {
                const size_t had = before.count(addr) ? before[addr] : 0;
                const size_t added = chain->links.size() - had;
                chain->links.erase(chain->links.begin(), chain->links.begin() + added);
            }
            frame_fns_.resize(frames_before);
            frame_hooked_ = frame_hooked_before;
            log.push_back(spec.mod + ": its plugin didn't start (built for another version of the "
                                     "port, or it refused); the mod's plugin is off");
            loader_.close(lib);
            plugins_.pop_back();
            return;
        }
        log.push_back(spec.mod + ": plugin loaded (" + spec.library + ")");
    }

    void Say(const Plugin* p, int level, const std::string& text) {
        const std::string line = p->spec.mod + ": " + text;
        if (log_) {
            log_->push_back(line);
        } else if (sink_) {
            sink_(level, line);
        }
    }

    // ── the host table ────────────────────────────────────────────────────────

    static int ApiHook(const MH4UPluginHost* self, const char* name, MH4UHookFn fn, void* user) {
        PluginHost& h = Get();
        Plugin* p = Self(self);
        if (!p->loading || !fn || !name) {
            h.Say(p, MH4U_LOG_ERROR, "hook() is for init only");
            return 0;
        }
        const u32 addr = Port::Hooks::FindHookPoint(h.info_, name, 0);
        if (!addr || !h.info_.set_hook) {
            h.Say(p, MH4U_LOG_WARNING, std::string("no hook point for ") + name +
                                           " in the code library (build it again with this mod on)");
            return 0;
        }
        if (!h.AddLink(addr, {fn, user})) {
            h.Say(p, MH4U_LOG_ERROR, std::string("can't hook ") + name + " (too many hooked functions)");
            return 0;
        }
        return 1;
    }

    static void ApiCallOriginal(MH4UCall* call) {
        if (call && call->chain) {
            Run(static_cast<Chain*>(call->chain), call->ctx, call->original, call->next);
        }
    }

    static void ApiSkipOriginal(MH4UCall* call) {
        if (call && call->chain) {
            rc_hook_return(call->ctx);
        }
    }

    static u32 ApiReg(MH4UCall* call, unsigned n) {
        return n < 16 ? call->ctx->r[n] : 0;
    }
    static void ApiSetReg(MH4UCall* call, unsigned n, u32 v) {
        if (n < 16) {
            call->ctx->r[n] = v;
        }
    }
    static u32 ApiRead32(MH4UCall* c, u32 a) { return rd32(c->ctx, a); }
    static u32 ApiRead16(MH4UCall* c, u32 a) { return rd16(c->ctx, a); }
    static u32 ApiRead8(MH4UCall* c, u32 a) { return rd8(c->ctx, a); }
    static void ApiWrite32(MH4UCall* c, u32 a, u32 v) { wr32(c->ctx, a, v); }
    static void ApiWrite16(MH4UCall* c, u32 a, u32 v) { wr16(c->ctx, a, v); }
    static void ApiWrite8(MH4UCall* c, u32 a, u32 v) { wr8(c->ctx, a, v); }

    static void* ApiGuestPointer(MH4UCall* c, u32 addr, u32 size) {
        if (size == 0 || addr + size < addr) {
            return nullptr;
        }
#ifdef RC_PAGED
        if ((addr & 0xFFF) + size > 0x1000 || !c->ctx->pages || !c->ctx->pages[addr >> 12]) {
            return nullptr;
        }
        return c->ctx->pages[addr >> 12] + (addr & 0xFFF);
#else
        return c->ctx->mem ? c->ctx->mem + addr : nullptr;
#endif
    }

    static void ApiLog(const MH4UPluginHost* self, int level, const char* message) {
        Get().Say(Self(self), level, message ? message : "");
    }

    static const char* ApiConfig(const MH4UPluginHost* self, const char* key) {
        const Plugin* p = Self(self);
        auto it = key ? p->spec.config.find(key) : p->spec.config.end();
        return it == p->spec.config.end() ? nullptr : it->second.c_str();
    }

    static void FrameLink(MH4UCall* call, void*) {
        PluginHost& h = Get();
        MH4UCall frame{call->ctx, nullptr, 0, nullptr};
        for (const Link& f : h.frame_fns_) {
            reinterpret_cast<MH4UFrameFn>(f.fn)(&frame, f.user);
        }
        ApiCallOriginal(call);
    }

    static int ApiOnFrame(const MH4UPluginHost* self, MH4UFrameFn fn, void* user) {
        PluginHost& h = Get();
        Plugin* p = Self(self);
        if (!p->loading || !fn) {
            h.Say(p, MH4U_LOG_ERROR, "on_frame() is for init only");
            return 0;
        }
        if (!h.frame_hooked_) {
            const u32 addr = Port::Hooks::FindHookPoint(h.info_, FRAME_HOOK, 0);
            if (!addr || !h.info_.set_hook || !h.AddLink(addr, {&FrameLink, nullptr})) {
                h.Say(p, MH4U_LOG_WARNING, std::string("no hook point for ") + FRAME_HOOK +
                                               " in the code library: no per-frame calls");
                return 0;
            }
            h.frame_hooked_ = true;
        }
        h.frame_fns_.push_back({reinterpret_cast<MH4UHookFn>(fn), user});
        return 1;
    }

    // ── guest memory ──────────────────────────────────────────────────────────

    /// Runs the guest function at `target` with r0-r2 = args, and returns its r0. Everything
    /// the guest's caller can see (core and VFP registers, flags, the fall-through return)
    /// is put back as it was; the call uses the guest's stack below its current sp.
    u32 CallGuest(RCtx* ctx, u32 target, u32 a0, u32 a1, u32 a2) {
        u32 regs[16];
        std::memcpy(regs, ctx->r, sizeof regs);
        const u32 flags[7] = {ctx->fn, ctx->fz, ctx->fc, ctx->fv, ctx->fq, ctx->ge, ctx->fpscr};
        auto vfp = ctx->f;
        const u32 expect_next = ctx->expect_next;
        ctx->expect_next = 0;
        ctx->r[0] = a0;
        ctx->r[1] = a1;
        ctx->r[2] = a2;
        ctx->r[14] = regs[14];   // a code address of the game's (only the interpreter reads it)
        guest_call_(ctx, target);
        const u32 result = ctx->r[0];
        std::memcpy(ctx->r, regs, sizeof regs);
        ctx->fn = flags[0];
        ctx->fz = flags[1];
        ctx->fc = flags[2];
        ctx->fv = flags[3];
        ctx->fq = flags[4];
        ctx->ge = flags[5];
        ctx->fpscr = flags[6];
        ctx->f = vfp;
        ctx->expect_next = expect_next;
        return result;
    }

    /// The default allocator and its virtual function at `vcall`, or false (logged once).
    bool HeapFunction(RCtx* ctx, u32 vcall, u32& allocator, u32& fn) {
        allocator = heap_table_ && guest_call_ ? rd32(ctx, heap_table_) : 0;
        const u32 vtable = allocator ? rd32(ctx, allocator) : 0;
        fn = vtable ? rd32(ctx, vtable + vcall) : 0;
        if (fn) {
            return true;
        }
        if (!heap_warned_) {
            heap_warned_ = true;
            const std::string why = !heap_table_ || !guest_call_
                                        ? "the port doesn't know this game's heap"
                                        : "the game's heap isn't set up yet";
            if (sink_) {
                sink_(MH4U_LOG_WARNING, "host: no guest memory for plugins (" + why + ")");
            }
        }
        return false;
    }

    static u32 ApiAlloc(MH4UCall* call, u32 size, u32 align) {
        PluginHost& h = Get();
        if (!call || !call->ctx || size == 0) {
            return 0;
        }
        if (align == 0) {
            align = 16;
        }
        if (align & (align - 1)) {
            return 0;
        }
        u32 allocator, fn;
        if (!h.HeapFunction(call->ctx, ALLOC_VCALL, allocator, fn)) {
            return 0;
        }
        return h.CallGuest(call->ctx, fn, allocator, size, align);
    }

    static void ApiFree(MH4UCall* call, u32 addr) {
        PluginHost& h = Get();
        u32 allocator, fn;
        if (call && call->ctx && addr && h.HeapFunction(call->ctx, FREE_VCALL, allocator, fn)) {
            h.CallGuest(call->ctx, fn, allocator, addr, 0);
        }
    }

    static u32 ApiCall(MH4UCall* call, u32 addr, u32 a0, u32 a1, u32 a2) {
        PluginHost& h = Get();
        if (!call || !call->ctx || !addr || !h.guest_call_) {
            return 0;
        }
        return h.CallGuest(call->ctx, addr, a0, a1, a2);
    }

    RCodeInfo info_{};
    Loader loader_{};
    std::map<u32, std::unique_ptr<Chain>> chains_;
    std::deque<std::unique_ptr<Plugin>> plugins_;
    std::array<Chain*, SLOTS> slots_{};
    size_t used_slots_ = 0;
    std::vector<Link> frame_fns_;
    bool frame_hooked_ = false;
    std::vector<std::string>* log_ = nullptr;
    void (*sink_)(int, const std::string&) = nullptr;
    u32 heap_table_ = 0;
    GuestCall guest_call_ = nullptr;
    bool heap_warned_ = false;
};

/// Reads <program id>.plugins.tsv (tools/mod_hooks.py writes it): `plugin<TAB>mod<TAB>library
/// <TAB>mod folder` and `config<TAB>mod<TAB>key<TAB>value` lines, in mod order.
inline std::vector<PluginSpec> ParsePluginList(const std::string& text) {
    std::vector<PluginSpec> specs;
    size_t pos = 0;
    while (pos < text.size()) {
        size_t end = text.find('\n', pos);
        if (end == std::string::npos) {
            end = text.size();
        }
        std::string line = text.substr(pos, end - pos);
        pos = end + 1;
        if (!line.empty() && line.back() == '\r') {
            line.pop_back();
        }
        if (line.empty() || line[0] == '#') {
            continue;
        }
        std::vector<std::string> f;
        size_t s = 0;
        for (size_t t; (t = line.find('\t', s)) != std::string::npos; s = t + 1) {
            f.push_back(line.substr(s, t - s));
        }
        f.push_back(line.substr(s));
        if (f[0] == "plugin" && f.size() >= 4) {
            specs.push_back({f[1], f[2], f[3], {}});
        } else if (f[0] == "config" && f.size() >= 4) {
            for (auto it = specs.rbegin(); it != specs.rend(); ++it) {
                if (it->mod == f[1]) {
                    it->config[f[2]] = f[3];
                    break;
                }
            }
        }
    }
    return specs;
}

} // namespace Port::Plugins
