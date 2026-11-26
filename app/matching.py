"""单/双枝节匹配（stub matching）：与 Smith 类工具对齐的核心功能。

约定：Z0 归一化；β = 2πf√εr/c；长度单位 mm。
支持：
  * 并联枝节（shunt stub）：开路/短路两种
  * 串联枝节（series stub）：开路/短路两种
求解方式：沿传输线扫描 tan(βd)，找 Re(Y)=1/Z0（并联）或 Re(Z)=Z0（串联）的交叉点，
再解析求出枝节电抗/电纳与长度；返回最小长度解与备选解。
"""
# 功能参考：著作权人自有软件（经授权）；代码为本项目独立实现。

from __future__ import annotations

import math
from typing import Dict, List

C0 = 299792458.0


def _beta(f_hz: float, er: float = 1.0) -> float:
    if er < 1.0:
        raise ValueError(f"相对介电常数 er 不得小于 1（真空为 1），当前 er={er:g}")
    return 2 * math.pi * f_hz * math.sqrt(er) / C0


def _len_mm(theta: float, beta: float) -> float:
    return (theta / beta) * 1000.0


def _y_line(yl: complex, t: float) -> complex:
    """输入导纳（归一化）：yL 经电长度 θ（t=tanθ）的线。"""
    return (yl + 1j * t) / (1 + 1j * yl * t)


def _z_line(zl: complex, t: float) -> complex:
    return (zl + 1j * t) / (1 + 1j * zl * t)


def _theta_roots(a: float, b: float, c: float) -> List[float]:
    """解 A·t² + B·t + C = 0（t=tanθ），返回 θ∈(0,π) 的解。

    并联：Re(Y)=1  ⇒ (g²+b²−g)t² − 2b·t + (1−g) = 0
    串联：Re(Z)=1  ⇒ (r²+x²−r)t² − 2x·t + (1−r) = 0
    """
    roots: List[float] = []
    if abs(a) < 1e-14:
        if abs(b) > 1e-14:
            roots = [-c / b]
    else:
        disc = b * b - 4 * a * c
        if disc >= 0:
            sq = math.sqrt(disc)
            roots = [(-b + sq) / (2 * a), (-b - sq) / (2 * a)]
    out: List[float] = []
    for tt in roots:
        th = math.atan(tt)
        while th <= 1e-9:
            th += math.pi
        while th >= math.pi:
            th -= math.pi
        if 1e-9 < th < math.pi - 1e-9:
            out.append(th)
    return sorted(set(round(x, 12) for x in out))


def shunt_stub(zl: complex, z0: float, f_hz: float, er: float = 1.0,
               prefer: str = "short") -> Dict:
    """并联枝节匹配。zl 为负载阻抗（Ω），可为复数。"""
    if f_hz <= 0:
        raise ValueError("频率必须 > 0")
    beta = _beta(f_hz, er)
    yl = z0 / complex(zl)
    g, bb = yl.real, yl.imag
    sols = []
    for th in _theta_roots(g * g + bb * bb - g, -2 * bb, 1 - g):
        yin = _y_line(yl, math.tan(th))
        b = -yin.imag            # 需要的归一化电纳
        if abs(b) < 1e-9:
            continue
        # 短路枝节：B = -cot(θs) → θs = atan(-1/B)
        th_s = math.atan2(-1.0, b) % math.pi
        th_o = math.atan2(b, 1.0) % math.pi   # 开路枝节：B = tan(θs)
        sols.append({"d_mm": _len_mm(th, beta),
                     "d_deg": math.degrees(th),
                     "b_norm": b,
                     "stub_short_mm": _len_mm(th_s, beta),
                     "stub_open_mm": _len_mm(th_o, beta)})
    if not sols:
        raise ValueError("该负载无并联枝节解（检查负载或频率）")
    sols.sort(key=lambda s: s["d_mm"] + s[("stub_short_mm" if prefer == "short"
                                           else "stub_open_mm")])
    best = sols[0]
    best["type"] = "shunt"
    best["stub"] = prefer
    best["stub_mm"] = best["stub_short_mm"] if prefer == "short" else best["stub_open_mm"]
    best["alternatives"] = sols[1:]
    return best


def _stub_len_to_theta(b: float, prefer: str) -> float:
    """由归一化电纳求枝节电长度：短路 B=-cot(θ)，开路 B=tan(θ)。"""
    if prefer == "short":
        return math.atan2(-1.0, b) % math.pi
    return math.atan2(b, 1.0) % math.pi


