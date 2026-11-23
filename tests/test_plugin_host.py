"""port/src/plugin_host.h: native plugins (include/mh4u_plugin.h) on a recompiled test program.

A synthetic program is recompiled with hook points (as tests/test_hooks.py does, through the
rh_set_hook harness); the plugin host is built into a small shim library; the sample plugin
(tools/plugin_sample/sample_plugin.c) is built twice, as two mods. Checked: chain order (the
last mod first, then the port's own hook, then the game's function), skipping the original,
per-frame calls with guest memory writes, a hook name the library lacks, an init that fails
(its hooks are taken back), the plugin list format, and guest memory from the game's heap
(alloc/free through an MtAllocator-shaped bump heap in the test program)."""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, HERE)

CXX = next((c for c in ("clang++", "c++", "g++") if shutil.which(c)), None)
CC = next((c for c in ("clang", "cc", "gcc") if shutil.which(c)), None)
pytestmark = pytest.mark.skipif(not (CXX and CC and shutil.which("clang") and shutil.which("ld.lld")
                                     and sys.platform.startswith("linux")),
                                reason="needs clang, ld.lld and a C++ compiler on Linux")

SHIM = r"""
#include <dlfcn.h>
#include <string>
#include <vector>
#include "plugin_host.h"

using namespace Port::Plugins;
static std::vector<u32> g_addrs;
static std::vector<std::string> g_names;
static std::vector<const char*> g_name_ptrs;
static std::vector<std::string> g_log;
static RCodeInfo g_port;

static void* Open(const char* path, std::string& error) {
    void* h = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (!h) error = dlerror();
    return h;
}
static void* Sym(void* lib, const char* name) { return dlsym(lib, name); }
static void Close(void* lib) { dlclose(lib); }
static void Sink(int, const std::string& line) { g_log.push_back(line); }

extern "C" {
// hook points: "addr name" pairs, sorted by address, as a code library lists them
void ph_point(u32 addr, const char* name) { g_addrs.push_back(addr); g_names.push_back(name); }
void* ph_begin(int (*set_hook)(u32, RHookFn), u64 title) {
    g_name_ptrs.clear();
    for (auto& n : g_names) g_name_ptrs.push_back(n.c_str());
    RCodeInfo info{};
    info.title_id = title;
    info.hook_addrs = g_addrs.data();
    info.hook_names = g_name_ptrs.data();
    info.hook_count = (u32)g_addrs.size();
    info.set_hook = set_hook;
    g_port = PluginHost::Get().Begin(info, Loader{Open, Sym, Close});
    PluginHost::Get().SetLog(Sink);
    g_log.clear();
    return (void*)g_port.set_hook;
}
int ph_load(const char* tsv) {
    auto lines = PluginHost::Get().Load(ParsePluginList(tsv));
    g_log.insert(g_log.end(), lines.begin(), lines.end());
    return (int)PluginHost::Get().PluginCount();
}
void ph_set_heap(u32 table, void (*call)(RCtx*, u32)) { PluginHost::Get().SetGuestHeap(table, call); }
int ph_log_count(void) { return (int)g_log.size(); }
const char* ph_log_line(int i) { return g_log[i].c_str(); }
void ph_reset(void) { PluginHost::Get().Reset(); g_addrs.clear(); g_names.clear(); }
}
"""


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    from test_hooks import _build

    work = tmp_path_factory.mktemp("plugins")
    res, lib, code, names, out = _build(work, ["add1", "thumb_sub", "screen_rows"])
    shim_src = work / "shim.cpp"
    shim_src.write_text(SHIM)
    shim = work / "shim.so"
    subprocess.run([CXX, "-std=c++17", "-shared", "-fPIC", "-I", os.path.join(ROOT, "port", "src"),
                    "-I", os.path.join(ROOT, "tools", "recomp", "runtime"), str(shim_src), "-o", str(shim), "-ldl"],
                   check=True)
    plugin = work / "sample.so"
    subprocess.run([CC, "-shared", "-fPIC", "-Wall", "-Werror", "-I", os.path.join(ROOT, "include"),
                    os.path.join(ROOT, "tools", "plugin_sample", "sample_plugin.c"), "-o", str(plugin)], check=True)
    copies = {}
    for name in ("a", "b", "c"):   # one library per mod: its globals are its own
        copies[name] = work / f"plugin_{name}.so"
        shutil.copy(plugin, copies[name])
    return {"lib": lib, "code": code, "names": names, "shim": shim, "plugins": copies}


