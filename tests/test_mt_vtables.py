"""Tests for tools/mt_vtables.py on a hand-assembled synthetic ARM image (no game data)."""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import mt_dti
import mt_vtables as V
from test_mt_dti import CLASSES, bl, build_image, ldr_pc

BASE = 0x00100000
TEXT = 0x1000
RO = BASE + TEXT
MEM_END = BASE + 0x3000

GETTER = BASE + 0x200        # the allocator getter: never runs, the emulator replaces it
BASE_CTOR = BASE + 0x240
NEW_INSTANCE = BASE + 0x300
F1, F2, F3, F4 = BASE + 0x400, BASE + 0x404, BASE + 0x408, BASE + 0x40C
VT_BASE, VT_DERIVED = RO + 0x00, RO + 0x10
DTI = BASE + 0x2800


def build():
    w = {}
    w[GETTER] = 0xE12FFF1E                                       # bx lr
    # base constructor: ldr r1, =VT_BASE; str r1, [r0]; bx lr
    w[BASE_CTOR] = ldr_pc(1, BASE_CTOR, BASE_CTOR + 0x0C)
    w[BASE_CTOR + 4] = 0xE5801000
    w[BASE_CTOR + 8] = 0xE12FFF1E
    w[BASE_CTOR + 0x0C] = VT_BASE
    # newInstance: allocator = getter(); obj = allocator->vt[9](0x40); base ctor; own vtable
    n = NEW_INSTANCE
    code = [0xE92D4010,                  # push {r4, lr}
            bl(n + 4, GETTER),
            0xE5901000,                  # ldr r1, [r0]
            0xE591C024,                  # ldr ip, [r1, #0x24]
            0xE3A01040,                  # mov r1, #0x40
            0xE12FFF3C,                  # blx ip
            0xE1A04000,                  # mov r4, r0
            bl(n + 0x1C, BASE_CTOR),
            ldr_pc(1, n + 0x20, n + 0x34),
            0xE5841000,                  # str r1, [r4]
            0xE1A00004,                  # mov r0, r4
            0xE8BD8010,                  # pop {r4, pc}
            0xE12FFF1E,
            VT_DERIVED]
    for i, x in enumerate(code):
        w[n + 4 * i] = x
    for f in (F1, F2, F3, F4):
        w[f] = 0xE12FFF1E
    # vtables in .rodata: an empty slot in each, then a word that isn't code
    for i, x in enumerate([F1, 0, F2]):
        w[VT_BASE + 4 * i] = x
    for i, x in enumerate([F1, 0, F3, F4, 0, 0x12345678]):
        w[VT_DERIVED + 4 * i] = x
    data = bytearray(0x2000)
    for a, x in w.items():
        struct.pack_into("<I", data, a - BASE, x)
    data = bytes(data)
    img = mt_dti.Image(data, BASE, TEXT, MEM_END)
    mem = V.Mem()
    mem.add(BASE, data, [(BASE, BASE + TEXT)], [(RO, RO + 0x1000)])
    return img, mem


def test_detects_the_allocator_getter():
    _, mem = build()
    assert V.first_call(mem, NEW_INSTANCE) == GETTER
    assert V.detect_getter(mem, [NEW_INSTANCE]) == GETTER


def test_emulation_records_the_constructor_chain():
    img, mem = build()
    out = V.emulate_new_instances(img, mem, {NEW_INSTANCE: DTI}, GETTER)
    assert out[NEW_INSTANCE] == [VT_BASE, VT_DERIVED]


def test_static_fallback_reads_the_last_vtable_store():
    _, mem = build()
    assert V.static_vtable(mem, NEW_INSTANCE) == VT_DERIVED


def test_measure_counts_slots_to_the_next_vtable():
    _, mem = build()
    sizes = V.measure(mem, [VT_BASE, VT_DERIVED])
    assert sizes == {VT_BASE: 3, VT_DERIVED: 4}          # trailing zero dropped
    assert V.slots(mem, VT_DERIVED, 4) == [F1, 0, F3, F4]


def classes(**chains):
    """Hierarchy Root < Mid < {A, B}; A and B emulated with the given chains."""
    c = {"Root": V.ClassVt("Root", 1), "Mid": V.ClassVt("Mid", 2, parent=1),
         "A": V.ClassVt("A", 3, parent=2), "B": V.ClassVt("B", 4, parent=2)}
    for name, chain in chains.items():
        c[name].chain, c[name].vtable, c[name].how = chain, chain[-1], "emulated"
    return c


def test_abstract_classes_get_vtables_from_their_subclasses_chains():
    c = classes(A=[10, 20, 30], B=[10, 20, 40])
    assert V.from_chains(c) == 2
    assert (c["Mid"].vtable, c["Root"].vtable) == (20, 10)
    assert c["Mid"].how == "chains"


def test_chains_skip_vtables_a_subclass_owns():
    # B's vtable (20) was found another way: Mid passes over it to the next one up
    c = classes(A=[10, 20, 30])
    c["B"].vtable, c["B"].how = 20, "static"
    V.from_chains(c)
    assert c["Mid"].vtable == 10 and c["Root"].vtable is None


def test_tsv_round_trip(tmp_path):
    c = classes(A=[10, 20, 30])
    c["A"].size, c["A"].slots = 2, [0x100400, 0]
    p = tmp_path / "vt.tsv"
    V.write_tsv(c, str(p))
    back = V.read_tsv(str(p))
    assert back["A"].chain == [10, 20, 30] and back["A"].slots == [0x100400, 0]
    assert back["A"].parent == 2 and back["Root"].vtable is None


def test_dti_vtables_reads_each_dti_after_its_initialiser():
    out = V.dti_vtables(build_image())
    names = {name: (vt, parent) for name, vt, parent in out.values()}
    assert set(names) == {n for n, _, _ in CLASSES}
    assert names["MtObject"] == (0, None)              # the fake constructor leaves word 0 alone
    assert names["rTexture"][1] is not None
