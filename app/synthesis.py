"""综合计算：滤波器原型、微带线、四分之一波长。

公式来源（公开教材，未复制任何商业软件实现）：
  * 切比雪夫/巴特沃斯低通原型 g 值：Pozar §8.3、Matthaei/Young/Jones Ch.4
  * 低通→带通变换：Pozar §8.4
  * 微带线：Hammerstad & Jensen (1980)
"""
from __future__ import annotations

import math
from typing import Dict, List

from .components import microstrip_synthesize, microstrip_z0_eeff

C0 = 299_792_458.0


# ---------------------------------------------------------------- 原型 g 值
def butterworth_g(n: int) -> List[float]:
    """巴特沃斯低通原型（g1..gn，源/负载归一化 g0=g_{n+1}=1）。"""
    if n < 1:
        raise ValueError("阶数必须 ≥ 1")
    return [2 * math.sin((2 * k - 1) * math.pi / (2 * n)) for k in range(1, n + 1)]


def chebyshev_g(n: int, ripple_db: float = 0.5) -> List[float]:
    """切比雪夫低通原型 g1..gn（等终端）。"""
    if n < 1:
        raise ValueError("阶数必须 ≥ 1")
    if ripple_db <= 0:
        return butterworth_g(n)
    beta = math.log(1.0 / math.tanh(ripple_db / 17.37))
    gamma = math.sinh(beta / (2 * n))
    a = [math.sin((2 * k - 1) * math.pi / (2 * n)) for k in range(1, n + 1)]
    b = [gamma ** 2 + math.sin(k * math.pi / n) ** 2 for k in range(1, n)]
    g = [2 * a[0] / gamma]
    for k in range(1, n):
        g.append(4 * a[k - 1] * a[k] / (b[k - 1] * g[k - 1]))
    return g


# ---------------------------------------------------------------- 低通 LC
def lowpass_lc(n: int, fc_hz: float, z0: float = 50.0,
               ripple_db: float = 0.5, kind: str = "chebyshev") -> List[Dict]:
    """低通梯形网络（n 奇数：串 L 起；n 偶数：并 C 起）。

    返回 [{'kind':'L'|'C','value':数值,'shunt':bool}]，value 单位 nH / pF。
    """
    if fc_hz <= 0:
        raise ValueError("截止频率必须 > 0")
    g = chebyshev_g(n, ripple_db) if kind == "chebyshev" else butterworth_g(n)
    wc = 2 * math.pi * fc_hz
    out = []
    for i, gi in enumerate(g):
        # 奇数位置（1,3,5...）在 n 为奇数时是串联 L；n 为偶数时整体翻转
        series_slot = (i % 2 == 0) if (n % 2 == 1) else (i % 2 == 1)
        if series_slot:
            l_h = gi * z0 / wc
            out.append({"kind": "L", "value": l_h * 1e9, "shunt": False})
        else:
            c_f = gi / (wc * z0)
            out.append({"kind": "C", "value": c_f * 1e12, "shunt": True})
    return out


# ---------------------------------------------------------------- 带通 LC
def bandpass_lc(n: int, f1_hz: float, f2_hz: float, z0: float = 50.0,
                ripple_db: float = 0.5, kind: str = "chebyshev") -> List[Dict]:
    """带通梯形网络：串联支路=串 LC，并联支路=并 LC。

    返回 [{'kind':'L'|'C','value':数值,'shunt':bool,'pair':group}]，同组两个元件串联/并联。
    """
    if not (0 < f1_hz < f2_hz):
        raise ValueError("需要 0 < f1 < f2")
    g = chebyshev_g(n, ripple_db) if kind == "chebyshev" else butterworth_g(n)
    f0 = math.sqrt(f1_hz * f2_hz)
    fbw = (f2_hz - f1_hz) / f0
    w0 = 2 * math.pi * f0
    out: List[Dict] = []
    for i, gi in enumerate(g):
        series_slot = (i % 2 == 0) if (n % 2 == 1) else (i % 2 == 1)
        if series_slot:
            # 串联 LC：L = g Z0 /(w0 FBW)，C = FBW/(w0 Z0 g)
            out.append({"kind": "L", "value": gi * z0 / (w0 * fbw) * 1e9,
                        "shunt": False, "pair": i})
            out.append({"kind": "C", "value": fbw / (w0 * z0 * gi) * 1e12,
                        "shunt": False, "pair": i})
        else:
            # 并联 LC：C = g/(w0 Z0 FBW)，L = FBW Z0/(w0 g)
            out.append({"kind": "C", "value": gi / (w0 * z0 * fbw) * 1e12,
                        "shunt": True, "pair": i})
            out.append({"kind": "L", "value": fbw * z0 / (w0 * gi) * 1e9,
                        "shunt": True, "pair": i})
    return out


