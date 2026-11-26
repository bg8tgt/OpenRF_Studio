# -*- coding: utf-8 -*-
"""技能层测试：注册表、滤波器综合、匹配设计、曲线解读、参数解析、派发。

全部为纯计算，不需要 GUI、不需要网络、不需要模型。
"""
from __future__ import annotations

import math
import sys

_ok = [0]
_fail = [0]


def check(name, cond, detail=""):
    if cond:
        _ok[0] += 1
        print("  [OK]   %-34s %s" % (name, detail))
    else:
        _fail[0] += 1
        print("  [FAIL] %-34s %s" % (name, detail))


def close(a, b, tol=1e-6):
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def main():
    from app.ai import skills
    from app.ai.skills import dispatch, params
    from app.ai.skills.circuit_build import butterworth_g, compute, format_table
    from app.ai.skills.match_design import design, zin
    from app.ai.skills.plot_explain import analyze, format_report

    print("== 注册表")
    cat = skills.catalog()
    names = [c["name"] for c in cat]
    check("发现三个内置技能", names == sorted(names) and len(names) == 3, ",".join(names))
    check("技能名齐全", set(names) == {"circuit.build", "plot.explain", "match.design"})
    check("加载无错误", not skills.errors(), str(skills.errors())[:80])
    ro = {c["name"]: c["read_only"] for c in cat}
    check("曲线解读是只读", ro.get("plot.explain") is True)
    check("滤波器会改电路", ro.get("circuit.build") is False)

    print("== Butterworth 原型")
    check("g1=g3 (3阶对称)", close(butterworth_g(3)[0], butterworth_g(3)[2], 1e-9))
    check("3阶 g1=1.0", close(butterworth_g(3)[0], 1.0, 1e-9))
    check("5阶 g1=0.618", close(butterworth_g(5)[0], 0.6180339887, 1e-6))
    check("阶数非法返回空", butterworth_g(0) == [])

    print("== 低通综合")
    info = compute(kind="lowpass", fc_ghz=2.0, order=3, z0=50.0)
    els = info["elements"]
    check("元件数 = 阶数", len(els) == 3, str(len(els)))
    check("第1节为串联", els[0]["pos"] == "series", els[0]["pos"])
    check("第2节为并联", els[1]["pos"] == "shunt", els[1]["pos"])
    check("串联是电感", els[0]["kind"] == "L", els[0]["kind"])
    g1 = butterworth_g(3)[0]
    want_nh = g1 * 50.0 / (2 * math.pi * 2e9) * 1e9
    check("L1 = 3.9789 nH", close(els[0]["value"] * 1e9, want_nh, 1e-6),
          "%.4f" % (els[0]["value"] * 1e9))
    check("无 NaN", all(math.isfinite(e["value"]) for e in els))
    tbl = format_table(info)
    check("表格有实际数值（不是 0）", "0.0000" not in tbl.replace("0.0000 GHz", ""), tbl.split(chr(10))[1] if chr(10) in tbl else "")

    print("== 其它响应类型")
    hp = compute(kind="highpass", fc_ghz=1.0, order=4, z0=50.0)
    check("高通首节串联电容", hp["elements"][0]["pos"] == "series"
          and hp["elements"][0]["kind"] == "C")
    bp = compute(kind="bandpass", f1_ghz=2.4, f2_ghz=2.5, order=5, z0=50.0)
    check("带通元件数 = 2×阶数", len(bp["elements"]) == 10, str(len(bp["elements"])))

    print("== 匹配设计（自洽性：反算回 Zin 必须等于 Z0）")
    for rl, xl, z0 in ((100.0, 0.0, 50.0), (20.0, 0.0, 50.0),
                       (100.0, -25.0, 50.0), (30.0, 12.0, 75.0)):
        d = design(z0=z0, rl=rl, xl=xl, freq_ghz=1.0)
        check("RL=%.0f XL=%+.0f 收敛" % (rl, xl), d["ok"], d.get("q", ""))
        z = zin((rl, xl), d["elements"])
        check("  反算 Zin≈Z0", close(abs(z - z0), 0.0, 1e-6), "%.9f" % abs(z))

    print("== 曲线解读")
    f = [0.5 + i * (6.5 / 20000) for i in range(20001)]
    s21 = [0.0 if 4.0 <= x <= 6.0 else -50.0 for x in f]
    info = analyze(f, s21, None, drop_db=3.0)
    check("识别为带通", info["shape"] == "bandpass", info["shape"])
    check("下限≈4GHz", close(info["f_low_ghz"], 4.0, 2e-3), "%.4f" % info["f_low_ghz"])
    check("上限≈6GHz", close(info["f_high_ghz"], 6.0, 2e-3), "%.4f" % info["f_high_ghz"])
    check("带宽≈2GHz", close(info["bandwidth_ghz"], 2.0, 4e-3), "%.4f" % info["bandwidth_ghz"])
    check("报告含判据行", "-3.000 dB" in format_report(info))
    bad = analyze([1, 2, 3], [])
    check("缺数据时给出原因", bad.get("ok") is False and bad.get("reason"))

    print("== 参数解析")
    p = params.parse("设计 3 阶 2GHz 低通滤波器，Z0 50 欧", "circuit.build")
    check("低通阶数/频率/Z0", (p["kind"], p["order"], p["fc_ghz"], p["z0"])
          == ("lowpass", 3, 2.0, 50.0), str(p))
    p = params.parse("5 阶带通 2.4GHz - 2.5GHz", "circuit.build")
    check("带通双频", (p["kind"], p["order"], p["f1_ghz"], p["f2_ghz"])
          == ("bandpass", 5, 2.4, 2.5), str(p))
    p = params.parse("1500MHz 高通 4 阶", "circuit.build")
    check("MHz 换算成 GHz", close(p["fc_ghz"], 1.5), str(p))
    p = params.parse("负载 100 欧，容性，1.5GHz 匹配到 50 欧", "match.design")
    check("源/负载不混淆", (p["z0"], p["rl"], p["xl"]) == (50.0, 100.0, -25.0), str(p))
    p = params.parse("做 50 欧到 100 欧的匹配网络，1GHz", "match.design")
    check("50欧到100欧 解析", (p["z0"], p["rl"]) == (50.0, 100.0), str(p))

    print("== 派发")
    r = dispatch.run("设计 3 阶 2GHz 低通滤波器")
    check("低通派发成功", r and r["ok"] and r["skill"] == "circuit.build")
    check("低通产生 build_filter", r["actions"] and r["actions"][0]["op"] == "build_filter",
          str(r["actions"]))
    check("低通需要确认", r["needs_confirm"] is True)
    r = dispatch.run("高通滤波器 4阶 1.2GHz")
    check("高通也产生 build_filter",
          r["ok"] and r["actions"] and r["actions"][0]["topo"] == "highpass",
          str(r["actions"]))
    r = dispatch.run("带阻 2.0 到 2.5GHz 3 阶")
    check("带阻产生 build_filter",
          r["ok"] and r["actions"] and r["actions"][0]["topo"] == "bandstop",
          str(r["actions"]))
    check("闲聊不派发", dispatch.run("你好，介绍一下你自己") is None)
    r = dispatch.run("这条曲线带宽多少")
    check("只读词“带宽”能路由", r is not None and r["skill"] == "plot.explain",
          "" if r is None else r["skill"])
    check("无数据时解读报错但不崩",
          bool(r) and r["ok"] is False, "" if not r else r["message"][:40])
    check("闲聊+设计词不误触发改电路",
          dispatch.run("帮我设计一个放大器") is None)

    print()
    if _fail[0]:
        print("技能测试失败 %d 项 ✗" % _fail[0])
        return 1
    print("技能测试全部通过 ✔（%d 项）" % _ok[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
