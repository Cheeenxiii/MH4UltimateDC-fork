"""The analyser gives the same functions whatever Python's string hashing (no game data).

Function F calls Xi and Yi; Xi calls Zi, and Yi branches to Zi. If Yi is analysed before Xi
has discovered Zi, Yi's branch is a goto (Zi's code inlined in Yi), otherwise a tail call:
the order in which F's calls are queued decides, and it must not change from run to run.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "..", "tools")

PROGRAM = r"""
import struct, sys
sys.path.insert(0, sys.argv[1])
from recomp.analysis import Analyzer, Image
base = 0x100000
def bl(at, t): return 0xEB000000 | (((t - at - 8) >> 2) & 0xFFFFFF)
def b(at, t): return 0xEA000000 | (((t - at - 8) >> 2) & 0xFFFFFF)
# F calls X0..X7 and Y0..Y7; Xi calls Zi, Yi branches to Zi
F, n = base, 8
X = [base + 0x100 + 0x10 * i for i in range(n)]
Y = [base + 0x200 + 0x10 * i for i in range(n)]
Z = [base + 0x300 + 0x10 * i for i in range(n)]
words = {}
for k, t in enumerate(X + Y):
    words[F + 4 * k] = bl(F + 4 * k, t)
words[F + 4 * 2 * n] = 0xE12FFF1E
for i in range(n):
    words[X[i]], words[X[i] + 4] = bl(X[i], Z[i]), 0xE12FFF1E
    words[Y[i]] = b(Y[i], Z[i])
    words[Z[i]], words[Z[i] + 4] = 0xE3A00001, 0xE12FFF1E
code = bytearray(0x400)
for a, w in words.items():
    struct.pack_into("<I", code, a - base, w)
funcs = Analyzer(Image(bytes(code), base, len(code))).analyze_all({F: "arm"})
print(sorted((hex(a), len(f.insns)) for a, f in funcs.items()))
"""


def run(seed: str) -> str:
    env = dict(os.environ, PYTHONHASHSEED=seed)
    return subprocess.run([sys.executable, "-c", PROGRAM, TOOLS], env=env, capture_output=True,
                          text=True, check=True).stdout


def test_discovery_order_does_not_depend_on_hashing():
    outs = {run(seed) for seed in map(str, range(8))}
    assert len(outs) == 1, outs