# ---------------------------------------------------------------- 高通 LC
def highpass_lc(n: int, fc_hz: float, z0: float = 50.0,
                ripple_db: float = 0.5, kind: str = "chebyshev") -> List[Dict]:
    """高通梯形网络：低通的串联 L→串联 C，并联 C→并联 L（阻抗倒置变换）。

    返回 [{'kind':'L'|'C','value':数值,'shunt':bool}]，value 单位 nH / pF。
    """
    if fc_hz <= 0:
        raise ValueError("截止频率必须 > 0")
    g = chebyshev_g(n, ripple_db) if kind == "chebyshev" else butterworth_g(n)
    wc = 2 * math.pi * fc_hz
    out = []
    for i, gi in enumerate(g):
        series_slot = (i % 2 == 0) if (n % 2 == 1) else (i % 2 == 1)
        if series_slot:
            # 串联 C = 1/(wc Z0 g)
            out.append({"kind": "C", "value": 1.0 / (wc * z0 * gi) * 1e12,
                        "shunt": False})
        else:
            # 并联 L = Z0/(wc g)
            out.append({"kind": "L", "value": z0 / (wc * gi) * 1e9,
                        "shunt": True})
    return out


# ---------------------------------------------------------------- 带阻 LC
def bandstop_lc(n: int, f1_hz: float, f2_hz: float, z0: float = 50.0,
                ripple_db: float = 0.5, kind: str = "chebyshev") -> List[Dict]:
    """带阻梯形网络：带通的串联 LC→并联 LC，并联 LC→串联 LC（对偶变换）。

    返回 [{'kind':'L'|'C','value':数值,'shunt':bool,'pair':group}]。
    """
    if not (0 < f1_hz < f2_hz):
        raise ValueError("需要 0 < f1 < f2")
    g = chebyshev_g(n, ripple_db) if kind == "chebyshev" else butterworth_g(n)
    f0 = math.sqrt(f1_hz * f2_hz)
    fbw = (f2_hz - f1_hz) / f0
    w0 = 2 * math.pi * f0
    out: List[Dict] = []
    for i, gi in enumerate(g):
        series_slot = (i % 2 == 0) if (n % 2 == 1) else (i % 2 == 1)
        if series_slot:
            # 串联臂里的并联 LC：L = FBW Z0/(w0 g)，C = 1/(w0 FBW Z0 g)
            out.append({"kind": "L", "value": fbw * z0 / (w0 * gi) * 1e9,
                        "shunt": False, "pair": i, "dual": True})
            out.append({"kind": "C", "value": 1.0 / (w0 * fbw * z0 * gi) * 1e12,
                        "shunt": False, "pair": i, "dual": True})
        else:
            # 并联臂里的串联 LC：L = g Z0/(w0 FBW)，C = FBW/(w0 g Z0)
            out.append({"kind": "L", "value": gi * z0 / (w0 * fbw) * 1e9,
                        "shunt": True, "pair": i, "dual": True})
            out.append({"kind": "C", "value": fbw / (w0 * gi * z0) * 1e12,
                        "shunt": True, "pair": i, "dual": True})
    return out


# ---------------------------------------------------------------- 微带辅助
def quarter_wave_length_mm(f0_hz: float, er_eff: float) -> float:
    """四分之一波长的物理长度（mm）。"""
    if f0_hz <= 0:
        raise ValueError(f"四分之一波长计算需要频率 f0 > 0，当前 f0={f0_hz:g} Hz")
    lam = C0 / (f0_hz * math.sqrt(max(er_eff, 1.0)))
    return lam / 4 * 1e3


# 非四分之一波长分支的缺省线长（mm）：仅为界面初始线长，非电学推导值。
# 旧版把 10.0 硬编码在 microstrip_line 内且无说明；现提为显式常量，
# 调用方可用 length_mm 参数覆盖。
DEFAULT_LINE_LEN_MM = 10.0


def microstrip_line(z0: float, f0_hz: float, h_mm: float, er: float,
                    quarter_wave: bool = False,
                    length_mm: float | None = None) -> Dict:
    """给定 Z0 与基板，返回微带线参数（线宽 mm、长度 mm）。

    quarter_wave=True 时长度 = 该频率下的 λg/4；否则取 length_mm
    （缺省 DEFAULT_LINE_LEN_MM）。
    """
    w = microstrip_synthesize(z0, h_mm, er)
    _, ee = microstrip_z0_eeff(w, h_mm, er, f0_hz)
    if quarter_wave:
        length = quarter_wave_length_mm(f0_hz, ee)
    elif length_mm is None:
        length = DEFAULT_LINE_LEN_MM
    else:
        length = float(length_mm)
        if length <= 0:
            raise ValueError(f"线长 length_mm 必须 > 0，当前 {length:g} mm")
    return {"w": w, "len": length, "h": h_mm, "er": er, "z0": z0, "eeff": ee}
