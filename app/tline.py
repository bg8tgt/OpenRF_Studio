"""传输线计算：微带 / 带状线 / 同轴。

公式来源：
  * 微带线：Hammerstad-Jensen 准静态 + Hammerstad 色散（与 components.py 同一套）
  * 带状线：IPC-2141 闭式近似（零厚度近似；实际铜厚会带来 ~5-10% 偏差）
  * 同轴：精确解析式 Z0 = (60/√εr)·ln(D/d)（TEM，无高阶模）

单位：本模块内部一律 mm / Hz；单位换算由 app.units 负责（界面层做）。
"""
from __future__ import annotations

import math
from typing import Dict

from .components import microstrip_synthesize, microstrip_z0_eeff

C0 = 299_792_458.0


# ---------------------------------------------------------------- 微带
def microstrip(w_mm: float, h_mm: float, er: float, f_hz: float = 0.0) -> Dict:
    """微带线分析：给几何求 Z0/εeff/电长度。"""
    z0, ee = microstrip_z0_eeff(w_mm, h_mm, er, f_hz)
    out = {"z0": z0, "eeff": ee, "w_mm": w_mm, "h_mm": h_mm, "er": er}
    out.update(_length_info(z0, ee, f_hz))
    return out


def microstrip_design(z0: float, h_mm: float, er: float, f_hz: float = 0.0) -> Dict:
    """微带线综合：给 Z0 求线宽。"""
    w = microstrip_synthesize(z0, h_mm, er)
    z, ee = microstrip_z0_eeff(w, h_mm, er, f_hz)
    out = {"z0": z, "eeff": ee, "w_mm": w, "h_mm": h_mm, "er": er}
    out.update(_length_info(z, ee, f_hz))
    return out


# ---------------------------------------------------------------- 带状线
def stripline_z0(w_mm: float, b_mm: float, er: float, t_mm: float = 0.0) -> float:
    """IPC-2141 带状线（b = 上下地平面总间距）。"""
    w = max(w_mm, 1e-9)
    b = max(b_mm, 1e-9)
    weff = 0.8 * w + max(t_mm, 0.0)
    arg = 4.0 * b / (0.67 * math.pi * weff)
    if arg <= 1.0:
        raise ValueError(
            "带状线几何无效：需 4b/(0.67π·weff) > 1；当前等效线宽 weff 相对地间距 b 过大，"
            "对数项 ≤ 0 会给出 Z0≤0 的非物理结果")
    return (60.0 / math.sqrt(max(er, 1.0))) * math.log(arg)


def stripline(w_mm: float, b_mm: float, er: float, t_mm: float = 0.0,
              f_hz: float = 0.0) -> Dict:
    z0 = stripline_z0(w_mm, b_mm, er, t_mm)
    ee = max(er, 1.0)               # 均匀介质：εeff = εr
    out = {"z0": z0, "eeff": ee, "w_mm": w_mm, "b_mm": b_mm, "er": er, "t_mm": t_mm}
    out.update(_length_info(z0, ee, f_hz))
    return out


def stripline_design(z0: float, b_mm: float, er: float, t_mm: float = 0.0,
                     f_hz: float = 0.0) -> Dict:
    """由 Z0 反解线宽（闭式反解 + 单调性保证）。"""
    if z0 <= 0:
        raise ValueError("Z0 必须为正")
    # Z0 = (60/√εr)·ln(4b/(0.67π(0.8w+t)))  →  解 ln 项
    k = math.exp(z0 * math.sqrt(max(er, 1.0)) / 60.0)
    weff = 4.0 * max(b_mm, 1e-9) / (0.67 * math.pi * k)
    w = (weff - max(t_mm, 0.0)) / 0.8
    if w <= 0:
        raise ValueError(
            f"由 Z0={z0:g}Ω 反解出的线宽为 {w:.3g} mm（≤0），无物理可行解："
            "目标阻抗过低或铜厚 t 相对地间距 b 过大")
    z = stripline_z0(w, b_mm, er, t_mm)
    out = {"z0": z, "eeff": max(er, 1.0), "w_mm": w, "b_mm": b_mm, "er": er, "t_mm": t_mm}
    out.update(_length_info(z, out["eeff"], f_hz))
    return out


# ---------------------------------------------------------------- 同轴
def coax_z0(d_in_mm: float, d_out_mm: float, er: float) -> float:
    """同轴：Z0 = (60/√εr)·ln(D/d)（精确，TEM 模）。"""
    if d_in_mm <= 0:
        raise ValueError(f"同轴线内导体外径 d_in 必须 > 0，当前 {d_in_mm:g} mm")
    if d_out_mm <= d_in_mm:
        raise ValueError(
            f"同轴线外导体内径 d_out({d_out_mm:g} mm) 必须大于内导体外径 "
            f"d_in({d_in_mm:g} mm)，否则无法构成同轴 TEM 结构")
    return (60.0 / math.sqrt(max(er, 1.0))) * math.log(d_out_mm / d_in_mm)


def coax(d_in_mm: float, d_out_mm: float, er: float, f_hz: float = 0.0) -> Dict:
    z0 = coax_z0(d_in_mm, d_out_mm, er)
    ee = max(er, 1.0)
    out = {"z0": z0, "eeff": ee, "d_in_mm": d_in_mm, "d_out_mm": d_out_mm, "er": er}
    out.update(_length_info(z0, ee, f_hz))
    return out


def coax_design(z0: float, d_in_mm: float, er: float, f_hz: float = 0.0) -> Dict:
    """由 Z0 与内导体直径求外导体内径。"""
    if z0 <= 0:
        raise ValueError("Z0 必须为正")
    ratio = math.exp(z0 * math.sqrt(max(er, 1.0)) / 60.0)
    d_out = max(d_in_mm, 1e-9) * ratio
    out = {"z0": coax_z0(d_in_mm, d_out, er), "eeff": max(er, 1.0),
           "d_in_mm": d_in_mm, "d_out_mm": d_out, "er": er}
    out.update(_length_info(out["z0"], out["eeff"], f_hz))
    return out


# ---------------------------------------------------------------- 公共
def electrical_length_deg(length_mm: float, eeff: float, f_hz: float) -> float:
    """电长度（度）：βl = 2πf·l·√εeff/c0。"""
    if f_hz <= 0:
        raise ValueError(f"电长度计算需要频率 f > 0（f≤0 时 βl 无定义），当前 f={f_hz:g} Hz")
    beta = 2 * math.pi * f_hz * math.sqrt(max(eeff, 1.0)) / C0
    return math.degrees(beta * length_mm * 1e-3)


def length_for_electrical_deg(deg: float, eeff: float, f_hz: float) -> float:
    if f_hz <= 0:
        raise ValueError("需要频率 > 0")
    beta = 2 * math.pi * f_hz * math.sqrt(max(eeff, 1.0)) / C0
    return math.radians(deg) / beta * 1e3


def quarter_wave_mm(f_hz: float, eeff: float) -> float:
    return length_for_electrical_deg(90.0, eeff, f_hz)


def _length_info(z0: float, eeff: float, f_hz: float) -> Dict:
    out = {"lambda_mm": (C0 / (max(f_hz, 1.0) * math.sqrt(max(eeff, 1.0)))) * 1e3 if f_hz > 0 else 0.0}
    if f_hz > 0:
        out["quarter_mm"] = quarter_wave_mm(f_hz, eeff)
        out["elen_deg_per_mm"] = electrical_length_deg(1.0, eeff, f_hz)
    else:
        out["quarter_mm"] = 0.0
        out["elen_deg_per_mm"] = 0.0
    return out
