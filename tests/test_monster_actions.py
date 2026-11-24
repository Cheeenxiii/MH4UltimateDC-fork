"""tools/monster_actions.py on a synthetic dispatcher (hand-encoded ARM, no game data)."""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import monster_actions as M
from monster_actions import Action, Code

BASE = 0x100000
NOP, BX_LR, POP_R4_PC, POP_R4_LR, PUSH_R4_LR = 0xE320F000, 0xE12FFF1E, 0xE8BD8010, 0xE8BD4010, 0xE92D4010


def b(at, target, cond=0xE):
    return (cond << 28) | (0xA << 24) | (((target - at - 8) >> 2) & 0xFFFFFF)


def program():
    """dispatcher at BASE on category byte (3 entries: 0 -> a category function, 1 -> default,
    2 -> a compare chain in the dispatcher); the category function's table has a case that
    tail-calls with r1 = 5 and one that goes through a veneer to outside code."""
    w = {}
    def put(a, *words):
        for k, x in enumerate(words):
            w[a + 4 * k] = x
    A = lambda off: BASE + off
    put(A(0x00), 0xE5901E28, 0xE5D121CA, 0xE3520003, 0x379FF102, BX_LR,   # ldr; ldrb; cmp #3; ldrlo pc; bx lr
        A(0x20), A(0x10), A(0x28))                                     # table: cat 1 = default
    put(A(0x20), NOP, b(A(0x24), A(0x100)))                            # cat 0: its own function
    put(A(0x28), 0xE5D111CB, 0xE3510001, b(A(0x30), A(0x40), 0x0), POP_R4_PC)  # ldrb r1; cmp r1,#1; beq; pop
    put(A(0x40), 0xE3A02000, b(A(0x44), A(0x400)))                     # mov r2, #0; b handler (outside)
    put(A(0x100), PUSH_R4_LR, 0xE5901E28, 0xE5D121CB, 0xE3520002, 0x379FF102, POP_R4_PC,
        A(0x120), A(0x130))
    put(A(0x120), POP_R4_LR, 0xE3A01005, b(A(0x128), A(0x500)))        # mov r1, #5; b handler
    put(A(0x130), POP_R4_LR, b(A(0x134), A(0x200)))                    # b veneer
    put(A(0x200), 0xE51FF004, 0x00987654)                              # ldr pc, [pc, #-4]; .word
    data = bytearray(0x600)
    for a, x in w.items():
        struct.pack_into("<I", data, a - BASE, x)
    return Code(bytes(data), BASE, BASE, BASE + 0x300)


def test_inventory_walks_tables_chains_and_veneers():
    acts = M.inventory(program(), BASE)
    got = {(x.cat, x.idx): x for x in acts}
    assert set(got) == {(0, 0), (0, 1), (2, 1)}          # category 1 is the default: no actions
    a = got[(0, 0)]
    assert (a.fn, a.kind, a.handler, a.args, a.via_veneer) == (BASE + 0x100, "tail", BASE + 0x500, {"r1": 5}, False)
    v = got[(0, 1)]
    assert v.handler == 0x00987654 and v.via_veneer
    c = got[(2, 1)]
    assert c.fn is None and c.handler == BASE + 0x400 and c.args == {"r2": 0}


def test_inventory_round_trips(tmp_path):
    acts = M.inventory(program(), BASE)
    p = tmp_path / "a.tsv"
    p.write_text(M.HEADER + "".join(x.row() + "\n" for x in acts))
    assert M.read_inventory(str(p)) == acts


def test_pairs_need_one_partner_per_handler():
    a = [Action(3, 0, 1, None, "tail", 0x10), Action(3, 1, 2, None, "tail", 0x10),
         Action(3, 2, 3, None, "tail", 0x20), Action(3, 3, 4, None, "tail", 0x20),
         Action(7, 0, 5, None, "inline")]
    b = [Action(3, 0, 1, None, "tail", 0xA0), Action(3, 1, 2, None, "tail", 0xA0),   # 0x10 -> 0xA0 twice
         Action(3, 2, 3, None, "tail", 0xB0), Action(3, 3, 4, None, "tail", 0xC0),   # 0x20 meets two
         Action(9, 0, 6, None, "tail", 0xD0)]
    out, stats = M.pairs(a, b)
    assert out == [(0x10, 0xA0)]
    assert stats["shared"] == 4 and stats["only in A"] == 1 and stats["only in B"] == 1
    assert stats["handlers meeting several"] == 1
