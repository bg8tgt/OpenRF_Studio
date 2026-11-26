"""1:4 巴伦（balun）设计：威尔金森功分 + 两级 λ/4 阻抗变换 + 两段 λ/4 移相。

结构（输入 50 Ω，差分输出 200 Ω，每个输出端对地 100 Ω）：
    输入 in ──┬─ TL1(70.71 Ω, λ/4) ─ b ─ TL3(70.71 Ω, λ/4) ─ d  （输出 +）
              └─ TL2(70.71 Ω, λ/4) ─ c ─ TL4(70.71 Ω, λ/4) ─ e
                                       │
                                    R1 = 100 Ω（隔离电阻，b–c）
    移相臂：e ─ TL5(100 Ω, λ/4) ─ m ─ TL6(100 Ω, λ/4) ─ h        （输出 −）
    相位差：两段 λ/4 = λ/2 → 180°

端口参考阻抗：P1=50 Ω，P2=P3=100 Ω（差分 200 Ω）。
在中心频率 f0：S11 → 深度匹配，|S21|=|S31|=−3.01 dB，相位差 180°。
"""
from __future__ import annotations

import math
from typing import Dict, List

from .components import Component
from .engine import Network, Port

C0 = 299792458.0


def quarter_wave_mm(f_hz: float, er: float = 1.0) -> float:
    if f_hz <= 0:
        raise ValueError("频率必须为正")
    return C0 / (4.0 * f_hz * math.sqrt(max(er, 1.0))) * 1000.0


def design_1to4(f_hz: float, z0: float = 50.0) -> Dict:
    """返回元件清单与预期指标（不修改工程）。"""
    if f_hz <= 0:
        raise ValueError("频率必须 > 0")
    q = quarter_wave_mm(f_hz)
    zb = z0 * math.sqrt(2.0)
    comps: List[Dict] = [
        {"id": "TL1", "kind": "TL", "nodes": ["in", "b"],
         "params": {"z0": zb, "er": 1.0, "len": q}},
        {"id": "TL2", "kind": "TL", "nodes": ["in", "c"],
         "params": {"z0": zb, "er": 1.0, "len": q}},
        {"id": "R1", "kind": "R", "nodes": ["b", "c"], "params": {"r": 2 * z0}},
        {"id": "TL3", "kind": "TL", "nodes": ["b", "d"],
         "params": {"z0": zb, "er": 1.0, "len": q}},
        {"id": "TL4", "kind": "TL", "nodes": ["c", "e"],
         "params": {"z0": zb, "er": 1.0, "len": q}},
        {"id": "TL5", "kind": "TL", "nodes": ["e", "m"],
         "params": {"z0": 2 * z0, "er": 1.0, "len": q}},
        {"id": "TL6", "kind": "TL", "nodes": ["m", "h"],
         "params": {"z0": 2 * z0, "er": 1.0, "len": q}},
    ]
    ports = [{"id": "P1", "node": "in", "z0": z0},
             {"id": "P2", "node": "d", "z0": 2 * z0},
             {"id": "P3", "node": "h", "z0": 2 * z0}]
    return {"f_hz": f_hz, "z0": z0, "quarter_mm": q, "branch_z0": zb,
            "components": comps, "ports": ports,
            "expected": {"s11_db": "深度匹配（< -60 dB）",
                         "s21_db": -3.01, "s31_db": -3.01,
                         "phase_diff_deg": 180.0,
                         "diff_z": 2 * z0}}


def build_network(f_hz: float, z0: float = 50.0) -> Network:
    """按设计生成 Network（可直接仿真）。"""
    d = design_1to4(f_hz, z0)
    net = Network(z0)
    for c in d["components"]:
        net.add(Component(c["id"], c["kind"], list(c["nodes"]), dict(c["params"])))
    net.ports = [Port(p["id"], p["node"], p["z0"]) for p in d["ports"]]
    return net


def describe(f_hz: float, z0: float = 50.0) -> str:
    d = design_1to4(f_hz, z0)
    return (f"1:4 巴伦 @ {f_hz/1e9:g} GHz：输入 {z0:g} Ω，差分 {2*z0:g} Ω；"
            f"分支线 {d['branch_z0']:.2f} Ω，λ/4={d['quarter_mm']:.3f} mm；"
            f"中心频率 |S21|=|S31|={d['expected']['s21_db']:.2f} dB，"
            f"相位差 {d['expected']['phase_diff_deg']:g}°")
