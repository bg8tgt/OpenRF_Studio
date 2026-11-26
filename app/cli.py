"""命令行入口：无界面也能跑（便于回归测试与批处理）。

用法：
  python -m app.cli demo                        生成示例工程并求解，导出 examples/demo_lpf.s2p
  python -m app.cli run 工程.json -o out.s2p    求解并导出 Touchstone
  python -m app.cli synth 3 3e9                 打印 3 阶 3GHz 低通 LC 值
  python -m app.cli microstrip 50 0.5 4.4       打印 50Ω 微带线线宽
"""
from __future__ import annotations

import argparse
import json
import os

from .project import Project, new_demo_project
from .synthesis import lowpass_lc, microstrip_line
from .touchstone import write_touchstone


def cmd_demo(args) -> int:
    p = new_demo_project()
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ex = os.path.join(here, "examples")
    os.makedirs(ex, exist_ok=True)
    jp = os.path.join(ex, "demo_lpf.json")
    p.save(jp)
    res = p.network.sweep(p.analysis)
    sp = os.path.join(ex, "demo_lpf.s2p")
    write_touchstone(sp, res.freqs, res.s, p.network.z0,
                     comment="3 阶切比雪夫低通 fc=3GHz")
    print(f"工程已保存：{jp}")
    print(f"Touchstone：{sp}（{len(res.freqs)} 个频点，{res.n_ports()} 端口）")
    k = len(res.freqs) // 2
    print(f"中心频点 {res.freqs[k]/1e9:.3f} GHz："
          f"|S11|={res.db(1,1)[k]:.2f} dB, |S21|={res.db(2,1)[k]:.2f} dB")
    return 0


def cmd_run(args) -> int:
    p = Project.load(args.project)
    res = p.network.sweep(p.analysis)
    out = args.output or os.path.splitext(args.project)[0] + ".s2p"
    write_touchstone(out, res.freqs, res.s, p.network.z0, comment=p.name)
    print(f"{out}: {len(res.freqs)} 点, {res.n_ports()} 端口, Z0={p.network.z0:g}Ω")
    return 0


def cmd_synth(args) -> int:
    rows = lowpass_lc(args.order, args.fc, args.z0, args.ripple, args.kind)
    print(f"{args.order} 阶 {args.kind} 低通，fc={args.fc/1e9:g} GHz，Z0={args.z0:g}Ω，纹波={args.ripple:g}dB")
    for i, r in enumerate(rows, 1):
        where = "并联到地" if r["shunt"] else "串联"
        unit = "nH" if r["kind"] == "L" else "pF"
        print(f"  {i}. {where} {r['kind']} = {r['value']:.6g} {unit}")
    return 0


def cmd_microstrip(args) -> int:
    d = microstrip_line(args.z0, args.f, args.h, args.er, args.quarter)
    print(f"Z0={args.z0:g}Ω  εr={args.er:g}  h={args.h:g}mm")
    print(f"  线宽 W = {d['w']:.4f} mm")
    print(f"  εeff  = {d['eeff']:.4f}")
    if args.quarter:
        print(f"  λ/4@{args.f/1e9:g}GHz 长度 = {d['len']:.4f} mm")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="openrf", description="OpenRF Studio 射频工作台")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="生成示例工程并导出 Touchstone")
    d.set_defaults(func=cmd_demo)

    r = sub.add_parser("run", help="求解工程并导出 Touchstone")
    r.add_argument("project")
    r.add_argument("-o", "--output")
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("synth", help="低通 LC 综合")
    s.add_argument("order", type=int)
    s.add_argument("fc", type=float, help="截止频率 Hz")
    s.add_argument("--z0", type=float, default=50.0)
    s.add_argument("--ripple", type=float, default=0.5)
    s.add_argument("--kind", default="chebyshev", choices=["chebyshev", "butterworth"])
    s.set_defaults(func=cmd_synth)

    m = sub.add_parser("microstrip", help="微带线计算")
    m.add_argument("z0", type=float)
    m.add_argument("h", type=float, help="基板厚度 mm")
    m.add_argument("er", type=float)
    m.add_argument("--f", type=float, default=1e9)
    m.add_argument("--quarter", action="store_true")
    m.set_defaults(func=cmd_microstrip)

    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
