"""拓扑回归：1..6 阶低通 / 1..4 阶带通都必须能解、且 P2 不悬空。

这是修复"偶数阶以并联元件收尾导致 P2 悬空"的回归测试。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.builders import ladder_to_network
from app.engine import Analysis
from app.synthesis import bandpass_lc, lowpass_lc

FAIL = []


def check(name, cond, detail=""):
    print(("  [OK]   " if cond else "  [FAIL] ") + name + ("   " + detail if detail else ""))
    if not cond:
        FAIL.append(name)


def main():
    print("== 低通 n=1..6（奇偶都要能解）")
    for n in range(1, 7):
        net = ladder_to_network(lowpass_lc(n, 3e9, 50.0, 0.5), 50.0)
        nodes = set()
        for c in net.components:
            nodes.update(x for x in c.nodes if x != "0")
        p2 = net.ports[1].node
        check(f"n={n} P2 节点在电路内", p2 in nodes or len(net.components) == 1,
              f"P2→{p2}")
        try:
            res = net.sweep(Analysis(0.5, 6, 21))
            il = res.db(2, 1)[3]
            check(f"n={n} 可解且 DC 附近插损>-1dB", il > -1.0, f"{il:.3f} dB")
        except Exception as e:  # noqa: BLE001
            check(f"n={n} 可解", False, str(e))

    print("== 带通 n=1..4")
    for n in range(1, 5):
        net = ladder_to_network(bandpass_lc(n, 2.3e9, 2.7e9, 50.0, 0.5), 50.0)
        try:
            res = net.sweep(Analysis(1.5, 3.5, 101))
            k = len(res.freqs) // 2
            il = res.db(2, 1)[k]
            check(f"n={n} 中心插损 > -1dB", il > -1.0, f"{il:.3f} dB")
        except Exception as e:  # noqa: BLE001
            check(f"n={n} 可解", False, str(e))

    print()
    if FAIL:
        print(f"失败 {len(FAIL)} 项：" + ", ".join(FAIL))
        return 1
    print("全部通过 ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