@pytest.fixture
def env(built):
    from recomp.gametest import STACK_SIZE, STACK_TOP
    from recomp.harness.machines import RET_TRAP, ST_RETURN, CRCtx, NativeMachine, Region, State

    code, names = built["code"], built["names"]
    size = (len(code) + 0x10000 + 0xFFF) & ~0xFFF
    m = NativeMachine(built["lib"], [Region(0x00100000, size, True, code.ljust(size, b"\0")),
                                     Region(STACK_TOP - STACK_SIZE, STACK_SIZE, True, bytes(STACK_SIZE))])
    m.lib.rh_set_hook.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    m.lib.rh_set_hook.restype = ctypes.c_int
    shim = ctypes.CDLL(str(built["shim"]))
    shim.ph_point.argtypes = [ctypes.c_uint32, ctypes.c_char_p]
    shim.ph_begin.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
    shim.ph_begin.restype = ctypes.c_void_p
    shim.ph_load.argtypes = [ctypes.c_char_p]
    shim.ph_log_line.restype = ctypes.c_char_p
    shim.ph_set_heap.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    shim.ph_reset()
    points = sorted([(names["add1"] & ~1, "add1"), (names["thumb_sub"] & ~1, "thumb_sub"),
                     (names["screen_rows"] & ~1, "sMhMain::frame")])
    for addr, name in points:
        shim.ph_point(addr, name.encode())
    set_hook = ctypes.cast(m.lib.rh_set_hook, ctypes.c_void_p).value
    hook_t = ctypes.CFUNCTYPE(None, ctypes.POINTER(CRCtx), ctypes.c_void_p)
    func_t = ctypes.CFUNCTYPE(None, ctypes.POINTER(CRCtx))
    keep = []

    class Env:
        stack_top = STACK_TOP

        def begin(self):
            port = shim.ph_begin(set_hook, 0x0004000000126300)
            return ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_uint32, ctypes.c_void_p)(port)

        def port_hook(self, port_set, fn_name, add):
            @hook_t
            def wrap(ctx, original):
                func_t(original)(ctx)
                ctx.contents.r[0] += add
            keep.append(wrap)
            return port_set(names[fn_name] & ~1, ctypes.cast(wrap, ctypes.c_void_p))

        def load(self, *mods):
            lines = []
            for mod, plugin, config in mods:
                path = built["plugins"].get(plugin, plugin)
                lines.append(f"plugin\t{mod}\t{path}\t/mods/{mod}")
                lines += [f"config\t{mod}\t{k}\t{v}" for k, v in config.items()]
            return shim.ph_load("\n".join(lines).encode() + b"\n")

        def log(self):
            return [shim.ph_log_line(i).decode() for i in range(shim.ph_log_count())]

        def call(self, fn, *args):
            st = State()
            for i, a in enumerate(args):
                st.r[i] = a & 0xFFFFFFFF
            st.r[13], st.r[14] = STACK_TOP - 0x100, RET_TRAP
            r = m.run(names[fn] & ~1, bool(names[fn] & 1), st)
            assert r.status == ST_RETURN, r
            return r.state.r[0]

        def read32(self, addr):
            return int.from_bytes(m.read(addr, 4), "little")

        def write32(self, addr, value):
            m.write(addr, (value & 0xFFFFFFFF).to_bytes(4, "little"))

        def heap(self, arena_size=0x1000):
            """An MtAllocator-shaped bump heap at the end of the code region, its table entry
            given to the host (call after begin, which forgets it). Returns the heap's address
            and its arena's start: the heap's fields are vtable, next, end, frees, last_freed."""
            top = 0x00100000 + size
            table, heap, vtable = top - 0x100, top - 0xC0, top - 0x80
            arena = top - 0x100 - arena_size
            self.write32(table, heap)
            for i, v in enumerate([vtable, arena, arena + arena_size, 0, 0]):
                self.write32(heap + 4 * i, v)
            self.write32(vtable + 0x20, names["heap_alloc"])
            self.write32(vtable + 0x38, names["heap_free"])
            shim.ph_set_heap(table, ctypes.cast(m.lib.rc_call, ctypes.c_void_p).value)
            return heap, arena

    yield Env()
    shim.ph_reset()


