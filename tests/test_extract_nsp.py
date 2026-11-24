"""extract_nsp / aes128 on synthetic data: made-up keys, a hand-built NSP."""
import hashlib
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import aes128
import extract_nsp as ex

HEADER_KEY = bytes(range(32))
TITLEKEK = bytes(range(0x40, 0x50))
KAEK = bytes(range(0x80, 0x90))
TITLE_KEY = bytes(range(0xA0, 0xB0))
RIGHTS_ID = bytes.fromhex("0100aaaa00bbb0000000000000000004")
CTR_UPPER = bytes.fromhex("0102030405060708")


@pytest.fixture(params=["openssl", "python"])
def backend(request, monkeypatch):
    if request.param == "python":
        monkeypatch.setattr(aes128, "_LIB", False)
    elif not aes128._libcrypto():
        pytest.skip("no libcrypto on this machine")
    return request.param


# ── AES vectors ─────────────────────────────────────────────────────────────

def test_fips197_vector(backend):
    k = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    pt = bytes.fromhex("00112233445566778899aabbccddeeff")
    ct = aes128.ecb_encrypt(k, pt)
    assert ct.hex() == "69c4e0d86a7b0430d8cdb78070b4c55a"
    assert aes128.ecb_decrypt(k, ct) == pt


def test_sp800_38a_ctr_vector(backend):
    k = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
    iv = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff")
    pt = bytes.fromhex("6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e51")
    assert aes128.ctr_crypt(k, iv, pt).hex() == (
        "874d6191b620e3261bef6864990db6ce9806f66b7970fdff8617187bb9fffdff")


def test_ieee1619_xts_vector_1(backend):
    # Sector 0: the big-endian and little-endian tweaks agree, so the standard vector applies.
    ct = aes128.xts_encrypt(bytes(32), bytes(32), 0, 32)
    assert ct.hex() == "917cf69ebd68b2ec9b9fe9a3eadda692cd43d2f59598ed858c02c2652fbf922e"


def test_xts_uses_big_endian_sector_tweak(backend):
    k = bytes(range(32))
    a = aes128.xts_encrypt(k, bytes(0x200), 1)
    tweak = aes128.ecb_encrypt(k[16:], (1).to_bytes(16, "big"))
    first = aes128.ecb_encrypt(k[:16], tweak)
    assert a[:16] == bytes(x ^ y for x, y in zip(first, tweak))
    assert aes128.xts_decrypt(k, a, 1) == bytes(0x200)


# ── LZ4 / NSO ───────────────────────────────────────────────────────────────

def lz4_literals(data: bytes) -> bytes:
    n = len(data)
    if n < 15:
        return bytes([n << 4]) + data
    out = bytearray([0xF0])
    rest = n - 15
    while rest >= 255:
        out.append(255)
        rest -= 255
    out.append(rest)
    return bytes(out) + data


def test_lz4_match_and_overlap():
    # "abc" literal, then a 9-byte match at offset 3 (overlapping), then "Z" literal.
    blk = bytes([0x35]) + b"abc" + struct.pack("<H", 3) + bytes([0x10]) + b"Z"
    assert ex.lz4_block_decompress(blk, 13) == b"abcabcabcabcZ"


def test_lz4_long_literals():
    data = bytes(range(256)) * 2
    assert ex.lz4_block_decompress(lz4_literals(data), len(data)) == data


def make_nso(text: bytes, ro: bytes, data: bytes, bss: int = 0x100) -> bytes:
    segs = [text, ro, data]
    comp = [lz4_literals(text), ro, data]          # only text compressed
    hdr = bytearray(0x100)
    hdr[0:4] = b"NSO0"
    struct.pack_into("<I", hdr, 0xC, 0b001001)     # text compressed, text hash checked
    foff, moff = 0x100, 0
    for k in range(3):
        struct.pack_into("<III", hdr, 0x10 + 0x10 * k, foff, moff, len(segs[k]))
        struct.pack_into("<I", hdr, 0x60 + 4 * k, len(comp[k]))
        hdr[0xA0 + 0x20 * k:0xC0 + 0x20 * k] = hashlib.sha256(segs[k]).digest()
        foff += len(comp[k])
        moff = (moff + len(segs[k]) + 0xFFF) & ~0xFFF
    struct.pack_into("<I", hdr, 0x3C, bss)
    hdr[0x40:0x60] = b"B" * 0x20
    return bytes(hdr) + b"".join(comp)


TEXT = b"\x1e\xff\x2f\xe1" * 0x40
RO = b"uEnemy\0rEnemyCmd\0"
DATA = b"\x01\x02\x03\x04" * 4


