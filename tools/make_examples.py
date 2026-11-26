"""生成成套示例工程（JSON + Touchstone），便于用户直接打开。"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.components import Component, microstrip_synthesize, microstrip_z0_eeff
from app.engine import Analysis, Network, Port
from app.project import Project
from app.synthesis import bandpass_lc, lowpass_lc
from app.touchstone import write_touchstone

EX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")


def ladder(items, z0=50.0):
    from app.builders import ladder_to_network
    return ladder_to_network(items, z0)


def save(name, project, ana):
    project.analysis = ana
    project.network.z0 = project.network.z0
    jp = os.path.join(EX, name + ".json")
    project.name = name
    Project.save(project, jp)
    res = project.network.sweep(ana)
    sp = os.path.join(EX, name + ".s%dp" % res.n_ports())
    write_touchstone(sp, res.freqs, res.s, project.network.z0, comment=name)
    k = len(res.freqs) // 2
    print(f"{name}: {len(res.freqs)} 点 {res.n_ports()} 端口 -> {os.path.basename(jp)}, {os.path.basename(sp)}")
    print(f"   mid {res.freqs[k]/1e9:.3f} GHz: |S11|={res.db(1,1)[k]:.2f} dB"
          f" |S21|={res.db(2,1)[k]:.2f} dB" if res.n_ports() >= 2 else "")


def main():
    os.makedirs(EX, exist_ok=True)

    # 1) 3 阶切比雪夫低通 3 GHz
    p = Project("低通_3阶_3GHz")
    p.network = ladder(lowpass_lc(3, 3e9, 50.0, 0.5))
    save("01_lowpass_3ghz", p, Analysis(0.5, 6.0, 401))

    # 2) 3 阶带通 2.3–2.7 GHz（ISM 2.4G 附近）
    p = Project("带通_3阶_2.4GHz")
    p.network = ladder(bandpass_lc(3, 2.3e9, 2.7e9, 50.0, 0.5))
    save("02_bandpass_2g4", p, Analysis(1.0, 4.0, 601))

    # 3) Wilkinson 三端口功分器 @2 GHz（理想传输线；实际版可换 MS 元件）
    Lq = 299792458.0 / 2e9 / 4 * 1e3
    net = Network(50.0)
    net.add(Component("T1", "TL", ["p1", "p2"], {"z0": 70.7107, "er": 1.0, "len": Lq}))
    net.add(Component("T2", "TL", ["p1", "p3"], {"z0": 70.7107, "er": 1.0, "len": Lq}))
    net.add(Component("R1", "R", ["p2", "p3"], {"r": 100.0}))
    net.ports = [Port("P1", "p1"), Port("P2", "p2"), Port("P3", "p3")]
    p = Project("功分器_Wilkinson_2GHz")
    p.network = net
    save("03_wilkinson_2ghz", p, Analysis(1.5, 2.5, 201))

    # 4) 微带线：FR4 h=0.508mm，50Ω，λ/4 @2.4GHz
    w = microstrip_synthesize(50.0, 0.508, 3.55)
    z, ee = microstrip_z0_eeff(w, 0.508, 3.55, 2.4e9)
    L = 299792458.0 / (2.4e9 * math.sqrt(ee)) / 4 * 1e3
    net = Network(50.0)
    net.add(Component("MS1", "MS", ["n1", "n2"],
                      {"w": w, "h": 0.508, "er": 3.55, "len": L, "loss": 0.0}))
    net.ports = [Port("P1", "n1"), Port("P2", "n2")]
    p = Project("微带线_50ohm_quarterwave")
    p.network = net
    save("04_microstrip_qw", p, Analysis(1.0, 4.0, 301))
    print(f"   微带线: W={w:.4f} mm, L={L:.4f} mm, εeff={ee:.4f}")

    # 5) 同轴 50Ω
    from app.tline import coax_design
    d = coax_design(50.0, 0.91, 2.1, 1.75e9)
    net = Network(50.0)
    net.add(Component("X1", "COAX", ["n1", "n2"],
                      {"d_in": 0.91, "d_out": d["d_out_mm"], "er": 2.1, "len": 100.0}))
    net.ports = [Port("P1", "n1"), Port("P2", "n2")]
    p = Project("同轴_50ohm_100mm")
    p.network = net
    save("05_coax_50ohm", p, Analysis(0.5, 3.0, 201))
    print(f"   同轴: d=0.91 mm, D={d['d_out_mm']:.4f} mm, εr=2.1, λ/4={d['quarter_mm']:.3f} mm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())