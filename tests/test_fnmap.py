"""tools/fnmap.py on synthetic functions (no game data)."""
import os
import random
import struct
import sys
from array import array

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import fnmap
from fnmap import Fn, Mapper, Side


def body(seed, n=30):
    rnd = random.Random(seed)
    return [rnd.randrange(1, 50) for _ in range(n)]


def fn(seq, sites=()):
    return Fn(array("I", seq), list(sites))


def mutate(seq, seed, k=3):
    rnd = random.Random(seed)
    s = list(seq)
    for _ in range(k):
        s[rnd.randrange(len(s))] = 99
    return s


def test_tokens_drop_registers_and_immediates():
    # ldr r1, [r0, #4]; ldr r3, [r2, #0x40]; bl +0x10 -- the two loads give one token
    code = struct.pack("<3I", 0xE5901004, 0xE5923040, 0xEB000002)
    toks = fnmap.tokens(code, 0x100000, "arm", [0x100000, 0x100004, 0x100008])
    assert toks[0] == toks[1] == ("ldr r,[r]", None)
    assert toks[2] == ("CALL", 0x100008 + 8 + 8)


def test_side_from_analysis_on_real_arm():
    from recomp.analysis import Analyzer, Image
    # f: bl g; bx lr      g: mov r0, #1; bx lr
    code = struct.pack("<4I", 0xEB000000, 0xE12FFF1E, 0xE3A00001, 0xE12FFF1E)
    img = Image(code, 0x100000, len(code))
    an = Analyzer(img)
    funcs = an.analyze_all({0x100000: "arm", 0x100008: "arm"})
    side = fnmap.side_from_analysis("t", funcs, code, 0x100000)
    assert side.fns[0x100000].sites == [(0, 0x100008)]
    assert len(side.fns[0x100008].seq) == 2


def test_anchors_need_unique_identical_bodies():
    a = Side("a", {1: fn(body(1)), 2: fn(body(2)), 3: fn(body(3)), 4: fn(body(3))})
    b = Side("b", {10: fn(body(1)), 20: fn(body(2)), 30: fn(body(3)), 40: fn(body(9, 5))})
    mp = Mapper(a, b)
    assert mp.anchors() == 2            # body 3 appears twice in a: not an anchor
    assert mp.m == {1: 10, 2: 20}


def test_short_identical_bodies_are_not_anchors():
    a = Side("a", {1: fn(body(1, 8))})
    b = Side("b", {10: fn(body(1, 8))})
    assert Mapper(a, b).anchors() == 0


def test_propagation_through_aligned_calls():
    # a1 (anchor) calls a2 then a3; b1 calls b2 then b3. a2/b2 differ a little.
    caller = body(1, 40)
    a = Side("a", {1: fn(caller, [(5, 2), (20, 3)]), 2: fn(body(2)), 3: fn(body(3)),
                   4: fn(body(4))})
    b = Side("b", {10: fn(caller, [(5, 20), (20, 30)]), 20: fn(mutate(body(2), 1)),
                   30: fn(body(3)), 40: fn(body(4))})
    mp = Mapper(a, b)
    mp.anchors()
    assert 1 in mp.m and mp.m[1] == 10
    mp.propagate()
    assert mp.m[2] == 20 and mp.how[2].startswith("call")
    assert mp.m[3] == 30


def test_propagation_rejects_unlike_callees():
    caller = body(1, 40)
    a = Side("a", {1: fn(caller, [(5, 2)]), 2: fn(body(2))})
    b = Side("b", {10: fn(caller, [(5, 20)]), 20: fn(body(7))})
    mp = Mapper(a, b)
    mp.anchors()
    mp.propagate()
    assert 2 not in mp.m


def test_propagation_through_a_similar_pair():
    # the callers aren't identical (anchors), but alike enough to vote
    ca = body(1, 60)
    cb = mutate(ca, 5, 6)
    a = Side("a", {1: fn(ca, [(10, 2)]), 2: fn(body(2))})
    b = Side("b", {10: fn(cb, [(10, 20)]), 20: fn(body(2))})
    mp = Mapper(a, b)
    mp.add(1, 10, "given")
    mp.propagate()
    assert mp.m[2] == 20


def test_similar_takes_only_clear_matches():
    target = body(1, 60)
    a = Side("a", {1: fn(target), 2: fn(body(2, 60))})
    b = Side("b", {10: fn(mutate(target, 3, 4)),          # close to a1
                   20: fn(mutate(body(2, 60), 4, 4)),      # close to a2 ...
                   30: fn(mutate(body(2, 60), 5, 4))})     # ... and so is this one
    mp = Mapper(a, b)
    mp.similar([1, 2])
    assert mp.m.get(1) == 10 and mp.how[1].startswith("similar")
    assert 2 not in mp.m                # two equally good candidates: not clear


def test_is_clear():
    assert fnmap.is_clear([(0.9, 1), (0.7, 2)])
    assert not fnmap.is_clear([(0.9, 1), (0.85, 2)])
    assert not fnmap.is_clear([(0.6, 1)])
    assert fnmap.is_clear([(0.75, 1)])
    assert not fnmap.is_clear([])


def test_external_targets_are_kept_apart():
    toks = [("CALL", 0x200), ("mov r,#", None), ("CALL", 0x300)]
    owner = {0x200: 0x200, 0x300: 0x300}.get
    f = fnmap.make_fn(toks, 0x100, owner, external={0x300: 0x00500000}.get)   # asked per target
    assert f.sites == [(0, 0x200)]
    assert f.external == [0x00500000]


def test_side_round_trip(tmp_path):
    side = Side("t", {1: Fn(array("I", [3, 4, 5]), [(0, 2)], [0x500000]), 2: fn([7])})
    p = str(tmp_path / "t.side")
    fnmap.save_side(side, p)
    back = fnmap.load_side(p)
    assert back.name == "t"
    assert back.fns[1].seq == array("I", [3, 4, 5]) and back.fns[1].sites == [(0, 2)]
    assert back.fns[1].external == [0x500000] and back.fns[2].seq == array("I", [7])
