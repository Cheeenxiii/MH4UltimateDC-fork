# Extra Data (SD extdata) in the port

MH4U keeps downloaded quests and DLC Palicos in its Extra Data: `quest1`..`quest5`, `otomo1`, `card1`..`card3` and `cardbox` (MH Ultimate Collection, `specs/quest.md` and `specs/extdata.md`, where the files' encryption and layout are written up). Nintendo's servers are gone, but the game still reads whatever is in that folder, so a player's own console Extra Data, or files a tool wrote, can be put there.

## Where it is

| What | Value | Status | Source |
|---|---|---|---|
| extdata id | the u64 at exheader 0x230 (ARM11 local system capabilities at 0x200, storage info at +0x30), unless bit 1 of the storage info's last byte (0x24F) is set | from 3dbrew, not yet read from the game's exheader | 3dbrew "NCCH/Extended Header" |
| Azahar folder | `<user>/sdmc/Nintendo 3DS/<32 zeros>/<32 zeros>/extdata/<id high, 8 hex>/<id low, 8 hex>/user/` | Citra's layout; not checked in the port's app | Citra/Azahar file layout |
| services | the game calls `CreateExtSaveData` and opens archive 7 (shared extdata) and 0x567890B4 (its own extdata) | from the code | [system-services.md](system-services.md) |

`tools/extdata_path.py EXHEADER.bin [--user DIR]` prints the id and the folder. Run it on the exheader `tools/extract_ncch.py` writes from your dump.

## Check (open)

1. Run `tools/extdata_path.py` on the USA v1.3.0 exheader, then on the European game's. Record the two ids here (ids are not game data).
2. Start the game once in the app with a fresh user folder and enter the DLC menu. The game creates its Extra Data. Check that the folder above exists and holds `quest1`..`quest5`, `otomo1`, `card1`..`card3` and `cardbox`.
3. Copy your console's Extra Data files there (from a save manager's export), restart, and open the downloaded quests. Pass: they are listed, as on the console.

The content repository's in-game checks Q17, Q19 and E4 (a copied quest, a rebuilt quest, a renamed Palico) can then run in the port instead of on a console.