def double_stub(zl: complex, z0: float, f_hz: float, er: float = 1.0,
                spacing_lambda: float = 0.125, prefer: str = "short") -> Dict:
    """双枝节匹配（两并联枝节，间距 spacing_lambda）。

    负载 → 线 d1 → 枝节1 → 线 d12 → 枝节2 → 端口。
    对 d1 做扫描：在枝节1平面加电纳 b1 后，使经 d12 变换的输入实部为 1，
    再求枝节2 抵消虚部。返回线长与两枝节长度（mm）。
    """
    if f_hz <= 0 or z0 <= 0:
        raise ValueError("频率与 Z0 必须 > 0")
    if not (0.01 <= spacing_lambda < 0.5):
        raise ValueError(
            f"双枝节间距须在 [0.01, 0.5)λ 之间，当前 {spacing_lambda:g}λ："
            "间距过小时 tan(2π·s)→0，会除零/数值溢出（禁戒区）")
    beta = _beta(f_hz, er)
    yl = z0 / complex(zl)
    t12 = math.tan(2 * math.pi * spacing_lambda)
    if abs(t12) < 1e-6:
        raise ValueError("双枝节间距过小：tan(2π·s)≈0，方程奇异无解")
    best = None
    steps = 720
    for i in range(1, steps):
        th1 = math.pi * i / steps
        t1 = math.tan(th1)
        y1 = _y_line(yl, t1)
        a, im1 = y1.real, y1.imag
        disc = a * (1 + t12 * t12) - (a * t12) ** 2
        if disc < 0:
            continue
        root = math.sqrt(disc)
        for sign in (1, -1):
            u = (1 + sign * root) / t12
            b1 = u - im1
            y2 = complex(a, u)
            tin = _y_line(y2, t12)
            b2 = -tin.imag
            th_s1 = _stub_len_to_theta(b1, prefer)
            th_s2 = _stub_len_to_theta(b2, prefer)
            L1 = _len_mm(th_s1, beta)
            L2 = _len_mm(th_s2, beta)
            score = L1 + L2
            cand = {"d1_mm": _len_mm(th1, beta),
                    "d12_mm": _len_mm(2 * math.pi * spacing_lambda, beta),
                    "b1": b1, "b2": b2,
                    "stub1_mm": L1, "stub2_mm": L2,
                    "stub": prefer, "score": score,
                    "d1_lambda": th1 / (2 * math.pi)}
            if best is None or score < best["score"]:
                best = cand
    if best is None:
        raise ValueError("该负载/间距无可行双枝节解（间距过小会出现禁戒区）")
    best.pop("score", None)
    return best


def series_stub(zl: complex, z0: float, f_hz: float, er: float = 1.0,
                prefer: str = "short") -> Dict:
    """串联枝节匹配。"""
    if f_hz <= 0:
        raise ValueError("频率必须 > 0")
    beta = _beta(f_hz, er)
    zln = complex(zl) / z0
    r, x = zln.real, zln.imag
    sols = []
    for th in _theta_roots(r * r + x * x - r, -2 * x, 1 - r):
        zin = _z_line(zln, math.tan(th))
        x_stub = -zin.imag          # 枝节所需归一化电抗（勿与负载电抗 x 混淆）
        if abs(x_stub) < 1e-9:
            continue
        th_s = math.atan2(x_stub, 1.0) % math.pi      # 短路：X = tan(θ)
        th_o = math.atan2(-1.0, x_stub) % math.pi     # 开路：X = -cot(θ)
        sols.append({"d_mm": _len_mm(th, beta), "d_deg": math.degrees(th),
                     "x_norm": x_stub,
                     "stub_short_mm": _len_mm(th_s, beta),
                     "stub_open_mm": _len_mm(th_o, beta)})
    if not sols:
        raise ValueError("该负载无串联枝节解")
    sols.sort(key=lambda s: s["d_mm"] + s[("stub_short_mm" if prefer == "short"
                                           else "stub_open_mm")])
    best = sols[0]
    best["type"] = "series"
    best["stub"] = prefer
    best["stub_mm"] = best["stub_short_mm"] if prefer == "short" else best["stub_open_mm"]
    best["alternatives"] = sols[1:]
    return best