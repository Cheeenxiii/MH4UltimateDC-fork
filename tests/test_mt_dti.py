"""Tests for tools/mt_dti.py on a hand-assembled synthetic ARM image (no game data)."""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import mt_dti  # noqa: E402

BASE = 0x00100000
CTOR = BASE
DTI_AREA = BASE + 0x8000
MEM_END = BASE + 0x10000

# (name, parent index or None, size)
CLASSES = [
    ("MtObject", None, 0x04),
    ("cResource", 0, 0x68),
    ("rTexture", 1, 0xF0),
    ("nDraw::Resource", 0, 0x10),
]


def ldr_pc(rd, at, target):
    return 0xE59F0000 | rd << 12 | (target - (at + 8))


def adr(rd, at, target):
    off = target - (at + 8)
    assert 0 <= off < 0x100
    return 0xE28F0000 | rd << 12 | off


def mov(rd, imm):
    assert imm < 0x100
    return 0xE3A00000 | rd << 12 | imm


def bl(at, target):
    return 0xEB000000 | (((target - (at + 8)) >> 2) & 0xFFFFFF)


def build_image():
    words = {}
    # Fake constructor: store name/parent/size, and use size as the "id" at +0x1C.
    ctor = [0xE5801004, 0xE5802008, 0xE580300C, 0xE580301C, 0xE12FFF1E]
    for i, w in enumerate(ctor):
        words[CTOR + 4 * i] = w
    blobs = {}
    for i, (name, parent, size) in enumerate(CLASSES):
        f = BASE + 0x100 + i * 0x40
        dti = DTI_AREA + i * 0x20
        words[f + 0x00] = 0xE92D4010                         # push {r4, lr}
        words[f + 0x04] = ldr_pc(0, f + 0x04, f + 0x1C)      # r0 = &dti
        words[f + 0x08] = adr(1, f + 0x08, f + 0x24)         # r1 = name
        words[f + 0x0C] = (ldr_pc(2, f + 0x0C, f + 0x20) if parent is not None else mov(2, 0))
        words[f + 0x10] = mov(3, size)
        words[f + 0x14] = bl(f + 0x14, CTOR)
        words[f + 0x18] = 0xE8BD8010                         # pop {r4, pc}
        words[f + 0x1C] = dti
        words[f + 0x20] = DTI_AREA + parent * 0x20 if parent is not None else 0
        blobs[f + 0x24] = name.encode() + b"\0"
    code = bytearray(0x1000)
    for a, w in words.items():
        struct.pack_into("<I", code, a - BASE, w)
    for a, b in blobs.items():
        code[a - BASE:a - BASE + len(b)] = b
    return mt_dti.Image(bytes(code), BASE, len(code), MEM_END)


def test_detects_constructor():
    assert mt_dti.detect_ctor(build_image()) == CTOR


def test_recovers_hierarchy_by_emulation():
    ctor, classes, ncalls = mt_dti.recover(build_image())
    assert ctor == CTOR and ncalls == len(CLASSES)
    by_name = {d.name: d for d in classes.values()}
    assert set(by_name) == {c[0] for c in CLASSES}
    for i, (name, parent, size) in enumerate(CLASSES):
        d = by_name[name]
        assert d.source == "emu"
        assert d.address == DTI_AREA + i * 0x20
        assert d.size == size
        assert d.id == size                      # read back from DTI + 0x1C after the real ctor ran
        expected_parent = None if parent is None else DTI_AREA + parent * 0x20
        assert d.parent == expected_parent


def test_static_fallback_matches():
    img = build_image()
    for i, (name, parent, size) in enumerate(CLASSES):
        call = BASE + 0x100 + i * 0x40 + 0x14
        d = mt_dti.static_resolve(img, call)
        assert d is not None and d.name == name and d.size == size
        assert d.address == DTI_AREA + i * 0x20


def test_write_tsv_names_parents(tmp_path):
    _, classes, _ = mt_dti.recover(build_image())
    out = tmp_path / "classes.tsv"
    mt_dti.write_tsv(classes, str(out))
    rows = [line.split("\t") for line in out.read_text().splitlines()[2:]]
    parent_of = {r[1]: r[3] for r in rows}
    assert parent_of == {"MtObject": "", "cResource": "MtObject",
                         "rTexture": "cResource", "nDraw::Resource": "MtObject"}


def test_mt_hash():
    # Value observed for "MtObject" in the game's own class registry.
    assert mt_dti.mt_hash("MtObject") == 0x2EA10CEB


POISON = BASE + 0x900                            # writable word holding its own address


def build_hostile_image():
    """Two initialisers that broke the emulation of others: one zeroes a global the
    constructor follows (as a constructor run on a stray pointer corrupts the class list),
    one stores through ip as its caller left it. The first sits before every class."""
    words, blobs = {}, {}
    ctor = [ldr_pc(12, CTOR, CTOR + 0x24), 0xE59CC000, 0xE59CC000,   # ip = *(*POISON): faults on 0
            0xE5801004, 0xE5802008, 0xE580300C, 0xE580301C, 0xE12FFF1E]
    for i, w in enumerate(ctor):
        words[CTOR + 4 * i] = w
    words[CTOR + 0x24] = POISON

    def initialiser(f, dti, name, parent, size, before):
        body = [0xE92D4010] + before                                 # push {r4, lr}
        at = f + 4 * len(body)
        body += [ldr_pc(0, at, f + 0x30), adr(1, at + 4, f + 0x38),
                 ldr_pc(2, at + 8, f + 0x34) if parent is not None else mov(2, 0), mov(3, size)]
        body += [bl(f + 4 * len(body), CTOR), 0xE8BD8010]            # bl ctor; pop {r4, pc}
        assert len(body) <= 12
        for i, w in enumerate(body):
            words[f + 4 * i] = w
        words[f + 0x30], words[f + 0x34] = dti, parent or 0
        blobs[f + 0x38] = name.encode() + b"\0"

    bad = BASE + 0x80
    initialiser(bad, DTI_AREA + 0x200, "cBad", None, 4,
                [mov(4, 0), ldr_pc(1, bad + 8, bad + 0x2C), 0xE5814000])  # *POISON = 0
    words[bad + 0x2C] = POISON
    for i, (name, parent, size) in enumerate(CLASSES):
        initialiser(BASE + 0x100 + i * 0x60, DTI_AREA + i * 0x20, name,
                    None if parent is None else DTI_AREA + parent * 0x20, size, [])
    initialiser(BASE + 0x400, DTI_AREA + 0x240, "cUsesIp", None, 8,
                [mov(4, 0), 0xE58C4000])                             # str r4, [ip]
    code = bytearray(0x1000)
    for a, w in words.items():
        struct.pack_into("<I", code, a - BASE, w)
    for a, b in blobs.items():
        code[a - BASE:a - BASE + len(b)] = b
    struct.pack_into("<I", code, POISON - BASE, POISON)
    return mt_dti.Image(bytes(code), BASE, 0x800, MEM_END)          # POISON is past text


def test_each_initialiser_starts_from_pristine_memory():
    _, classes, _ = mt_dti.recover(build_hostile_image())
    by_name = {d.name: d for d in classes.values()}
    for name, _, size in CLASSES:
        assert by_name[name].source == "emu" and by_name[name].id == size


def test_initialiser_may_use_ip_from_its_caller():
    _, classes, _ = mt_dti.recover(build_hostile_image())
    d = next(d for d in classes.values() if d.name == "cUsesIp")
    assert d.source == "emu" and d.id == 8
