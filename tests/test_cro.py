"""tools/cro.py on synthetic CRO0 modules (no game data)."""
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import cro


def build(name="roTest", text=b"", ro=b"", data=b"", bss=0, relocs=(), anon=(), modules=(),
          exports=()):
    """A minimal CRO0. relocs: (tag, type, segment, addend). anon: (static tag, [(tag, type,
    addend)]). modules: (name, [(module tag, [(tag, type, addend)])]) for a CRS."""
    body = bytearray(0x180)
    tables = {}

    def put(blob, align=4):
        while len(body) % align:
            body.append(0)
        off = len(body)
        body.extend(blob)
        return off

    t_off = put(text)
    ro_off = put(ro)
    d_off = put(data)
    segs = [(t_off, len(text), 0), (ro_off, len(ro), 1), (d_off, len(data), 2), (0, bss, 3)]
    tables["segments"] = (put(b"".join(struct.pack("<3I", *s) for s in segs)), len(segs))
    strings = {}

    def string(s):
        if s not in strings:
            strings[s] = put(s.encode() + b"\0", 1)
        return strings[s]

    name_off = string(name)
    ex = [(string(n), tag) for n, tag in exports]
    tables["named_exports"] = (put(b"".join(struct.pack("<II", *e) for e in ex)), len(ex))

    def patches(plist):
        blob = b"".join(struct.pack("<IBBBBI", tag, ty, int(i == len(plist) - 1), 0, 0, add)
                        for i, (tag, ty, add) in enumerate(plist))
        return put(blob)

    rows = [(tag, patches(pl)) for tag, pl in anon]
    tables["anon_imports"] = (put(b"".join(struct.pack("<II", *r) for r in rows)), len(rows))
    mrows = []
    for mname, entries in modules:
        er = [(tag, patches(pl)) for tag, pl in entries]
        eoff = put(b"".join(struct.pack("<II", *r) for r in er))
        mrows.append((string(mname), eoff, 0, eoff, len(er)))
    tables["import_modules"] = (put(b"".join(struct.pack("<5I", *r) for r in mrows)), len(mrows))
    tables["relocations"] = (put(b"".join(struct.pack("<IBBBBI", t, ty, seg, 0, 0, add)
                                         for t, ty, seg, add in relocs)), len(relocs))
    body[0x80:0x84] = b"CRO0"
    struct.pack_into("<I", body, 0x84, name_off)
    struct.pack_into("<I", body, 0x90, len(body))
    struct.pack_into("<I", body, 0x94, bss)
    for i, n in enumerate(cro.TABLES):
        off, count = tables.get(n, (len(body), 0))
        struct.pack_into("<II", body, cro.TABLES_AT + 8 * i, off, count)
    return bytes(body)


def tag(seg, off):
    return off << 4 | seg


def word(img, base, addr):
    return struct.unpack_from("<I", img, addr - base)[0]


def test_header_and_segments():
    c = cro.Cro(build(text=b"\0" * 8, ro=b"\0" * 4, data=b"\0" * 12, bss=0x20,
                      exports=[("nnroControlObject_", tag(2, 0))]))
    assert c.name == "roTest"
    assert [s.kind for s in c.segments] == [0, 1, 2, 3]
    assert c.segments[0].size == 8 and c.segments[2].size == 12 and c.segments[3].size == 0x20
    assert c.named_exports() == [("nnroControlObject_", tag(2, 0))]


def test_rejects_other_files():
    with pytest.raises(cro.CroError):
        cro.Cro(b"\0" * 0x200)


def test_relocations_and_static_imports():
    text = struct.pack("<2I", 0xE51FF004, 0)           # ldr pc, [pc, #-4]; .word (import)
    data = struct.pack("<3I", 0, 0, 0)
    blob = build(text=text, data=data, bss=0x10,
                 relocs=[(tag(2, 0), cro.R_ARM_ABS32, 0, 0),        # data[0] = &text[0]
                         (tag(2, 4), cro.R_ARM_ABS32, 3, 8),        # data[1] = &bss + 8
                         (tag(2, 8), cro.R_ARM_REL32, 0, 4)],       # data[2] = &text[4] - P
                 anon=[(tag(0, 0x1234), [(tag(0, 4), cro.R_ARM_ABS32, 0)])])
    base = 0x02000000
    static = [0x00100000, 0x00800000, 0x00900000]
    ld = cro.load(blob, base, static)
    t0, _ = ld.text
    d0 = ld.segment_bases[2]
    assert word(ld.image, base, d0) == t0
    assert word(ld.image, base, d0 + 4) == ld.segment_bases[3] + 8
    assert ld.segment_bases[3] == base + len(blob)
    assert word(ld.image, base, d0 + 8) == (t0 + 4 - (d0 + 8)) & 0xFFFFFFFF
    assert word(ld.image, base, t0 + 4) == 0x00101234            # the veneer's target
    assert ld.imports == [0x00101234]
    assert ld.patch_types == {cro.R_ARM_ABS32: 3, cro.R_ARM_REL32: 1}
    assert cro.entry_points(ld) == {t0: "arm"}


def test_branch_relocations():
    text = struct.pack("<3I", 0xEB000000, 0xEA000000, 0xEB000000)   # bl, b, bl
    blob = build(text=text, anon=[(tag(0, 0x40), [(tag(0, 0), cro.R_ARM_CALL, 0),
                                                  (tag(0, 4), cro.R_ARM_JUMP24, 0)]),
                                  (tag(0, 0x81), [(tag(0, 8), cro.R_ARM_CALL, 0)])])  # Thumb
    base = 0x00200000
    ld = cro.load(blob, base, [0x00100000])
    t0, _ = ld.text

    def target(addr):
        w = word(ld.image, base, addr)
        off = (w & 0xFFFFFF) << 2
        off -= (1 << 26) if off & (1 << 25) else 0
        return addr + 8 + off + ((w >> 24) & 1) * 2 * (w >> 28 == 0xF), w >> 24

    assert target(t0) == (0x00100040, 0xEB)
    assert target(t0 + 4) == (0x00100040, 0xEA)
    addr, op = target(t0 + 8)
    assert op & 0xFE == 0xFA and addr == 0x00100080              # BLX, Thumb target


def test_unknown_relocation_type_is_an_error():
    blob = build(data=b"\0" * 4, relocs=[(tag(2, 0), 0x7F, 0, 0)])
    with pytest.raises(cro.CroError):
        cro.load(blob, 0x02000000, [0x100000])


def test_static_imports_of_module():
    crs = cro.Cro(build(name="|static|", modules=[
        ("roTest", [(tag(0, 0x10), [(tag(0, 0x2000), cro.R_ARM_ABS32, 0),
                                    (tag(1, 0x8), cro.R_ARM_ABS32, 0)])])]))
    # a CRS gives its segments as absolute addresses; this synthetic one has small offsets
    segs = cro.static_segments(crs)
    got = cro.static_imports_of(crs, "roTest")
    assert got == [(tag(0, 0x10), [segs[0] + 0x2000, segs[1] + 0x8])]
    assert cro.static_imports_of(crs, "roOther") == []
    mod = build(name="roTest", text=b"\0" * 0x20)
    ld = cro.load(mod, 0x02000000, segs)
    assert cro.entry_points(ld, crs) == {ld.text[0] + 0x10: "arm"}


def test_cli_info(tmp_path, capsys):
    p = tmp_path / "m.cro"
    p.write_bytes(build(text=b"\0" * 4))
    assert cro.main(["info", str(p)]) == 0
    assert "name: roTest" in capsys.readouterr().out
