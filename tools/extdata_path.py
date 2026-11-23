#!/usr/bin/env python3
"""Where a 3DS title's Extra Data (SD extdata) lives, read from its exheader.

The exheader's ARM11 local system capabilities start at 0x200 (program id first); their storage info is at
+0x30, and its first field is the u64 extdata id (3dbrew, "NCCH/Extended Header", ARM11 Local System
Capabilities > Storage Info). Azahar, like Citra, keeps SD extdata at
    <user>/sdmc/Nintendo 3DS/<32 zeros>/<32 zeros>/extdata/<id high, 8 hex>/<id low, 8 hex>/
with the files the game sees under `user/` (an assumption taken from Citra's layout, to be checked in the app:
docs/research/extdata.md). MH Ultimate Collection writes downloaded-quest and DLC Palico files there
(its specs/extdata.md).

Usage: extdata_path.py EXHEADER.bin [--user AZAHAR_USER_DIR]
"""
from __future__ import annotations

import argparse
import os
import struct
import sys

ACI = 0x200
STORAGE_INFO = ACI + 0x30
EXTDATA_ID = STORAGE_INFO + 0x00
OTHER_ATTRIBUTES = STORAGE_INFO + 0x1F  # bit 1: "use extended savedata access" (the id field means otherwise)
ID0 = "0" * 32


def extdata_id(exheader: bytes) -> int:
    if len(exheader) < STORAGE_INFO + 0x20:
        raise ValueError(f"exheader too small (0x{len(exheader):X} bytes) for the storage info")
    if exheader[OTHER_ATTRIBUTES] & 0x2:
        raise ValueError("the title uses extended savedata access: the extdata id field holds other ids")
    return struct.unpack_from("<Q", exheader, EXTDATA_ID)[0]


def azahar_extdata_dir(user_dir: str, ext_id: int) -> str:
    return os.path.join(user_dir, "sdmc", "Nintendo 3DS", ID0, ID0, "extdata",
                        f"{ext_id >> 32:08x}", f"{ext_id & 0xFFFFFFFF:08x}", "user")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("exheader")
    ap.add_argument("--user", help="Azahar's user folder: prints the full folder")
    args = ap.parse_args(argv)
    with open(args.exheader, "rb") as f:
        data = f.read()
    try:
        ext = extdata_id(data)
    except ValueError as e:
        print(f"extdata_path: {e}", file=sys.stderr)
        return 1
    print(f"extdata id : {ext:016X}")
    if ext == 0:
        print("this title declares no extdata")
        return 0
    print(azahar_extdata_dir(args.user or "<Azahar user folder>", ext))
    return 0


if __name__ == "__main__":
    sys.exit(main())
