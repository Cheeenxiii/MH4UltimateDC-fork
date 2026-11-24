"""tools/recompile_module.py and recomp/modtest.py on synthetic CRO modules (no game data)."""
import os
import struct
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import cro
import recompile_module as RM
from recomp import modtest
from test_cro import build, tag

BASE = 0x02000000


def module_and_crs():
    """roTest: f0 tail-branches to a veneer, which jumps to a static function through its
    import word. Its .data holds a pointer to f0 (its entry point)."""
    text = struct.pack("<3I", 0xEA000000,      # b +8: to the veneer at text+8
                       0xE12FFF1E,             # (unreached)
                       0xE51FF004) + b"\0" * 4  # veneer: ldr pc, [pc, #-4]; .word import
    blob = build(text=text, data=b"\0" * 4,
                 relocs=[(tag(2, 0), cro.R_ARM_ABS32, 0, 0)],
                 anon=[(tag(0, 0x10), [(tag(0, 12), cro.R_ARM_ABS32, 0)])])
    crs = cro.Cro(build(name="|static|", text=b"\0" * 0x100,
                        modules=[("roTest", [(tag(0, 0), [(tag(0, 0x40), cro.R_ARM_ABS32, 0)])])]))
    return blob, crs


def read(path):
    with open(path) as f:
        return f.read()


def test_static_text_comes_from_the_crs():
    _, crs = module_and_crs()
    lo, hi = RM.static_text(crs)
    assert hi - lo == 0x100


def test_veneers_become_tail_calls_into_the_static_code(tmp_path):
    blob, crs = module_and_crs()
    ld = cro.load(blob, BASE, cro.static_segments(crs))
    img = RM.module_image(ld)
    entries = cro.entry_points(ld, crs)
    target = cro.static_segments(crs)[0] + 0x10
    res = RM.recompile_module(img, entries, str(tmp_path / "m"), [RM.static_text(crs)], ld.data_segments())
    assert res["report"]["problems"] == 0
    c = "".join(read(p) for p in res["files"])
    assert f"rc_call(ctx, 0x{target:08x}u)" in c
    assert "RC_TRAP_BAD_JUMP" not in c and ", 4);" not in c
    # the plain analyser calls the same branch a bad jump
    plain = RM.R.recompile(img, entries, str(tmp_path / "p"), data_segments=ld.data_segments())
    assert any("rc_trap" in read(p) for p in plain["files"])


def write_src(d, entries, tail="const u32 rc_text_base = 0x00100000u;"):
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "funcs.h"), "w") as f:
        f.write('#include "recomp.h"\n' + "".join(f"void f_{a:08x}(RCtx *ctx);\n" for a, _ in entries))
    with open(os.path.join(d, "table.c"), "w") as f:
        f.write('#include "funcs.h"\n\nconst RFuncEntry rc_func_table[] = {\n')
        f.writelines(f"    {{0x{a:08x}u, {m}, f_{a:08x}}},\n" for a, m in entries)
        f.write(f"}};\nconst u32 rc_func_count = {len(entries)};\n{tail}\n")
    for a, _ in entries:
        with open(os.path.join(d, f"f{a & ~0xFFFF:08x}.c"), "a") as f:
            f.write(f"/* f_{a:08x} */\n")


def test_merge_makes_one_table(tmp_path):
    s, m, out = tmp_path / "s", tmp_path / "m", tmp_path / "out"
    write_src(str(s), [(0x00100000, 0), (0x00100040, 1)])
    write_src(str(m), [(0x02000010, 0)], tail="")
    assert RM.merge(str(s), str(m), str(out)) == 3
    assert os.path.islink(out / "f00100000.c") and not os.path.islink(out / "f02000000.c")
    entries, tail = RM.read_table(str(out / "table.c"))
    assert [a for a, _, _ in entries] == [0x00100000, 0x00100040, 0x02000010]
    assert entries[1][1] == 1
    assert "const u32 rc_text_base = 0x00100000u;" in tail       # the static build's metadata
    assert (out / "funcs.h").read_text().count("void ") == 3


def test_merge_refuses_shared_addresses(tmp_path):
    write_src(str(tmp_path / "s"), [(0x00100000, 0)])
    write_src(str(tmp_path / "m"), [(0x00100000, 0)])
    with pytest.raises(SystemExit):
        RM.merge(str(tmp_path / "s"), str(tmp_path / "m"), str(tmp_path / "out"))


def seg(address, size, padded):
    return SimpleNamespace(address=address, size=size, padded_size=padded)


def test_modtest_code_offsets_follow_the_padded_segments():
    header = SimpleNamespace(text=seg(0x100000, 0x1800, 0x2000), ro=seg(0x102000, 0x800, 0x1000),
                             data=seg(0x103000, 0x100, 0x1000))
    assert modtest.code_offset(header, 0x100010) == 0x10
    assert modtest.code_offset(header, 0x102004) == 0x2004
    assert modtest.code_offset(header, 0x103008) == 0x3008
    with pytest.raises(ValueError):
        modtest.code_offset(header, 0x101900)                    # text padding: no segment


def test_modtest_patches_the_static_veneers():
    blob, crs = module_and_crs()
    segs = cro.static_segments(crs)
    ld = cro.load(blob, BASE, segs)
    header = SimpleNamespace(text=seg(segs[0], 0x100, 0x1000), ro=seg(segs[1], 0x10, 0x1000),
                             data=seg(segs[2], 0x10, 0x1000))
    code = bytes(0x3000)
    out = modtest.patch_veneers(header, code, crs, ld)
    assert struct.unpack_from("<I", out, 0x40)[0] == ld.segment_bases[0]     # module text + 0
    region, = modtest.module_regions(ld)
    assert region.addr == BASE and region.size % 0x1000 == 0 and region.writable