def test_parse_nso_segments_and_image():
    nso = ex.parse_nso(make_nso(TEXT, RO, DATA))
    assert nso.segments["text"] == (0, TEXT)
    assert nso.segments["rodata"] == (0x1000, RO)
    assert nso.segments["data"] == (0x2000, DATA)
    img = nso.image()
    assert img[:len(TEXT)] == TEXT and img[0x2000:] == DATA and nso.bss_size == 0x100


def test_parse_nso_hash_mismatch():
    bad = bytearray(make_nso(TEXT, RO, DATA))
    bad[0xA0] ^= 1
    with pytest.raises(ex.NspError, match="hash"):
        ex.parse_nso(bytes(bad))


# ── PFS0 / NCA / NSP ────────────────────────────────────────────────────────

def make_pfs0(files: list[tuple[str, bytes]], align: int = 0) -> bytes:
    strtab = b"".join(n.encode() + b"\0" for n, _ in files)
    hlen = 0x10 + 0x18 * len(files) + len(strtab)
    if align:
        strtab += b"\0" * (((hlen + align - 1) & ~(align - 1)) - hlen)
    ents, off, noff = b"", 0, 0
    for n, d in files:
        ents += struct.pack("<QQII", off, len(d), noff, 0)
        off += len(d)
        noff += len(n) + 1
    return b"PFS0" + struct.pack("<II", len(files), len(strtab)) + bytes(4) + ents + strtab \
        + b"".join(d for _, d in files)


def make_npdm(is64: bool) -> bytes:
    d = bytearray(0x80)
    d[0:4] = b"META"
    d[0xC] = (1 if is64 else 0) | (2 << 1)
    d[0x20:0x2B] = b"Application"
    return bytes(d)


