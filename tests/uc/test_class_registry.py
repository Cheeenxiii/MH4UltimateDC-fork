"""mt_dti: one bad class initialiser must not corrupt the classes recovered after it."""
from __future__ import annotations

import os
import struct
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
sys.path.insert(0, os.path.join(HERE, ".."))          # upstream's synthetic-image helpers

pytest.importorskip("unicorn")
import mt_dti  # noqa: E402
from test_mt_dti import BASE, CLASSES, CTOR, DTI_AREA, MEM_END, adr, bl, ldr_pc, mov  # noqa: E402

POINTER = BASE + 0x900          # a writable word the constructor follows; it holds its own address


def image_with_a_bad_initialiser_first() -> mt_dti.Image:
    words, names = {}, {}
    ctor = [ldr_pc(12, CTOR, CTOR + 0x24), 0xE59CC000, 0xE59CC000,      # ip = **POINTER: faults if zeroed
            0xE5801004, 0xE5802008, 0xE580300C, 0xE580301C, 0xE12FFF1E]
    for i, w in enumerate(ctor):
        words[CTOR + 4 * i] = w
    words[CTOR + 0x24] = POINTER

    def initialiser(at, dti, name, parent, size, first):
        body = [0xE92D4010] + first                                      # push {r4, lr}
        here = at + 4 * len(body)
        body += [ldr_pc(0, here, at + 0x30), adr(1, here + 4, at + 0x38),
                 ldr_pc(2, here + 8, at + 0x34) if parent is not None else mov(2, 0), mov(3, size)]
        body += [bl(at + 4 * len(body), CTOR), 0xE8BD8010]               # bl ctor; pop {r4, pc}
        for i, w in enumerate(body):
            words[at + 4 * i] = w
        words[at + 0x30], words[at + 0x34] = dti, parent or 0
        names[at + 0x38] = name.encode() + b"\0"

    bad = BASE + 0x80                                                     # zeroes *POINTER, like a stray store
    initialiser(bad, DTI_AREA + 0x200, "cBad", None, 4, [mov(4, 0), ldr_pc(1, bad + 8, bad + 0x2C), 0xE5814000])
    words[bad + 0x2C] = POINTER
    for i, (name, parent, size) in enumerate(CLASSES):
        initialiser(BASE + 0x100 + i * 0x60, DTI_AREA + i * 0x20, name,
                    None if parent is None else DTI_AREA + parent * 0x20, size, [])
    code = bytearray(0x1000)
    for a, w in words.items():
        struct.pack_into("<I", code, a - BASE, w)
    for a, b in names.items():
        code[a - BASE:a - BASE + len(b)] = b
    struct.pack_into("<I", code, POINTER - BASE, POINTER)
    return mt_dti.Image(bytes(code), BASE, 0x800, MEM_END)


def test_each_initialiser_is_emulated_from_the_images_own_memory():
    _, classes, _ = mt_dti.recover(image_with_a_bad_initialiser_first())
    by_name = {d.name: d for d in classes.values()}
    for name, _, size in CLASSES:
        assert by_name[name].source == "emu", name
        assert by_name[name].id == size, name
