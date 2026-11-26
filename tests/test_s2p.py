"""S2P 元件测试：Touchstone 加载、插值、S→Y、错误处理。"""
from __future__ import annotations

import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.components import Component, _S2P_CACHE
from app.engine import Network, Port

FAIL = []


def check(name, cond, detail=""):
    print(("  [OK]   " if cond else "  [FAIL] ") + name + ("   " + detail if detail else ""))
    if not cond:
        FAIL.append(name)


def write_s2p(mag: float, freqs=(1.0, 2.0, 3.0)) -> str:
    p = os.path.join(tempfile.mkdtemp(), "dev.s2p")
    with open(p, "w") as fh:
        fh.write("! test\n# GHZ S MA R 50\n")
        for f in freqs:
            fh.write(f"{f} 0 0 {mag} 0 {mag} 0 0 0\n")
    return p


def main():
    print("== S2P 元件")
    path = write_s2p(0.501187)
    for f in (1e9, 1.5e9, 2e9, 3e9):
        n = Network(50)
        n.add(Component("X", "S2P", ["a", "b"], {"path": path, "z0": 50}))
        n.ports = [Port("P1", "a"), Port("P2", "b")]
        s = n.s_matrix(f)
        check(f"{f/1e9:g} GHz |S11|≈0", abs(s[0][0]) < 1e-9, f"{abs(s[0][0]):.2e}")
        check(f"{f/1e9:g} GHz |S21|=0.5012", abs(abs(s[1][0]) - 0.501187) < 1e-6,
              f"{abs(s[1][0]):.6f}")
    # 路径未指定
    try:
        Component("X", "S2P", ["a", "b"], {}).stamp(1e9)
    except ValueError as e:
        check("未指定文件时报错", "未指定" in str(e), str(e)[:40])
    else:
        check("未指定文件时报错", False)
    # 非 2 端口
    p3 = os.path.join(tempfile.mkdtemp(), "d3.s3p")
    with open(p3, "w") as fh:
        # 3 端口：freq + 9 个复数（18 个数）
        fh.write("# GHZ S MA R 50\n1 0 0 0.5 0 0.5 0 0 0 "
                 "0.5 0 0.5 0 0 0 0.5 0 0.5 0 0 0\n")
    try:
        Component("Y", "S2P", ["a", "b"], {"path": p3}).stamp(1e9)
    except ValueError as e:
        check("3 端口文件明确拒绝", "2 端口" in str(e), str(e)[:40])
    else:
        check("3 端口文件明确拒绝", False)
    # 缓存生效
    _S2P_CACHE.clear()
    n = Network(50)
    c = Component("X", "S2P", ["a", "b"], {"path": path})
    n.add(c)
    n.ports = [Port("P1", "a"), Port("P2", "b")]
    n.s_matrix(1e9); n.s_matrix(2e9)
    check("S2P 文件被缓存", len(_S2P_CACHE) == 1, str(len(_S2P_CACHE)))
    # 序列化保留字符串路径
    d = c.to_dict()
    c2 = Component.from_dict(d)
    check("序列化保留路径", isinstance(c2.params.get("path"), str))
    print()
    if FAIL:
        print(f"失败 {len(FAIL)} 项：" + ", ".join(FAIL)); return 1
    print("S2P 测试全部通过 ✔"); return 0


if __name__ == "__main__":
    raise SystemExit(main())