def make_nca(exefs: bytes, use_rights: bool, ctype: int = 0) -> bytes:
    block = 0x1000
    pfs = exefs + bytes((-len(exefs)) % 0x200)
    table = b"".join(hashlib.sha256(exefs[i:i + block]).digest() for i in range(0, len(exefs), block))
    table_padded = table + bytes((-len(table)) % 0x200)
    sec_plain = table_padded + pfs
    sec_plain += bytes((-len(sec_plain)) % MEDIA)

    fsh = bytearray(0x200)
    struct.pack_into("<HBBB", fsh, 0, 2, 1, 2, 3)        # version, PFS0, hier-SHA256, CTR
    fsh[8:0x28] = hashlib.sha256(table).digest()
    struct.pack_into("<IIQQQQ", fsh, 0x28, block, 2, 0, len(table), len(table_padded), len(exefs))
    fsh[0x140:0x148] = CTR_UPPER

    sec_start = 0xC00
    hdr = bytearray(0xC00)
    hdr[0x200:0x204] = b"NCA3"
    hdr[0x205] = ctype
    hdr[0x206] = 0
    hdr[0x220] = 3                                        # key generation 3 → master index 2
    struct.pack_into("<QQ", hdr, 0x208, sec_start + len(sec_plain), 0x0100AAAA00BBB000)
    struct.pack_into("<I", hdr, 0x21C, 0x04040100)
    struct.pack_into("<II", hdr, 0x240, sec_start // MEDIA, (sec_start + len(sec_plain)) // MEDIA)
    hdr[0x280:0x2A0] = hashlib.sha256(fsh).digest()
    hdr[0x400:0x600] = fsh
    if use_rights:
        hdr[0x230:0x240] = RIGHTS_ID
        key = TITLE_KEY
    else:
        key = bytes(range(0xC0, 0xD0))
        hdr[0x320:0x330] = aes128.ecb_encrypt(KAEK, key)
    enc_sec = aes128.ctr_crypt(key, CTR_UPPER[::-1] + (sec_start >> 4).to_bytes(8, "big"), sec_plain)
    enc_hdr = aes128.xts_encrypt(HEADER_KEY, bytes(hdr), 0)
    return enc_hdr + enc_sec


MEDIA = 0x200


def make_ticket() -> bytes:
    t = bytearray(0x2C0)
    struct.pack_into("<I", t, 0, 0x10004)
    body = 0x140
    t[body + 0x40:body + 0x50] = aes128.ecb_encrypt(TITLEKEK, TITLE_KEY)
    t[body + 0x141] = 0
    t[body + 0x160:body + 0x170] = RIGHTS_ID
    return bytes(t)


def make_nsp(use_rights: bool = True, with_ticket: bool = True, is64: bool = False) -> bytes:
    main = make_nso(TEXT, RO, DATA)
    exefs = make_pfs0([("main", main), ("main.npdm", make_npdm(is64)), ("sdk", make_nso(TEXT, b"x", b"y"))])
    files = [("abcd.nca", make_nca(exefs, use_rights))]
    if with_ticket:
        files.append((RIGHTS_ID.hex() + ".tik", make_ticket()))
    return make_pfs0(files, align=0x20)


def keys(with_titles: bool = False) -> ex.Keys:
    k = ex.Keys({"header_key": HEADER_KEY, "titlekek_02": TITLEKEK, "key_area_key_application_02": KAEK})
    if with_titles:
        k.titles = {RIGHTS_ID.hex(): aes128.ecb_encrypt(TITLEKEK, TITLE_KEY)}
    return k


def test_parse_keyfile():
    k = ex.parse_keyfile("# c\nheader_key = 00ff\nTitlekek_00=0102 ; x\nbad = zz\n\n")
    assert k == {"header_key": b"\x00\xff", "titlekek_00": b"\x01\x02"}


def test_nca_header_roundtrip():
    nca_bytes = make_nca(make_pfs0([("a", b"1")]), use_rights=False)
    hdr = ex.decrypt_nca_header(nca_bytes[:0xC00], HEADER_KEY)
    nca = ex.parse_nca_header(hdr)
    assert nca.magic == "NCA3" and nca.content_type == "program" and nca.key_generation == 3
    assert len(nca.sections) == 1 and nca.sections[0].crypt_type == 3
    with pytest.raises(ex.NspError, match="did not decrypt"):
        ex.decrypt_nca_header(nca_bytes[:0xC00], bytes(32))


def test_section_ctr_iv():
    sec = ex.NcaSection(0, 0xC00, 0x1000, 1, 2, 3, CTR_UPPER, b"")
    assert ex.section_ctr_iv(sec, 0xC10) == CTR_UPPER[::-1] + (0xC1).to_bytes(8, "big")


@pytest.mark.parametrize("use_rights,with_ticket,with_titles", [
    (True, True, False),       # title key from the NSP's ticket
    (True, False, True),       # title key from title.keys
    (False, False, False),     # key area
])
def test_extract_end_to_end(tmp_path, backend, use_rights, with_ticket, with_titles):
    nsp = tmp_path / "t.nsp"
    nsp.write_bytes(make_nsp(use_rights, with_ticket))
    info = ex.extract(str(nsp), keys(with_titles), str(tmp_path / "out"), ["main"])
    out = tmp_path / "out"
    assert (out / "main.text.bin").read_bytes() == TEXT
    assert (out / "main.rodata.bin").read_bytes() == RO
    assert (out / "main.data.bin").read_bytes() == DATA
    assert (out / "main.npdm").read_bytes()[:4] == b"META"
    text = (out / "info.txt").read_text()
    assert "AArch32" in text and "exefs: 3 files" in text and "hash blocks verified" in text
    assert info[0].startswith("source:")
    assert TITLE_KEY.hex() not in text and HEADER_KEY.hex() not in text


def test_extract_all_nso_and_64bit(tmp_path):
    nsp = tmp_path / "t.nsp"
    nsp.write_bytes(make_nsp(is64=True))
    ex.extract(str(nsp), keys(), str(tmp_path / "o"), [], all_nso=True)
    assert (tmp_path / "o" / "sdk.rodata.bin").read_bytes() == b"x"
    assert "AArch64" in (tmp_path / "o" / "info.txt").read_text()


def test_missing_title_key(tmp_path):
    nsp = tmp_path / "t.nsp"
    nsp.write_bytes(make_nsp(True, with_ticket=False))
    with pytest.raises(ex.NspError, match="no title key"):
        ex.extract(str(nsp), keys(), str(tmp_path / "o"), ["main"])


def test_wrong_title_key_fails_hash_check(tmp_path):
    nsp = tmp_path / "t.nsp"
    nsp.write_bytes(make_nsp(True, with_ticket=False))
    k = keys()
    k.titles = {RIGHTS_ID.hex(): bytes(16)}
    with pytest.raises(ex.NspError, match="master hash"):
        ex.extract(str(nsp), k, str(tmp_path / "o"), ["main"])


def test_cli_list_and_errors(tmp_path, capsys):
    nsp = tmp_path / "t.nsp"
    nsp.write_bytes(make_nsp())
    kf = tmp_path / "prod.keys"
    kf.write_text(f"header_key = {HEADER_KEY.hex()}\ntitlekek_02 = {TITLEKEK.hex()}\n")
    assert ex.main([str(nsp), "--keys", str(kf), "--list"]) == 0
    assert "main" in capsys.readouterr().out
    (tmp_path / "bad.nsp").write_bytes(b"NOPE" + bytes(60))
    assert ex.main([str(tmp_path / "bad.nsp"), "--keys", str(kf), "-o", str(tmp_path / "o")]) == 1


def test_personalized_ticket_rejected():
    t = bytearray(make_ticket())
    t[0x140 + 0x141] = 1
    with pytest.raises(ex.NspError, match="personalized"):
        ex.ticket_title_key(bytes(t))
