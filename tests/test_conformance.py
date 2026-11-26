"""一致性测试：单位、传输线计算、元件目录、反向计算、原理图、品牌审计。

Golden 值来源：同轴/微带/带状线的公开公式与工程常用设计值；L 型匹配与
S 参数结果用本软件引擎交叉验证（构建电路 → 看 |S11| 是否回到 0）。
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import catalog, inverse, tline, units
from app.builders import ladder_to_network
from app.components import Component
from app.engine import Analysis, Network, Port
from app.synthesis import lowpass_lc

FAIL = []


def check(name, cond, detail=""):
    print(("  [OK]   " if cond else "  [FAIL] ") + name + ("   " + detail if detail else ""))
    if not cond:
        FAIL.append(name)


# ------------------------------------------------------------------ 1 单位
def test_units():
    print("== 1. 单位换算")
    check("10 mil = 0.254 mm", abs(units.length_to_mm(10, "mil") - 0.254) < 1e-12)
    check("1 inch = 25.4 mm", abs(units.length_to_mm(1, "inch") - 25.4) < 1e-12)
    check("mm→mil→mm 往返", abs(units.length_from_mm(units.length_to_mm(3.7, "mil"), "mil") - 3.7) < 1e-12)
    check("2.4 GHz = 2400 MHz",
          abs(units.freq_to_hz(2.4, "GHz") - units.freq_to_hz(2400, "MHz")) < 1e-6)
    check("540 kHz = 0.00054 GHz", abs(units.freq_to_hz(540, "kHz") / 1e9 - 0.00054) < 1e-12)


# ------------------------------------------------------------------ 2 传输线
def test_lines():
    print("== 2. 传输线计算")
    for d, D, er in [(0.91, 3.04, 2.1), (1.0, 4.6, 1.0), (0.5, 2.0, 2.3)]:
        expect = 60.0 / math.sqrt(er) * math.log(D / d)
        got = tline.coax_z0(d, D, er)
        check(f"同轴 D/d={D}/{d} εr={er}", abs(got - expect) < 1e-9,
              f"{got:.6f} vs {expect:.6f}")
    d = tline.coax_design(50.0, 0.91, 2.1)
    check("同轴 50Ω 综合回代",
          abs(tline.coax_z0(0.91, d["d_out_mm"], 2.1) - 50.0) < 1e-6,
          f"D={d['d_out_mm']:.4f} mm")
    ms = tline.microstrip_design(50.0, 1.6, 4.4)
    check("微带 FR-4 1.6mm 50Ω → W≈3.0mm（±10%）", abs(ms["w_mm"] - 3.0) <= 0.3,
          f"W={ms['w_mm']:.4f} mm")
    check("微带 εeff 合理", 3.0 < ms["eeff"] < 4.4, f"{ms['eeff']:.4f}")
    q = tline.microstrip(ms["w_mm"], 1.6, 4.4, 2.4e9)
    check("λ/4 电长度 = 90°",
          abs(tline.electrical_length_deg(q["quarter_mm"], q["eeff"], 2.4e9) - 90.0) < 1e-6)
    sl = tline.stripline_design(50.0, 1.6, 4.4)
    check("带状线 FR-4 b=1.6mm 50Ω → W≈0.66mm（±20%）", abs(sl["w_mm"] - 0.66) <= 0.13,
          f"W={sl['w_mm']:.4f} mm")
    check("带状线综合回代 50Ω",
          abs(tline.stripline_z0(sl["w_mm"], 1.6, 4.4) - 50.0) < 1e-6)
    check("带状线单调性：线宽↑ Z0↓",
          tline.stripline_z0(1.5, 1.6, 4.4) < tline.stripline_z0(0.4, 1.6, 4.4))


# ------------------------------------------------------------------ 3 目录
def test_catalog():
    print("== 3. 元件目录与测量项")
    ready = catalog.ready_codes()
    check("已实现元件 ≥ 8 个", len(ready) >= 8, str(ready))
    bad = [k for k, v in catalog.ELEMENT_CATALOG.items()
           if v["status"] == "ready" and not v.get("kind")]
    check("已实现元件都有内部 kind", not bad, str(bad))
    check("规划元件不含 kind",
          all("kind" not in x for x in catalog.PLANNED_ELEMENTS))
    for kind, code in catalog.KIND_CODE.items():
        check(f"kind {kind} ↔ 代号 {code}", catalog.kind_for_code(code) == kind)
    for name in ("S 参数", "驻波比", "回波损耗", "插入损耗", "线性增益", "稳定性", "群时延"):
        check(f"测量「{name}」可用", catalog.measurement_status(name) == "ok")
    for name in ("噪声系数", "互调", "增益压缩", "负载牵引"):
        check(f"测量「{name}」标注未实现", catalog.measurement_status(name) == "missing")
    check("术语表不含第三方工具名",
          not any("TX" in g["en"] or "TX" in g["cn"] for g in catalog.GLOSSARY))


# ------------------------------------------------------------------ 4 LC 反算
def test_lc():
    print("== 4. LC 谐振与改频")
    r = inverse.lc_resonance(2.4e9, l_nh=10.0)
    c_expected = 1.0 / ((2 * math.pi * 2.4e9) ** 2 * 10e-9) * 1e12
    check("给定 f0、L 求 C", abs(r["c_pf"] - c_expected) < 1e-9,
          f"C={r['c_pf']:.6f} pF")
    r2 = inverse.lc_resonance(2.4e9, c_pf=0.4397620818)
    check("给定 f0、C 求 L", abs(r2["l_nh"] - 10.0) < 1e-6, f"L={r2['l_nh']:.6f} nH")
    r3 = inverse.lc_resonance(l_nh=10.0, c_pf=0.4397620818)
    check("由 L、C 求 f0", abs(r3["f_hz"] - 2.4e9) < 1e3, f"{r3['f_hz']/1e9:.6f} GHz")
    rt = inverse.retune_lc(4.2344, 1.16361, 2.5e9, keep="L")
    check("改频校验误差为 0", abs(rt["error_hz"]) < 1e-3, f"{rt['error_hz']:.3e} Hz")
    check("改频后 C 变化方向正确", rt["delta_pf"] < 0, f"{rt['delta_pf']:.4g} pF")
    rt2 = inverse.retune_lc(4.2344, 1.16361, 2.5e9, keep="C")
    check("保留 C 时 L 校验通过", abs(rt2["error_hz"]) < 1e-3)


# ------------------------------------------------------------------ 5 匹配
def _build_match(rs, rl, sol, side):
    net = Network(rs)

    def key(e):
        return "l" if e["kind"] == "L" else "c"

    sh, se = sol["shunt"], sol["series"]
    if side == "load":
        net.add(Component("XS", se["kind"], ["n1", "a"], {key(se): se["value"]}))
        net.add(Component("XP", sh["kind"], ["a", "0"], {key(sh): sh["value"]}))
        net.add(Component("RL", "R", ["a", "0"], {"r": rl}))
    else:
        net.add(Component("XP", sh["kind"], ["n1", "0"], {key(sh): sh["value"]}))
        net.add(Component("XS", se["kind"], ["n1", "a"], {key(se): se["value"]}))
        net.add(Component("RL", "R", ["a", "0"], {"r": rl}))
    net.ports = [Port("P1", "n1")]
    return net


def test_matching():
    print("== 5. L 型匹配（用引擎验证 |S11|→0）")
    for rs, rl in [(50, 100), (100, 50), (50, 25), (75, 50)]:
        m = inverse.l_network_match(rs, rl, 2.4e9)
        check(f"Rs={rs} Rl={rl} 给出两种解", len(m["solutions"]) == 2)
        for sol in m["solutions"]:
            s11 = _build_match(rs, rl, sol, m["shunt_side"]).s_matrix(2.4e9)[0][0]
            check(f"  {sol['name']} |S11|<1e-9", abs(s11) < 1e-9, f"{abs(s11):.2e}")
        check(f"  Q 值 = √(Rhigh/Rlow−1)",
              abs(m["q"] - math.sqrt(max(rs, rl) / min(rs, rl) - 1)) < 1e-12)
    ident = inverse.l_network_match(50, 50, 2.4e9)
    check("等阻抗时提示无需匹配", ident["identity"] and not ident["solutions"])


# ------------------------------------------------------------------ 6 S11 反算
def test_from_s11():
    print("== 6. 由 S11 反算")
    g = (100 - 50) / (100 + 50)      # 100Ω 负载
    r = inverse.match_from_s11(g, 2.4e9)
    check("Zin 反算 = 100 Ω", abs(r["zin"] - 100) < 1e-6, f"{r['zin']:.6f}")
    check("VSWR = 2", abs(r["vswr"] - 2.0) < 1e-9, f"{r['vswr']:.6f}")
    check("实部偏离 Z0 时两种单元件方案都不适用",
          r["series"] is None and r["shunt"] is None)
    # 构造 Zin = 50 - j50 → Γ = (Z-Z0)/(Z+Z0)
    z = complex(50, -50)
    g2 = (z - 50) / (z + 50)
    r2 = inverse.match_from_s11(g2, 2.4e9)
    check("Zin = 50−j50 时给出串联方案", r2["series"] is not None)
    if r2["series"]:
        check("串联元件为电感（抵消容性）", r2["series"]["kind"] == "L")
        X = r2["series"]["x_ohm"]
        check("所需串联 X = +50 Ω", abs(X - 50) < 1e-6, f"{X:.6f}")
        # 引擎验证：串联该电感后输入阻抗回到 50Ω
        net = Network(50)
        net.add(Component("X1", "L", ["n1", "a"], {"l": r2["series"]["value"]}))
        net.add(Component("RL", "R", ["a", "0"], {"r": abs(z) ** 2 / z.real}))
        net.ports = [Port("P1", "n1")]
        # 负载用等效串联组合更直接：R=50 与 C 串联
        net2 = Network(50)
        net2.add(Component("X1", "L", ["n1", "a"], {"l": r2["series"]["value"]}))
        net2.add(Component("C1", "C", ["a", "b"], {"c": 1.0 / (2 * math.pi * 2.4e9 * 50) * 1e12}))
        net2.add(Component("R1", "R", ["b", "0"], {"r": 50}))
        net2.ports = [Port("P1", "n1")]
        s11 = net2.s_matrix(2.4e9)[0][0]
        check("引擎验证：串 L 后 |S11|≈0", abs(s11) < 1e-6, f"{abs(s11):.2e}")


# ------------------------------------------------------------------ 7 滤波器改频
def test_scale():
    print("== 7. 滤波器改频缩放")
    items = lowpass_lc(3, 3e9, 50, 0.5)
    scaled = inverse.scale_filter_values(items, 3e9, 2e9)
    k = 1.5
    check("L、C 同比例缩放 k=1.5",
          all(abs(s["value"] - s["value_old"] * k) < 1e-12 for s in scaled))
    net_old = ladder_to_network(items, 50)
    net_new = ladder_to_network(scaled, 50)
    def il(net, f):
        # Analysis 的频率字段单位是 GHz
        r = net.sweep(Analysis(f / 1e9, f / 1e9, 2))
        return r.db(2, 1)[0]
    check("改频后 2 GHz 处仍通带（插损 > −1 dB）", il(net_new, 2e9) > -1.0,
          f"{il(net_new, 2e9):.2f} dB")
    check("原 3 GHz 设计在 6 GHz 已明显衰减",
          il(net_old, 6e9) < -15, f"{il(net_old, 6e9):.1f} dB")


# ------------------------------------------------------------------ 8 界面
def test_ui():
    print("== 8. 界面集成：原理图页签 + 反向计算对话框")
    import time
    from app.ui import dialogs
    from app.ui.app import App, APP_NAME

    check("程序名不含旧品牌",
          ("Base_" + "AWR") not in APP_NAME and ("A" + "WR") not in APP_NAME, APP_NAME)
    app = App()
    app.withdraw()
    try:
        for _ in range(12):
            app.update()
            time.sleep(0.1)
            if app.result is not None:
                break
        check("自动仿真完成", app.result is not None)
        check("存在原理图页签", app.nb.index("end") >= 4, str(app.nb.index("end")))
        check("原理图已绘制图元", len(app.sch.find_all()) > 20,
              str(len(app.sch.find_all())))
        dlg = dialogs.InverseDialog(app)
        dlg.withdraw()
        dlg.vars["lc"]["电感 L (nH)"].set("10")
        dlg.calc_lc()
        check("LC 反算按钮可用", "LC 谐振" in dlg.out.get("1.0", "end"))
        dlg.calc_match()
        check("L 型匹配按钮可用", "L 型匹配" in dlg.out.get("1.0", "end"))
        dlg.calc_s11()
        check("S11 反算按钮可用", "由 S11 反算" in dlg.out.get("1.0", "end"))
        dlg.destroy()
        dlg2 = dialogs.TransmissionLineDialog(app)
        dlg2.withdraw()
        dlg2.ms_design()
        check("传输线计算器可用", "微带线综合" in dlg2.out.get("1.0", "end"))
        dlg2.destroy()
    finally:
        app.destroy()


# ------------------------------------------------------------------ 8.5 巴伦
def test_balun():
    print("== 8.5 1:4 巴伦（威尔金森 + λ/4 变换 + λ/4 移相）")
    import cmath
    from app.balun import build_network, design_1to4
    f = 2.4e9
    d = design_1to4(f, 50)
    check("分支线阻抗 70.71 Ω", abs(d["branch_z0"] - 70.7107) < 1e-3,
          f"{d['branch_z0']:.4f}")
    check("λ/4 长度 ≈31.23 mm", abs(d["quarter_mm"] - 31.228) < 0.01,
          f"{d['quarter_mm']:.3f}")
    n = build_network(f, 50)
    check("三端口（P1/P2/P3）", [p.pid for p in n.ports] == ["P1", "P2", "P3"])
    check("端口阻抗 50/100/100", [p.effective_z0(50) for p in n.ports] == [50, 100, 100])
    s = n.s_matrix(f)
    s11 = 20 * math.log10(abs(s[0][0]) + 1e-30)
    s21 = 20 * math.log10(abs(s[1][0]) + 1e-30)
    s31 = 20 * math.log10(abs(s[2][0]) + 1e-30)
    ph = math.degrees(cmath.phase(s[1][0]) - cmath.phase(s[2][0]))
    while ph <= -180: ph += 360
    check("中心 S11 < -100 dB", s11 < -100, f"{s11:.1f} dB")
    check("两路 |S21|、|S31| = -3.01 dB", abs(s21 + 3.0103) < 0.05 and
          abs(s31 + 3.0103) < 0.05, f"{s21:.2f}/{s31:.2f}")
    check("相位差 180°", abs(abs(ph) - 180) < 0.5, f"{ph:.1f}°")
    r = n.sweep(Analysis(2.0, 2.8, 5))
    check("偏离中心后失配（2.0 GHz S11 > -20 dB）", r.db(1, 1)[0] > -20,
          f"{r.db(1, 1)[0]:.1f} dB")


def test_double_stub():
    print("== 8.6 双枝节匹配（间距 λ/8）")
    from app import matching
    from app.components import Component
    from app.engine import Network, Port
    f = 2.4e9
    for zl in (100 + 0j, 50 + 30j, 10 - 20j):
        s = matching.double_stub(zl, 50, f, spacing_lambda=0.125)
        check(f"ZL={zl} 给出 d1/stub", s["d1_mm"] > 0 and s["stub1_mm"] > 0)
        n = Network(50)
        n.add(Component("TL2", "TL", ["p", "A"], {"z0": 50, "er": 1.0, "len": s["d12_mm"]}))
        n.add(Component("ST2", "TL", ["p", "0"], {"z0": 50, "er": 1.0, "len": s["stub2_mm"]}))
        n.add(Component("TL1", "TL", ["A", "L"], {"z0": 50, "er": 1.0, "len": s["d1_mm"]}))
        n.add(Component("ST1", "TL", ["A", "0"], {"z0": 50, "er": 1.0, "len": s["stub1_mm"]}))
        n.add(Component("LD_R", "R", ["L", "b"], {"r": max(zl.real, 1e-6)}))
        if zl.imag >= 0:
            n.add(Component("LD_X", "L", ["b", "0"],
                            {"l": zl.imag / (2 * math.pi * f) * 1e9}))
        else:
            n.add(Component("LD_X", "C", ["b", "0"],
                            {"c": 1 / (2 * math.pi * f * abs(zl.imag)) * 1e12}))
        n.ports = [Port("P1", "p")]
        s11 = n.s_matrix(f)[0][0]
        check(f"  ZL={zl} 回代 |S11| < -100 dB", abs(s11) < 1e-5,
              f"{20*math.log10(abs(s11)+1e-30):.1f} dB")


def test_rlc():
    print("== 8.7 RLC 谐振元件（串联/并联）")
    from app.components import Component
    from app.engine import Network, Port
    f0 = 1e6
    l_nh, c_pf = 100.0, 253302.9
    for kind, expect in (("RLCS", 2/3), ("RLCP", 2/3)):
        n = Network(50)
        n.add(Component("X", kind, ["a", "b"], {"r": 50, "l": l_nh, "c": c_pf}))
        n.ports = [Port("P1", "a"), Port("P2", "b")]
        s21 = abs(n.s_matrix(f0)[1][0])
        check(f"{kind} 谐振点 |S21|≈{expect:.3f}", abs(s21 - expect) < 0.02,
              f"{s21:.4f}")
        n1 = Network(50)
        n1.add(Component("X", kind, ["a", "0"], {"r": 50, "l": l_nh, "c": c_pf}))
        n1.ports = [Port("P1", "a")]
        s11 = abs(n1.s_matrix(f0)[0][0])
        check(f"{kind} 谐振点 |S11|≈0", s11 < 1e-3, f"{s11:.2e}")


# ------------------------------------------------------------------ 9 品牌审计
def test_brand_audit():
    print("== 9. 品牌审计（源码/文档不得含旧品牌与第三方工具名）")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # 拆开拼装，避免本文件命中自身
    tokens = ["A" + "WR", "Cad" + "ence", "Microwave" + " Office",
              "TX" + "Line", "Base_" + "AWR", "ML" + "IN"]
    exts = {".py", ".md", ".txt", ".cmd", ".spec", ".json"}
    skip_dirs = {"dist", "build", "__pycache__", "assets", ".git"}
    self_path = os.path.abspath(__file__)
    hits = []
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in skip_dirs]
        for f in fn:
            p = os.path.join(dp, f)
            if os.path.abspath(p) == self_path:
                continue
            if os.path.splitext(f)[1].lower() not in exts:
                continue
            try:
                t = open(p, encoding="utf-8").read()
            except Exception:
                continue
            for tok in tokens:
                if tok in t:
                    hits.append(f"{os.path.relpath(p, root)}:{tok}")
    check("无旧品牌/第三方工具名残留", not hits, "; ".join(hits[:8]))


def main():
    test_units()
    test_lines()
    test_catalog()
    test_lc()
    test_matching()
    test_from_s11()
    test_scale()
    test_ui()
    test_balun()
    test_double_stub()
    test_rlc()
    test_brand_audit()
    print()
    if FAIL:
        print(f"失败 {len(FAIL)} 项：" + ", ".join(FAIL))
        return 1
    print("一致性测试全部通过 ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())