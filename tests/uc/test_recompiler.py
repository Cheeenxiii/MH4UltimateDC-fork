"""The fork's recompiler fixes: each one recovers code the recompile would otherwise get wrong."""
from __future__ import annotations

import os
import random
import shutil
import struct
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "..", "..", "tools")
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(HERE, ".."))          # upstream's test helpers

import recompile  # noqa: E402
from recomp.analysis import Analyzer, Image  # noqa: E402

BASE = 0x00100000
LLVM = ["clang", "ld.lld", "llvm-objcopy", "llvm-readelf"]
needs_llvm = pytest.mark.skipif(any(shutil.which(t) is None for t in LLVM), reason="needs the LLVM toolchain")


def test_position_independent_callback_becomes_an_entry_point():
    # setup: ldr r1, =off; add r1, pc; str r1, [r0, #12]; bx lr  (no word holds the callback's address)
    code = bytearray(0x40)
    setup, callback = BASE, BASE + 0x10
    struct.pack_into("<4H", code, 0, 0x4901, 0x4479, 0x60C1, 0x4770)
    struct.pack_into("<I", code, 8, (callback + 1 - (setup + 6)) & 0xFFFFFFFF)
    struct.pack_into("<2H", code, 0x10, 0x6900, 0x4770)                      # callback: ldr r0, [r0, #16]; bx lr
    img = Image(bytes(code), BASE, 0x20)
    an = Analyzer(img)
    first = an.analyze_all({setup: "thumb"})
    assert recompile.data_pointer_closure(img, an, [], first) == {callback: "thumb"}


def test_arm_thunk_into_thumb_code_reaches_the_thumb_function():
    # add r0, #4; add ip, pc, #5; bx ip  ->  Thumb code at thunk + 0x10
    code = bytearray(0x40)
    struct.pack_into("<3I", code, 0, 0xE2800004, 0xE28FC005, 0xE12FFF1C)
    struct.pack_into("<2H", code, 0x10, 0x3001, 0x4770)                      # adds r0, #1; bx lr
    first = Analyzer(Image(bytes(code), BASE, 0x20)).analyze_all({BASE: "arm"})
    assert first.get(BASE + 0x10) is not None and first[BASE + 0x10].mode == "thumb"


def test_functions_found_through_data_are_scanned_for_more_code_addresses():
    # a vtable holds f; f loads g's address from its literal pool and stores it
    code = bytearray(0x200)
    a, f, g = BASE, BASE + 0x10, BASE + 0x20
    struct.pack_into("<I", code, 0, 0xE12FFF1E)
    struct.pack_into("<4I", code, 0x10, 0xE59F1004, 0xE5801000, 0xE12FFF1E, g)
    struct.pack_into("<2I", code, 0x20, 0xE3A00000, 0xE12FFF1E)
    struct.pack_into("<I", code, 0x100, f)
    img = Image(bytes(code), BASE, 0x100)
    an = Analyzer(img)
    found = recompile.data_pointer_closure(img, an, [(BASE + 0x100, 4)], an.analyze_all({a: "arm"}))
    assert found == {f: "arm", g: "arm"}


ORDER_PROGRAM = r"""
import sys, struct
sys.path.insert(0, sys.argv[1])
from recomp.analysis import Analyzer, Image
BASE = 0x00100000
words = {}
def put(at, *ws):
    for i, w in enumerate(ws):
        words[at + 4 * i] = w
def bl(at, t): return 0xEB000000 | (((t - (at + 8)) >> 2) & 0xFFFFFF)
def b(at, t): return 0xEA000000 | (((t - (at + 8)) >> 2) & 0xFFFFFF)
# F calls X0..X7 and Y0..Y7; Xi calls Zi; Yi branches to Zi. Whether Yi's branch is a
# tail call or inlined code depends on which of Xi, Yi is analysed first.
F = BASE
put(F, 0xE92D4010)
at = F + 4
for i in range(8):
    x, y, z = BASE + 0x1000 + 0x100 * i, BASE + 0x1040 + 0x100 * i, BASE + 0x1080 + 0x100 * i
    put(at, bl(at, x)); put(at + 4, bl(at + 4, y)); at += 8
    put(x, 0xE92D4010, bl(x + 4, z), 0xE8BD8010)
    put(y, b(y, z))
    put(z, 0xE2800001, 0xE12FFF1E)
put(at, 0xE8BD8010)
code = bytearray(0x2000)
for a, w in words.items():
    struct.pack_into("<I", code, a - BASE, w)
funcs = Analyzer(Image(bytes(code), BASE, 0x2000)).analyze_all({F: "arm"})
print(sorted((a, sorted(f.insns)) for a, f in funcs.items()))
"""


