"""IO 与综合测试：Touchstone 往返、工程存取、带通响应、微带线匹配。"""
from __future__ import annotations

import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.components import Component
from app.engine import Analysis, Network, Port
from app.project import Project, new_demo_project
from app.synthesis import bandpass_lc, lowpass_lc
from app.touchstone import read_touchstone, write_touchstone

FAIL = []


def check(name, cond, detail=""):
    print(("  [OK]   " if cond else "  [FAIL] ") + name + ("   " + detail if detail else ""))
    if not cond:
        FAIL.append(name)


def build_ladder(items, z0):
    """把 lowpass_lc/bandpass_lc 的条目装配成 Network（带通用 pair 分组）。"""
    net = Network(z0)
    prev = "n1"
    if "pair" not in items[0]:
        for k, it in enumerate(items):
            kind, val = it["kind"], it["value"]
            if it["shunt"]:
                net.add(Component(net.next_id(kind), kind, [prev, "0"], {kind.lower(): val}))
            else:
                nxt = "n2" if k == len(items) - 1 else f"m{k}"
                net.add(Component(net.next_id(kind), kind, [prev, nxt], {kind.lower(): val}))
                prev = nxt
    else:
        groups = {}
        for it in items:
            groups.setdefault(it["pair"], []).append(it)
        keys = sorted(groups)
        for gi, key in enumerate(keys):
            grp = groups[key]
            if grp[0]["shunt"]:
                c = next(x for x in grp if x["kind"] == "C")
                l = next(x for x in grp if x["kind"] == "L")
                net.add(Component(net.next_id("C"), "C", [prev, "0"], {"c": c["value"]}))
                net.add(Component(net.next_id("L"), "L", [prev, "0"], {"l": l["value"]}))
            else:
                mid = f"bp{gi}"
                nxt = "n2" if gi == len(keys) - 1 else f"s{gi}"
                net.add(Component(net.next_id("L"), "L", [prev, mid], {"l": grp[0]["value"]}))
                net.add(Component(net.next_id("C"), "C", [mid, nxt], {"c": grp[1]["value"]}))
                prev = nxt
    net.ports = [Port("P1", "n1"), Port("P2", "n2")]
    return net


def main():
    tmp = tempfile.mkdtemp(prefix="basearw_test_")

    print("== 1. Touchstone 往返（MA/DB/RI，频率单位 GHz/MHz）")
    p = new_demo_project()
    res = p.network.sweep(Analysis(0.5, 6.0, 41))
    for fmt in ("MA", "DB", "RI"):
        path = os.path.join(tmp, f"rt_{fmt}.s2p")
        write_touchstone(path, res.freqs, res.s, 50.0, fmt=fmt)
        f2, s2, z0, n = read_touchstone(path)
        err = 0.0
        for k in range(len(f2)):
            for i in range(2):
                for j in range(2):
                    err = max(err, abs(s2[k][i][j] - res.s[k][i][j]))
        check(f"格式 {fmt} 往返误差 < 1e-6", err < 1e-6, f"max err={err:.2e}")
        check(f"格式 {fmt} 频点与端口数一致", len(f2) == len(res.freqs) and n == 2)

    # 频率单位 MHz
    path = os.path.join(tmp, "unit.s2p")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# MHz S RI R 50\n1000 0.5 0.0 0.5 0.0 0.5 0.0 0.5 0.0\n")
    f3, s3, _, _ = read_touchstone(path)
    check("MHz 单位换算正确", abs(f3[0] - 1e9) < 1e-6, f"{f3[0]:.0f} Hz")

    print("== 2. 工程保存/读取往返")
    jp = os.path.join(tmp, "proj.json")
    p.save(jp)
    q = Project.load(jp)
    check("元件数量一致", len(q.network.components) == len(p.network.components))
    check("分析设置一致", q.analysis.points == p.analysis.points and
          abs(q.analysis.stop_ghz - p.analysis.stop_ghz) < 1e-12)
    r1 = p.network.sweep(Analysis(1, 5, 21))
    r2 = q.network.sweep(Analysis(1, 5, 21))
    err = max(abs(a - b) for k in range(len(r1.freqs)) for i in range(2)
              for j in range(2) for a, b in [(r1.s[k][i][j], r2.s[k][i][j])])
    check("工程往返后结果一致", err < 1e-9, f"{err:.2e}")

    print("== 3. 3 阶带通 2.3–2.7 GHz（0.5dB 纹波）：通带插损 ≈0dB，带外抑制")
    net = build_ladder(bandpass_lc(3, 2.3e9, 2.7e9, 50.0, 0.5), 50.0)
    res = net.sweep(Analysis(1.0, 4.0, 601))
    def at(f):
        k = min(range(len(res.freqs)), key=lambda i: abs(res.freqs[i] - f))
        return res.db(2, 1)[k], res.db(1, 1)[k]
    il, rl = at(2.5e9)
    check("中心插损 > -1.0 dB", il > -1.0, f"{il:.3f} dB")
    check("中心回波损耗 < -10 dB", rl < -10.0, f"{rl:.2f} dB")
    il1, _ = at(1.5e9)
    il4, _ = at(3.6e9)
    check("1.5GHz 抑制 > 20 dB", il1 < -20, f"{il1:.1f} dB")
    check("3.6GHz 抑制 > 20 dB", il4 < -20, f"{il4:.1f} dB")

    print("== 4. 微带线：50Ω 线在匹配系统中反射极小")
    from app.components import microstrip_synthesize, microstrip_z0_eeff
    w = microstrip_synthesize(50.0, 0.508, 3.55)
    _, ee = microstrip_z0_eeff(w, 0.508, 3.55)
    net = Network(50.0)
    net.add(Component("MS1", "MS", ["n1", "n2"],
                      {"w": w, "h": 0.508, "er": 3.55, "len": 20.0, "loss": 0.0}))
    net.ports = [Port("P1", "n1"), Port("P2", "n2")]
    res = net.sweep(Analysis(1, 6, 101))
    worst = max(abs(x) for x in res.s_ij(1, 1))
    check("微带线 S11 < -30 dB", worst < 1e-3, f"max|S11|={worst:.2e}")
    check("损耗≈0（无损）", min(res.db(2, 1)) > -0.2, f"min |S21|={min(res.db(2,1)):.3f} dB")

    print("== 5. 低通综合阶数递增 → 阻带更陡")
    def il_at(order, f):
        n2 = build_ladder(lowpass_lc(order, 3e9, 50, 0.5), 50.0)
        r = n2.sweep(Analysis(f, f, 2))
        return r.db(2, 1)[0]
    a3, a5 = il_at(3, 4.5e9), il_at(5, 4.5e9)
    check("5 阶比 3 阶抑制更好", a5 < a3, f"{a5:.1f} dB < {a3:.1f} dB")

    print()
    if FAIL:
        print(f"失败 {len(FAIL)} 项：" + ", ".join(FAIL))
        return 1
    print("全部通过 ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