def test_no_plugins_keeps_port_hooks(env):
    port = env.begin()
    assert env.port_hook(port, "add1", 1000) == 1
    assert env.load() == 0
    assert env.call("add1", 5) == 1006


def test_chain_order(env):
    port = env.begin()
    env.port_hook(port, "add1", 1000)
    n = env.load(("Mod A", "a", {"hook": "add1", "op": "add", "value": "100"}),
                 ("Mod B", "b", {"hook": "add1", "op": "mul", "value": "2"}))
    assert n == 2, env.log()
    # game 6, port +1000, then Mod A (earlier) +100, then Mod B (last, outermost) *2
    assert env.call("add1", 5) == (6 + 1000 + 100) * 2
    assert env.call("twice_add1", 5) == (6 + 1000 + 100) * 2 * 2   # called from game code
    assert any("Mod A: plugin loaded" in line for line in env.log())


def test_port_hook_set_after_plugins(env):
    port = env.begin()
    env.load(("Mod A", "a", {"hook": "add1", "value": "100"}))
    env.port_hook(port, "add1", 1000)          # the port's hook joins the chain's end
    assert env.call("add1", 5) == 6 + 1000 + 100


def test_skip_original(env):
    port = env.begin()
    env.port_hook(port, "add1", 1000)
    env.load(("Mod A", "a", {"hook": "add1", "value": "100"}),
             ("Mod B", "b", {"hook": "add1", "skip": "1", "value": "77"}))
    assert env.call("add1", 5) == 77           # Mod B returns at once: nothing below it runs
    assert env.call("twice_add1", 5) == 154


def test_thumb_hook_point(env):
    env.begin()
    env.load(("Mod A", "a", {"hook": "thumb_sub", "value": "100"}))
    assert env.call("use_thumb", 10) == (6 + 100) * 3


def test_frame_calls_write_guest_memory(env):
    counter = env.stack_top - 0x800
    env.begin()
    env.load(("Mod A", "a", {"hook": "add1", "value": "1", "frames_at": hex(counter)}),
             ("Mod B", "b", {"hook": "add1", "value": "1", "frames_at": hex(counter + 4)}))
    for _ in range(3):
        assert env.call("screen_rows") == 400  # the frame hook point runs the game's function too
    assert env.read32(counter) == 3 and env.read32(counter + 4) == 3


def test_missing_hook_point(env):
    env.begin()
    assert env.load(("Mod A", "a", {"hook": "nMissing::function", "value": "1"})) == 1
    log = env.log()
    assert any("no hook point for nMissing::function" in line and line.startswith("Mod A:") for line in log), log
    assert env.call("add1", 5) == 6


def test_failed_init_takes_hooks_back(env):
    counter = env.stack_top - 0x800
    env.begin()
    n = env.load(("Mod A", "a", {"hook": "add1", "value": "100"}),
                 ("Mod B", "b", {"hook": "add1", "value": "5", "fail": "1", "frames_at": hex(counter)}),
                 ("Mod C", "c", {"hook": "add1", "op": "mul", "value": "3"}))
    assert n == 2
    assert any("Mod B: its plugin didn't start" in line for line in env.log())
    assert env.call("add1", 5) == (6 + 100) * 3
    env.call("screen_rows")
    assert env.read32(counter) == 0


