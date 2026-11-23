"""tools/extdata_path.py on a synthetic exheader (no game data)."""
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import extdata_path as ep  # noqa: E402


def exheader(ext_id: int, attributes: int = 0) -> bytes:
    buf = bytearray(0x400)
    struct.pack_into("<Q", buf, 0x200, 0x0004000000ABC000)
    struct.pack_into("<Q", buf, ep.EXTDATA_ID, ext_id)
    buf[ep.OTHER_ATTRIBUTES] = attributes
    return bytes(buf)


def test_reads_the_extdata_id():
    assert ep.extdata_id(exheader(0x1234)) == 0x1234


def test_refuses_short_or_extended_access():
    with pytest.raises(ValueError):
        ep.extdata_id(bytes(0x220))
    with pytest.raises(ValueError):
        ep.extdata_id(exheader(0x1234, attributes=0x2))


def test_azahar_path():
    path = ep.azahar_extdata_dir("U", 0x00000000_0000ABCD)
    assert path.split(os.sep) == ["U", "sdmc", "Nintendo 3DS", "0" * 32, "0" * 32, "extdata",
                                  "00000000", "0000abcd", "user"]


def test_cli(tmp_path, capsys):
    f = tmp_path / "exh.bin"
    f.write_bytes(exheader(0xABCD))
    assert ep.main([str(f), "--user", "U"]) == 0
    out = capsys.readouterr().out
    assert "000000000000ABCD" in out and "0000abcd" in out
    f.write_bytes(exheader(0))
    assert ep.main([str(f)]) == 0
    assert "declares no extdata" in capsys.readouterr().out
