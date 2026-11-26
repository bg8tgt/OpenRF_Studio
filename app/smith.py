"""史密斯圆图数学接口（干净室实现）。

本模块为独立编写：只使用公开的传输线与圆图公式，不包含任何第三方代码，
也不引用任何特定第三方软件的源码或产物。

  Γ = (Z−Z0)/(Z+Z0)，Z = Z0(1+Γ)/(1−Γ)
  Γin = ΓL·e^{−j4πd/λ}，VSWR = (1+|Γ|)/(1−|Γ|)
  回波损耗 = −20log|Γ|，失配损耗 = −10log(1−|Γ|²)
  等 r/x/g/b 圆为闭式几何；L 型匹配为两元件网络的标准解。
"""
# 功能参考：著作权人自有软件（经授权）；代码为本项目独立实现。

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, List, Optional

from . import rfmath as _rf

TWO_PI = 2.0 * math.pi
NORMAL, OPEN_POINT, REAL_AXIS, OUTSIDE = 0, 1, 2, 3


def fmt_signed(v: float, nd: int = 3) -> str:
    return f"{v:+.{nd}f}"


def fmt_complex(z: complex, nd: int = 4) -> str:
    return _rf.fmt_complex(z, nd)


def fmt_polar(g: complex, nd: int = 4) -> str:
    return _rf.fmt_polar(g, nd)


def fmt_henry(h: float) -> str:
    if h >= 1e-3:
        return f"{h * 1e3:.4g} mH"
    if h >= 1e-6:
        return f"{h * 1e6:.4g} µH"
    if h >= 1e-9:
        return f"{h * 1e9:.4g} nH"
    return f"{h * 1e12:.4g} pH"


def fmt_farad(c: float) -> str:
    if c >= 1e-6:
        return f"{c * 1e6:.4g} µF"
    if c >= 1e-9:
        return f"{c * 1e9:.4g} nF"
    if c >= 1e-12:
        return f"{c * 1e12:.4g} pF"
    return f"{c * 1e15:.4g} fF"


def gamma_from_impedance(z: complex, z0: float = 50.0) -> complex:
    return _rf.gamma_of_z(z, z0)


def impedance_from_gamma(g: complex, z0: float = 50.0) -> complex:
    return _rf.z_of_gamma(g, z0)


def admittance_from_gamma(g: complex, y0: float = 0.02) -> complex:
    z = _rf.z_of_gamma(g, 1.0 / y0)
    return 1.0 / z if abs(z) > _rf.EPS else complex(1e12, 0)


def vswr_from_mag(mag: float) -> float:
    return _rf.vswr_of(complex(mag, 0))


def return_loss_db(mag: float) -> float:
    return _rf.return_loss_db(complex(mag, 0))


def mismatch_loss_db(mag: float) -> float:
    return _rf.mismatch_loss_db(complex(mag, 0))


def reflected_power(mag: float) -> float:
    return _rf.reflected_power_pct(complex(mag, 0))


def angle_of_toward_generator(d_lambda: float) -> float:
    return -4.0 * math.pi * d_lambda


def wtg_at(angle_rad: float) -> float:
    return (-angle_rad / (4.0 * math.pi)) % 1.0


def wtl_at(angle_rad: float) -> float:
    return (0.5 - wtg_at(angle_rad)) % 1.0


@dataclass
@dataclass
@dataclass
class Element:
    role: str
    comp: str
    value: float
    omega: float
    x_ohm: float = 0.0
    b_siemens: float = 0.0

    @property
    def is_noop(self) -> bool:
        return abs(self.x_ohm) < 1e-12 and abs(self.b_siemens) < 1e-15

    def value_text(self) -> str:
        if self.is_noop:
            return "无需元件"
        return fmt_henry(self.value) if self.comp == "L" else fmt_farad(self.value)

    def reactance_text(self) -> str:
        role_cn = "串联" if self.role == "series" else "并联"
        tail = (f"(X = {fmt_signed(self.x_ohm, 2)} Ω)" if self.role == "series"
                else f"(B = {fmt_signed(self.b_siemens, 5)} S)")
        return f"{role_cn}{self.comp}  {self.value_text()}  {tail}"


@dataclass
class LSolution:
    topology: str
    desc: str
    series: Element
    shunt: Element
    q: float
    z_result: complex

    @property
    def label(self) -> str:
        return "A｜串→并" if self.topology == "A" else "B｜并→串"

    def elements_text(self) -> str:
        return f"{self.series.reactance_text()}   ／   {self.shunt.reactance_text()}"

    def summary_text(self) -> str:
        return f"{self.label}  Q={self.q:.4f}  Zin={fmt_complex(self.z_result, 2)}"


