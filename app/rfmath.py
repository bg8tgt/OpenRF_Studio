"""圆图与传输线数学（独立实现）。

只用公开公式：
  Γ = (Z−Z0)/(Z+Z0)；Z = Z0(1+Γ)/(1−Γ)；Y = 1/Z；
  VSWR = (1+|Γ|)/(1−|Γ|)；回波损耗 = −20log|Γ|；
  失配损耗 = −10log(1−|Γ|²)；反射功率比 = |Γ|²；
  Γin = ΓL·e^{−j4πd/λ}；λ = c/(f√εr)；d = d/λ·λ。
等电阻/电抗圆与 L 型匹配均为教科书闭式。
"""
# 功能参考：著作权人自有软件（经授权）；代码为本项目独立实现。

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

C0 = 299_792_458.0
EPS = 1e-12


# ---------------------------------------------------------------- 基础换算
def gamma_of_z(z: complex, z0: float = 50.0) -> complex:
    if z0 <= 0:
        raise ValueError("Z0 必须 > 0")
    den = complex(z) + z0
    if abs(den) < EPS:
        return complex(1e12, 0)
    return (complex(z) - z0) / den


def z_of_gamma(g: complex, z0: float = 50.0) -> complex:
    if z0 <= 0:
        raise ValueError("Z0 必须 > 0")
    den = 1 - g
    if abs(den) < EPS:
        return complex(1e12, 0)
    return z0 * (1 + g) / den


def y_of_gamma(g: complex, z0: float = 50.0) -> complex:
    z = z_of_gamma(g, z0)
    if abs(z) < EPS:
        return complex(1e12, 0)
    return 1.0 / z


def vswr_of(g: complex) -> float:
    m = abs(g)
    if m >= 1:
        return float("inf")
    return (1 + m) / (1 - m)


def return_loss_db(g: complex) -> float:
    m = abs(g)
    return 999.0 if m < 1e-12 else -20 * math.log10(m)


def mismatch_loss_db(g: complex) -> float:
    m2 = abs(g) ** 2
    return 0.0 if m2 < EPS else -10 * math.log10(max(1 - m2, EPS))


def reflected_power_pct(g: complex) -> float:
    return 100.0 * min(abs(g) ** 2, 1.0)


def wavelength_m(f_hz: float, vf: float = 1.0) -> float:
    if f_hz <= 0:
        return float("nan")
    return C0 / (f_hz * max(vf, 1e-6))


def physical_length_m(d_lambda: float, f_hz: float, vf: float = 1.0) -> float:
    lam = wavelength_m(f_hz, vf)
    return float("nan") if not math.isfinite(lam) else d_lambda * lam


# ---------------------------------------------------------------- 传输线
@dataclass
class Line:
    z0: float = 50.0
    zl: complex = 50.0 + 0j
    d_lambda: float = 0.0

    @property
    def gamma_load(self) -> complex:
        return gamma_of_z(self.zl, self.z0)

    def gamma_at(self, d_lambda: Optional[float] = None) -> complex:
        d = self.d_lambda if d_lambda is None else d_lambda
        return self.gamma_load * complex(math.cos(-4 * math.pi * d),
                                         math.sin(-4 * math.pi * d))

    @property
    def gamma_in(self) -> complex:
        return self.gamma_at()

    @property
    def zin(self) -> complex:
        return z_of_gamma(self.gamma_in, self.z0)

    @property
    def vswr(self) -> float:
        return vswr_of(self.gamma_load)

    @property
    def return_loss(self) -> float:
        return return_loss_db(self.gamma_load)

    @property
    def mismatch_loss(self) -> float:
        return mismatch_loss_db(self.gamma_load)

    @property
    def reflected_power(self) -> float:
        return reflected_power_pct(self.gamma_load)