def test_analysis_gives_the_same_functions_whatever_the_string_hash_seed():
    outputs = set()
    for seed in ("0", "1", "2", "3"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        res = subprocess.run([sys.executable, "-c", ORDER_PROGRAM, TOOLS], env=env, capture_output=True,
                             text=True, check=True)
        outputs.add(res.stdout)
    assert len(outputs) == 1


SWITCH8 = r"""
    .syntax unified
    .arm
    .text
    .global switch8
    .type switch8, %function
switch8:
    ldrb    ip, [lr, #-1]
    cmp     r3, ip
    ldrbhs  r3, [lr, ip]
    ldrblo  r3, [lr, r3]
    add     ip, lr, r3, lsl #1
    bx      ip

    .thumb
    .global sw_caller
    .type sw_caller, %function
    .thumb_func
sw_caller:
    push    {r4, lr}
    adds    r4, r1, #0
    movs    r3, r0
    blx     switch8
tbl:
    .byte   3
    .byte   (c0 - tbl) / 2, (c1 - tbl) / 2, (c2 - tbl) / 2, (cd - tbl) / 2
    .balign 2
c0: adds    r0, r4, #5
    pop     {r4, pc}
c1: subs    r0, r4, #7
    pop     {r4, pc}
c2: lsls    r0, r4, #2
    pop     {r4, pc}
cd: mvns    r0, r4
    pop     {r4, pc}
"""


@needs_llvm
def test_rvct_thumb_switch_helper_runs_like_the_original(tmp_path):
    from test_recomp import _recompile_and_compare
    res, _, verdicts = _recompile_and_compare(tmp_path, {"s.S": SWITCH8}, cases=48)
    symbols = subprocess.run(["llvm-readelf", "-s", str(tmp_path / "p.elf")], capture_output=True, text=True,
                             check=True).stdout.splitlines()
    caller = next(int(p[1], 16) for p in (line.split() for line in symbols) if len(p) >= 8 and p[7] == "sw_caller")
    assert len(next(iter(res["funcs"][caller & ~1].mret_calls.values()))) == 4
    assert verdicts[caller & ~1][0] == "pass", verdicts[caller & ~1]


@needs_llvm
def test_indirect_call_to_address_one_goes_to_rc_call(tmp_path):
    from recomp import build as rbuild
    from recomp.gametest import BUF_BASE, BUF_SIZE, STACK_SIZE, STACK_TOP, TLS, Tester, random_state
    from recomp.harness.machines import ST_NOFUNC, Region
    words = [0xE92D4010, 0xE12FFF30, 0xE8BD8010]                             # push {r4, lr}; blx r0; pop {r4, pc}
    code = struct.pack(f"<{len(words)}I", *words).ljust(0x1000, b"\0")
    out = tmp_path / "recomp"
    recompile.recompile(Image(code, BASE, 4 * len(words)), {BASE: "arm"}, str(out), log=lambda *a: None)
    lib = rbuild.build(str(out), 2, "O1", ["RC_CHECK_RETURNS"], "icall.so", [rbuild.HARNESS])
    size = 0x10000
    regions = [Region(BASE, size, True, code.ljust(size, b"\0")),
               Region(STACK_TOP - STACK_SIZE, STACK_SIZE, True, bytes(STACK_SIZE)),
               Region(BUF_BASE, BUF_SIZE, True, bytes(BUF_SIZE)),
               Region(TLS, 0x1000, True, bytes(0x1000))]
    state = random_state(random.Random(1))
    state.r[0] = 1
    result = Tester(lib, [], regions, seed=5).nat.run(BASE, False, state, budget=10000)
    assert (result.status, result.info0) == (ST_NOFUNC, 1), result