def _element(omega: float, role: str, x_ohm: float = 0.0,
             b_siemens: float = 0.0) -> Element:
    if role == "series":
        if abs(x_ohm) < 1e-12:
            return Element(role, "L", 0.0, omega, x_ohm=0.0)
        if x_ohm > 0:
            return Element(role, "L", x_ohm / omega, omega, x_ohm=x_ohm)
        return Element(role, "C", 1.0 / (omega * abs(x_ohm)), omega, x_ohm=x_ohm)
    if abs(b_siemens) < 1e-15:
        return Element(role, "C", 0.0, omega, b_siemens=0.0)
    if b_siemens > 0:
        return Element(role, "C", b_siemens / omega, omega, b_siemens=b_siemens)
    return Element(role, "L", 1.0 / (omega * abs(b_siemens)), omega, b_siemens=b_siemens)


def solve_l_network(zl: complex, z0: float = 50.0,
                    freq_hz: float = 1e9) -> List[LSolution]:
    if z0 <= 0:
        raise ValueError("Z0 必须 > 0")
    zl = complex(zl)
    if abs(zl) < 1e-15:
        raise ValueError("负载阻抗不能为 0")
    if abs(zl - z0) <= 1e-12 * max(1.0, z0):
        return []
    omega = TWO_PI * freq_hz if freq_hz > 0 else 1.0
    rl, xl = zl.real, zl.imag
    sols: List[LSolution] = []

    if 0 < rl < z0:
        xt_abs = math.sqrt(rl * (z0 - rl))
        for xt in (xt_abs, -xt_abs):
            xs = xt - xl
            bp = xt / (rl * z0)
            zin = 1.0 / (1.0 / complex(rl, xl + xs) + complex(0.0, bp))
            sols.append(LSolution(
                "A", "负载侧先串联 X，靠源侧并联 B",
                _element(omega, "series", x_ohm=xs),
                _element(omega, "shunt", b_siemens=bp),
                abs(xt) / rl, zin))

    yl = 1.0 / zl
    g, b0 = yl.real, yl.imag
    if g > 0 and g < 1.0 / z0:
        b1_abs = math.sqrt(g / z0 - g * g)
        for b1 in (b1_abs, -b1_abs):
            bp = b1 - b0
            xs = z0 * b1 / g
            zin = 1.0 / (1.0 / zl + complex(0.0, bp)) + complex(0.0, xs)
            sols.append(LSolution(
                "B", "负载侧先并联 B，靠源侧串联 X",
                _element(omega, "series", x_ohm=xs),
                _element(omega, "shunt", b_siemens=bp),
                abs(b1) / g, zin))
    sols.sort(key=lambda s: (round(s.q, 12), s.topology, -s.series.x_ohm))
    return sols


def solution_components(sol: LSolution, node_a: str, node_b: str,
                        node_gnd: str = "0",
                        id_factory: Optional[Callable[[str], str]] = None):
    from .components import Component

    def cid(kind: str) -> str:
        return id_factory(kind) if id_factory else kind

    def comp(e: Element, a: str, b: str, note: str) -> Component:
        return Component(cid(e.comp), e.comp, [a, b],
                         {"l": e.value * 1e9} if e.comp == "L" else {"c": e.value * 1e12},
                         note=note)

    out = []
    if sol.topology == "A":
        if not sol.series.is_noop:
            out.append(comp(sol.series, node_a, node_b, "L 型匹配（串联）"))
        if not sol.shunt.is_noop:
            out.append(comp(sol.shunt, node_b, node_gnd, "L 型匹配（并联）"))
    else:
        if not sol.shunt.is_noop:
            out.append(comp(sol.shunt, node_a, node_gnd, "L 型匹配（并联）"))
        if not sol.series.is_noop:
            out.append(comp(sol.series, node_a, node_b, "L 型匹配（串联）"))
    return out


def apply_to_network(net, sol: LSolution, port_id: str = "P1",
                     node_gnd: str = "0", new_node: str = "m_smith"):
    port = next((p for p in net.ports if p.pid == port_id), None)
    if port is None:
        raise ValueError(f"找不到端口 {port_id}")
    old = port.node
    if new_node in net.node_list():
        raise ValueError(f"节点 {new_node} 已存在，无法插入匹配网络")
    comps = solution_components(sol, old, new_node, node_gnd, net.next_id)
    for c in comps:
        net.add(c)
    port.node = new_node
    return comps