# ---------------------------------------------------------------- 圆族
@dataclass
class Circle:
    cx: float
    cy: float
    r: float

    def intersects_unit(self) -> List[complex]:
        """与单位圆的交点（复数平面），用于绘制辅助圆与标注。"""
        d = math.hypot(self.cx, self.cy)
        if d < EPS:
            return []
        if abs(d - self.r) < 1e-9 or abs(d - (1 + self.r)) < 1e-9:
            return []
        if d > 1 + self.r or d < abs(1 - self.r):
            return []
        a = (1 - self.r ** 2 + d ** 2) / (2 * d)
        h2 = 1 - a * a
        if h2 < 0:
            return []
        h = math.sqrt(h2)
        ux, uy = self.cx / d, self.cy / d
        p = complex(ux * a, uy * a)
        q = complex(-uy * h, ux * h)
        return [p + q, p - q]


def r_circle(r: float) -> Circle:
    if r < 0:
        raise ValueError("r 必须 ≥ 0")
    c = r / (1 + r)
    return Circle(c, 0.0, 1 / (1 + r))


def x_circle(x: float) -> Circle:
    if abs(x) < EPS:
        return Circle(1e9, 0.0, 1e9)   # 实轴，绘制时按直线处理
    return Circle(1.0, 1.0 / x, abs(1.0 / x))


def g_circle(g: float) -> Circle:
    if g < 0:
        raise ValueError("g 必须 ≥ 0")
    c = -g / (1 + g)
    return Circle(c, 0.0, 1 / (1 + g))


def b_circle(b: float) -> Circle:
    if abs(b) < EPS:
        return Circle(1e9, 0.0, 1e9)
    return Circle(-1.0, -1.0 / b, abs(1.0 / b))


def vswr_circle(g: complex, z0: float = 50.0) -> Circle:
    return Circle(0.0, 0.0, min(abs(g), 1.0))


# ---------------------------------------------------------------- L 型匹配
def _element_from_x(x_ohm: float, f_hz: float) -> dict:
    """串联电抗 → L/C（Ω→元件值）。"""
    w = 2 * math.pi * f_hz
    if x_ohm >= 0:
        return {"kind": "L", "value": x_ohm / w * 1e9, "unit": "nH",
                "text": f"串联 L = {x_ohm / w * 1e9:.4g} nH"}
    c = -1 / (w * x_ohm) * 1e12
    return {"kind": "C", "value": c, "unit": "pF",
            "text": f"串联 C = {c:.4g} pF"}


def _element_from_b(b_s: float, f_hz: float) -> dict:
    """并联电纳 → L/C（S→元件值）。"""
    w = 2 * math.pi * f_hz
    if b_s >= 0:
        c = b_s / w * 1e12
        return {"kind": "C", "value": c, "unit": "pF",
                "text": f"并联 C = {c:.4g} pF"}
    l = -1 / (w * b_s) * 1e9
    return {"kind": "L", "value": l, "unit": "nH",
            "text": f"并联 L = {l:.4g} nH"}