def test_branch_imports_skip_data():
    # one import feeds a veneer, the other a data word
    text = struct.pack("<2I", 0xE51FF004, 0)
    blob = build(text=text, data=b"\0" * 4,
                 anon=[(tag(0, 0x10), [(tag(0, 4), cro.R_ARM_ABS32, 0)]),
                       (tag(0, 0x20), [(tag(2, 0), cro.R_ARM_ABS32, 0)])])
    segs = [0x00100000, 0x00800000, 0x00900000]
    ld = cro.load(blob, BASE, segs)
    assert RM.branch_imports(ld, segs) == {0x00100010}
    assert sorted(ld.imports) == [0x00100010, 0x00100020]


def test_load_all_links_modules_to_each_other(tmp_path):
    # roB exports text+8 (indexed export 0); roA imports it twice: by tag and by index
    rob = bytearray(build(name="roB", text=b"\0" * 0x10))
    off = len(rob)
    rob += struct.pack("<I", tag(0, 8))
    i = cro.TABLES.index("indexed_exports")
    struct.pack_into("<II", rob, cro.TABLES_AT + 8 * i, off, 1)
    roa = build(name="roA", data=b"\0" * 8,
                modules=[("roB", [(tag(0, 4), [(tag(2, 0), cro.R_ARM_ABS32, 0)])])])
    roa = bytearray(roa)                       # and the indexed import: export 0, into data[1]
    plist = len(roa)
    roa += struct.pack("<IBBBBI", tag(2, 4), cro.R_ARM_ABS32, 1, 0, 0, 0)
    irow = len(roa)
    roa += struct.pack("<II", 0, plist)
    mod_off = struct.unpack_from("<I", roa, cro.TABLES_AT + 8 * cro.TABLES.index("import_modules"))[0]
    struct.pack_into("<II", roa, mod_off + 4, irow, 1)
    paths = []
    for name, blob in (("roA", roa), ("roB", rob)):
        p = tmp_path / f"{name}.cro"
        p.write_bytes(bytes(blob))
        paths.append(str(p))
    crs = cro.Cro(build(name="|static|", text=b"\0" * 0x100))
    a, b = RM.load_all(crs, paths, BASE)
    assert a.base == BASE and b.base % 0x10000 == 0 and b.base > a.base
    d = a.segment_bases[2] - a.base
    assert struct.unpack_from("<2I", a.image, d) == (b.text[0] + 4, b.text[0] + 8)


def test_layout_round_trip(tmp_path):
    p = tmp_path / "modules.tsv"
    p.write_text("# module\tbase\nroEm001\t0x02000000\nroEm003\t0x02030000\n")
    assert RM.read_layout(str(p)) == [("roEm001", 0x02000000), ("roEm003", 0x02030000)]


def test_recompile_static_uses_the_patched_code(tmp_path, monkeypatch):
    blob, crs = module_and_crs()
    segs = cro.static_segments(crs)
    ld = cro.load(blob, BASE, segs)
    header = SimpleNamespace(text=seg(segs[0], 0x100, 0x1000), ro=seg(segs[1], 0x10, 0x1000),
                             data=seg(segs[2], 0x10, 0x1000))
    exheader = tmp_path / "exheader.bin"
    exheader.write_bytes(bytes(0x200) + struct.pack("<Q", 0x0004000000197100))
    code = tmp_path / "code.bin"
    code.write_bytes(bytes(0x3000))
    import codebin2elf
    import exheader as exh
    monkeypatch.setattr(exh, "parse", lambda raw: header)
    monkeypatch.setattr(codebin2elf, "load_code", lambda h, data: data)

    def resolve(ns):
        ns.functions, ns.extra = "unused.tsv", []
        return None
    monkeypatch.setattr(RM.R, "resolve_args", resolve)
    monkeypatch.setattr(RM.R, "load_entries", lambda functions, extra: {segs[0]: "arm"})
    seen = {}

    def fake_recompile(img, entries, out, data_segments=None, title_id=0):
        seen.update(img=img, title_id=title_id, out=out)
        return {"report": {"functions": 1}}
    monkeypatch.setattr(RM.R, "recompile", fake_recompile)
    RM.recompile_static("mhxx", str(exheader), str(code), crs, [ld], str(tmp_path / "static"))
    assert struct.unpack_from("<I", seen["img"].code, 0x40)[0] == ld.segment_bases[0]
    assert seen["title_id"] == 0x0004000000197100


def test_pointers_into_veneers_are_not_entries():
    # text: a veneer (ldr pc, [pc, #-4]; .word) then f (bx lr). .data points at f, at the
    # veneer's address word, and inside the veneer with bit 0 set (as a Thumb pointer).
    text = struct.pack("<3I", 0xE51FF004, 0x00123456, 0xE12FFF1E)
    blob = build(text=text, data=b"\0" * 12,
                 relocs=[(tag(2, 0), cro.R_ARM_ABS32, 0, 8), (tag(2, 4), cro.R_ARM_ABS32, 0, 4),
                         (tag(2, 8), cro.R_ARM_ABS32, 0, 3)])
    crs = cro.Cro(build(name="|static|", text=b"\0" * 0x100))
    ld = cro.load(blob, BASE, cro.static_segments(crs))
    t = ld.text[0]
    assert set(cro.entry_points(ld)) == {t + 8, t + 4, t + 2}     # what the data says
    assert RM.module_entries(ld, crs, [ld]) == {t + 8: "arm"}