def test_bad_library(env):
    env.begin()
    n = env.load(("Mod X", "/nonexistent/plugin.so", {"hook": "add1"}),
                 ("Mod A", "a", {"hook": "add1", "value": "100"}))
    assert n == 1
    assert any(line.startswith("Mod X: its plugin /nonexistent/plugin.so can't be loaded") for line in env.log())
    assert env.call("add1", 5) == 106


def test_reset_restores_port_hooks(env):
    port = env.begin()
    env.port_hook(port, "add1", 1000)
    env.load(("Mod A", "a", {"hook": "add1", "value": "100"}))
    assert env.call("add1", 5) == 1106
    port = env.begin()                         # a new library: the old chain is gone
    assert env.call("add1", 5) == 1006         # the port's hook was put back as it was


def test_list_written_by_mod_hooks(env, built, tmp_path):
    """The plugin list tools/mod_hooks.py writes is the one the host reads (config.ini wins)."""
    import mod_hooks

    mod_dir = tmp_path / "Mod A"
    mod_dir.mkdir()
    (mod_dir / "config.ini").write_text("value = 300\n")
    m = mod_hooks.ModHooks("Mod A", str(mod_dir), [{"name": "add1"}], {"linux": "x.so"},
                           {"hook": "add1", "value": "100"})
    text = mod_hooks.plugin_list_text([(m, str(built["plugins"]["a"]))])
    import ctypes as c
    shim = c.CDLL(str(built["shim"]))
    shim.ph_load.argtypes = [c.c_char_p]
    env.begin()
    assert shim.ph_load(text.encode()) == 1
    assert env.call("add1", 5) == 306


def test_alloc_frame_counter_on_the_game_heap(env):
    env.begin()
    heap, arena = env.heap()
    env.load(("Mod A", "a", {"hook": "add1", "value": "1", "frames_at": "alloc"}))
    for _ in range(3):
        assert env.call("screen_rows") == 400  # the game's registers are back after the calls
    # the 64-byte scratch block came first (and was freed), then the 4-byte counter
    assert env.read32(heap + 12) == 1 and env.read32(heap + 16) == arena
    counter = arena + 64
    assert env.read32(heap + 4) == counter + 4
    assert env.read32(counter) == 3
    assert any(f"Mod A: sample plugin: frame counter at 0x{counter:08x}" in line for line in env.log()), env.log()


def test_alloc_and_free_inside_a_hook_keep_registers(env):
    port = env.begin()
    env.port_hook(port, "add1", 1000)
    heap, arena = env.heap()
    env.load(("Mod A", "a", {"hook": "add1", "value": "100", "alloc_in_hook": "1"}))
    assert env.call("add1", 5) == 1106         # r0 (the argument) survived the allocation
    assert env.call("twice_add1", 5) == 2212   # and so did the game caller's registers
    assert env.read32(heap + 12) == 2          # each run freed its block
    assert env.read32(heap + 16) == arena + 16  # 8 bytes at 16-byte alignment (align 0)


def test_alloc_full_heap_returns_zero(env):
    env.begin()
    heap, _ = env.heap(arena_size=32)          # room for the scratch block? no: 64 > 32
    env.load(("Mod A", "a", {"hook": "add1", "frames_at": "alloc"}))
    env.call("screen_rows")
    assert env.read32(heap + 12) == 0          # free(0) doesn't reach the game
    assert env.read32(heap + 4) == env.read32(heap + 8) - 32 + 4   # the counter still fits
    assert any("frame counter at" in line for line in env.log())


def test_alloc_without_a_known_heap(env):
    env.begin()                                # no heap: another game, or a test without one
    env.load(("Mod A", "a", {"hook": "add1", "value": "1", "frames_at": "alloc"}))
    env.call("screen_rows")
    env.call("screen_rows")
    log = env.log()
    assert any("sample plugin: no guest memory for the frame counter" in line for line in log), log
    assert sum("no guest memory for plugins" in line for line in log) == 1, log   # said once
    assert env.call("add1", 5) == 7
