"""引擎物理正确性测试（用解析解对拍）。

运行：python -m tests.test_engine
"""
from __future__ import annotations

import cmath
import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.engine import Analysis, Network, Port
from app.components import Component, microstrip_synthesize, microstrip_z0_eeff

FAIL = []


def check(name, cond, detail=""):
    print(("  [OK]   " if cond else "  [FAIL] ") + name + ("   " + detail if detail else ""))
    if not cond:
        FAIL.append(name)


def net2(*comps, z0=50.0, ports=("P1", "P2")):
    n = Network(z0=z0)
    for c in comps:
        n.add(c)
    n.ports = [Port(ports[0], "n1"), Port(ports[1], "n2")]
    return n


def main():
    print("== 1. 串联电阻 R=50Ω（Z0=50）：S11=R/(R+2Z0)=1/3, S21=2/3")
    n = net2(Component("R1", "R", ["n1", "n2"], {"r": 50}))
    s = n.s_matrix(1e9)
    check("S11=1/3", abs(s[0][0] - 1 / 3) < 1e-12, f"{s[0][0]:.6f}")
    check("S21=2/3", abs(s[1][0] - 2 / 3) < 1e-12, f"{s[1][0]:.6f}")

    print("== 2. 并联电容 C（Z0=50）：S11=(1-jωCZ0)/(1+jωCZ0)")
    C = 2.0e-12
    f = 2e9
    n = net2(Component("C1", "C", ["n1", "0"], {"c": 2.0}))
    # 单端口网络：把两个端口接同一点没有意义，改为 1 端口
    n2 = Network(z0=50.0)
    n2.add(Component("C1", "C", ["n1", "0"], {"c": 2.0}))
    n2.ports = [Port("P1", "n1")]
    s11 = n2.s_matrix(f)[0][0]
    w = 2 * math.pi * f
    expect = (1 - 1j * w * C * 50) / (1 + 1j * w * C * 50)
    check("并联 C 解析解", abs(s11 - expect) < 1e-12, f"{s11:.6f} vs {expect:.6f}")
    check("|S11|=1（纯电抗）", abs(abs(s11) - 1) < 1e-12)

    print("== 3. 理想传输线 25mm@1GHz 匹配 → 全反射率为 0，插损 0dB")
    # 50Ω 线，两端 50Ω 系统
    n = net2(Component("T1", "TL", ["n1", "n2"], {"z0": 50, "er": 1.0, "len": 25.0}))
    s = n.s_matrix(1e9)
    check("Z0=50 线 S11≈0", abs(s[0][0]) < 1e-9, f"{abs(s[0][0]):.2e}")
    check("|S21|≈1", abs(abs(s[1][0]) - 1) < 1e-6, f"{abs(s[1][0]):.9f}")

    print("== 4. 50Ω 线取 λ/4（@1GHz）→ S11≈0，S21=-j（解析解）")
    L = 299792458.0 / 1e9 / 4 * 1e3
    n = net2(Component("T1", "TL", ["n1", "n2"], {"z0": 50.0, "er": 1.0, "len": L}))
    s = n.s_matrix(1e9)
    check("λ/4 线 S11≈0", abs(s[0][0]) < 1e-9, f"{abs(s[0][0]):.2e}")
    check("S21≈-j", abs(s[1][0] - (-1j)) < 1e-6, f"{s[1][0]:.6f}")

    print("== 4b. λ/4 阻抗变换器：50Ω 源经 70.71Ω λ/4 线到 100Ω 负载 → S11≈0")
    n = Network(z0=50.0)
    n.add(Component("T1", "TL", ["n1", "n2"], {"z0": 70.7107, "er": 1.0, "len": L}))
    n.add(Component("R1", "R", ["n2", "0"], {"r": 100.0}))
    n.ports = [Port("P1", "n1")]
    s = n.s_matrix(1e9)
    check("变换器匹配 S11≈0", abs(s[0][0]) < 1e-4, f"{abs(s[0][0]):.2e}")

    print("== 5. 微带综合/分析自洽（FR4: εr=4.4, h=0.5mm）")
    w = microstrip_synthesize(50.0, 0.5, 4.4)
    z, ee = microstrip_z0_eeff(w, 0.5, 4.4)
    check("综合→分析回到 50Ω", abs(z - 50) < 0.05, f"W={w:.4f}mm → Z0={z:.4f}")
    check("有效介电常数合理", 3.0 < ee < 4.4, f"εeff={ee:.4f}")
    w2 = microstrip_synthesize(75.0, 0.5, 4.4)
    check("75Ω 线更窄", w2 < w, f"{w2:.4f} < {w:.4f}")

    print("== 6. 三端口等分功分器（Wilkinson 型：2×70.7Ω λ/4 + 100Ω 隔离电阻）")
    Lq = 299792458.0 / 2e9 / 4 * 1e3 / math.sqrt(1.0)  # 2GHz, er=1（理想线）
    n = Network(z0=50.0)
    n.add(Component("T1", "TL", ["p1", "p2"], {"z0": 70.7107, "er": 1.0, "len": Lq}))
    n.add(Component("T2", "TL", ["p1", "p3"], {"z0": 70.7107, "er": 1.0, "len": Lq}))
    n.add(Component("R1", "R", ["p2", "p3"], {"r": 100.0}))
    n.ports = [Port("P1", "p1"), Port("P2", "p2"), Port("P3", "p3")]
    s = n.s_matrix(2e9)
    check("输入匹配 |S11|≈0", abs(s[0][0]) < 1e-6, f"{abs(s[0][0]):.2e}")
    check("等分 -3dB（|S21|=1/√2）", abs(abs(s[1][0]) - 1 / math.sqrt(2)) < 1e-6,
          f"{abs(s[1][0]):.6f}")
    check("输出隔离 |S32|≈0", abs(s[2][1]) < 1e-6, f"{abs(s[2][1]):.2e}")

    print("== 7. 扫频与结果结构")
    n = net2(Component("R1", "R", ["n1", "n2"], {"r": 10}))
    r = n.sweep(Analysis(1, 3, 5))
    check("频点数=5", len(r.freqs) == 5)
    # 串联 R=10Ω 于 50Ω 系统：S21 = 2Z0/(R+2Z0) = 100/110
    check("S21_dB 与公式一致", abs(r.db(2, 1)[0] - 20 * math.log10(100 / 110)) < 1e-9,
          f"{r.db(2, 1)[0]:.4f} vs {20 * math.log10(100 / 110):.4f}")

    print()
    if FAIL:
        print(f"失败 {len(FAIL)} 项：" + ", ".join(FAIL))
        return 1
    print("全部通过 ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())