def l_match(z0: float, zl: complex, f_hz: float) -> List[dict]:
    """复数负载的两元件 L 型匹配（并联件在负载侧 / 串联件在负载侧 两种拓扑）。

    拓扑 A（并联件并在负载上，串联件朝源）：
        Re(1/(yL+jB)) = z0  ⇒ (b+B)² = g/z0 − g²，g = Re(yL)
    拓扑 B（串联件串在负载上，并联件朝源）：
        Re(1/(zL+jX)) = 1/z0 ⇒ (x+X)² = r·z0 − r²，r = Re(zL)
    两式各有 ± 两个根，取物理可实现的解。
    """
    if z0 <= 0 or f_hz <= 0:
        raise ValueError("Z0 与频率必须 > 0")
    zl = complex(zl)
    out: List[dict] = []
    # 拓扑 A
    yl = 1 / zl if abs(zl) > EPS else complex(1e12, 0)
    g, b = yl.real, yl.imag
    disc = g / z0 - g * g
    if disc >= 0:
        root = math.sqrt(disc)
        for sign in (+1, -1):
            bt = sign * root               # t = b + B
            bb = bt - b                    # 需要并联的电纳 B = t − b
            if abs(bb) < EPS:
                continue
            z_after = 1 / complex(g, bt)
            xs = -z_after.imag
            if abs(xs) < EPS:
                continue
            out.append({"name": "并联件在负载侧", "topology": "A",
                        "shunt": _element_from_b(bb, f_hz),
                        "series": _element_from_x(xs, f_hz),
                        "q": abs(bb) * z0})
    # 拓扑 B
    r, x = zl.real, zl.imag
    disc = r * z0 - r * r
    if disc >= 0:
        root = math.sqrt(disc)
        for sign in (+1, -1):
            xt = x + sign * root
            xs = -x + sign * root           # 需要串联的电抗
            if abs(xs) < EPS:
                continue
            z_after = complex(r, xt)
            bb = -z_after.imag / (abs(z_after) ** 2) if abs(z_after) > EPS else 0.0
            if abs(bb) < EPS:
                continue
            out.append({"name": "串联件在负载侧", "topology": "B",
                        "shunt": _element_from_b(bb, f_hz),
                        "series": _element_from_x(xs, f_hz),
                        "q": abs(xs) / z0})
    # 自校验：只保留真正把输入拉回 z0 的解
    ok: List[dict] = []
    w = 2 * math.pi * f_hz
    for s in out:
        if s["topology"] == "A":
            B = s["shunt"]["value"] / 1e12 * w if s["shunt"]["kind"] == "C" else -1.0 / (s["shunt"]["value"] * 1e-9 * w)
            X = s["series"]["value"] * 1e-9 * w if s["series"]["kind"] == "L" else -1.0 / (s["series"]["value"] * 1e-12 * w)
            zin = complex(0, X) + 1.0 / (1.0 / zl + complex(0, B))
            if abs(zin - z0) / z0 < 1e-6:
                ok.append(s)
        else:
            B = s["shunt"]["value"] / 1e12 * w if s["shunt"]["kind"] == "C" else -1.0 / (s["shunt"]["value"] * 1e-9 * w)
            X = s["series"]["value"] * 1e-9 * w if s["series"]["kind"] == "L" else -1.0 / (s["series"]["value"] * 1e-12 * w)
            yin = complex(0, B) + 1.0 / (zl + complex(0, X))
            if abs(yin - 1.0 / z0) * z0 < 1e-6:
                ok.append(s)
    out = ok
    # 去重（不同根可能落到同一元件值）
    seen = set()
    uniq: List[dict] = []
    for s in out:
        key = (s["topology"], round(s["shunt"]["value"], 9), s["shunt"]["kind"],
               round(s["series"]["value"], 9), s["series"]["kind"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(s)
    return uniq[:4]


# ---------------------------------------------------------------- 格式
def fmt_complex(z: complex, nd: int = 4) -> str:
    return f"{z.real:.{nd}g} {z.imag:+.{nd}g}j"


def fmt_polar(g: complex, nd: int = 4) -> str:
    return f"{abs(g):.{nd}f} ∠{math.degrees(math.atan2(g.imag, g.real)):.1f}°"


def fmt_vswr(v: float, nd: int = 4) -> str:
    """VSWR 文本：|Γ|>=1 时方程无解，显示 ∞ 而不是裸 inf。"""
    if v != v:
        return "—"
    if not math.isfinite(v):
        return "∞"
    return f"{v:.{nd}f}"


def fmt_db(v: float, nd: int = 2) -> str:
    """dB 文本：被 DB_FLOOR 钳出的极低值显示 -∞，NaN 显示 —。"""
    if v != v:
        return "—"
    if not math.isfinite(v):
        return "∞" if v > 0 else "-∞"
    if v <= -600.0:
        return "-∞"
    return f"{v:.{nd}f}"


def fmt_num(v: float, nd: int = 4) -> str:
    """通用数值文本：非有限值按 ∞/— 显示。"""
    if v != v:
        return "—"
    if not math.isfinite(v):
        return "∞" if v > 0 else "-∞"
    return f"{v:.{nd}f}"