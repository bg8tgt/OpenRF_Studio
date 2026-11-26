"""电路元件模型（干净室实现）。

约定：
  * 节点名 "0" / "GND" / "gnd" 一律表示参考地；
  * 每个元件提供 stamp(freq_hz) -> (节点列表, 复导纳矩阵)，矩阵按“元件自身节点”排列；
  * 引擎会把地节点对应的行列删掉（即导纳落到对应节点的对角元上）。

模型全部来自公开公式：
  * 理想传输线 / 有耗传输线：Y 参数（Pozar, Microwave Engineering, 4th ed., §4.4）
  * 微带线准静态：Hammerstad & Jensen (1980)，带 Hammerstad 色散修正
"""
from __future__ import annotations

import cmath
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

C0 = 299_792_458.0  # m/s

GROUND_NAMES = {"0", "gnd", "GND", "ground", "GND0", "-"}

# S2P 文件缓存：{(绝对路径, mtime): (freqs, S[i][j][k], z0, nport)}
_S2P_CACHE: Dict[Tuple[str, float], Tuple[List[float], List[List[List[complex]]], float, int]] = {}


def _load_s2p(path: str):
    """读取并缓存 Touchstone 文件（返回频率、S[频点][i][j]、Z0、端口数）。"""
    import os
    from .touchstone import read_touchstone
    ap = os.path.abspath(path)
    mtime = os.path.getmtime(ap)
    key = (ap, mtime)
    if key not in _S2P_CACHE:
        _S2P_CACHE[key] = read_touchstone(ap)
    return _S2P_CACHE[key]


def _interp_s(freqs: List[float], data: List[List[List[complex]]], f_hz: float,
              nport: int) -> List[List[complex]]:
    """对 S 参数做复数线性插值；越界取端点值。"""
    if f_hz <= freqs[0]:
        return data[0]
    if f_hz >= freqs[-1]:
        return data[-1]
    lo, hi = 0, len(freqs) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if freqs[mid] <= f_hz:
            lo = mid
        else:
            hi = mid
    t = (f_hz - freqs[lo]) / (freqs[hi] - freqs[lo])
    out = [[0j] * nport for _ in range(nport)]
    for i in range(nport):
        for j in range(nport):
            out[i][j] = data[lo][i][j] * (1 - t) + data[hi][i][j] * t
    return out


def _inv2(m: List[List[complex]]) -> List[List[complex]]:
    a, b = m[0][0], m[0][1]
    c, d = m[1][0], m[1][1]
    det = a * d - b * c
    if abs(det) < 1e-30:
        raise ValueError("S2P 元件矩阵奇异")
    return [[d / det, -b / det], [-c / det, a / det]]


def _s2p_admittance(path: str, z0: float, f_hz: float) -> List[List[complex]]:
    """2 端口 S → Y：Y = Y0·(I−S)·(I+S)⁻¹。"""
    freqs, data, fz0, nport = _load_s2p(path)
    if nport != 2:
        raise ValueError(f"S2P 元件目前只支持 2 端口（该文件 {nport} 端口）")
    s = _interp_s(freqs, data, f_hz, 2)
    i_s = [[1 - s[0][0], -s[0][1]], [-s[1][0], 1 - s[1][1]]]
    p_s = [[1 + s[0][0], s[0][1]], [s[1][0], 1 + s[1][1]]]
    inv = _inv2(p_s)
    y0 = 1.0 / (fz0 if fz0 and fz0 > 0 else z0)
    return [[y0 * (i_s[0][0] * inv[0][0] + i_s[0][1] * inv[1][0]),
             y0 * (i_s[0][0] * inv[0][1] + i_s[0][1] * inv[1][1])],
            [y0 * (i_s[1][0] * inv[0][0] + i_s[1][1] * inv[1][0]),
             y0 * (i_s[1][0] * inv[0][1] + i_s[1][1] * inv[1][1])]]


def is_ground(name: str) -> bool:
    return str(name).strip() in GROUND_NAMES


def _microstrip_quasi(w_m: float, h_m: float, er: float) -> Tuple[float, float]:
    """Hammerstad-Jensen 准静态：返回 (Z0, eps_eff)。"""
    u = w_m / h_m
    if u <= 0:
        return 1e9, (er + 1) / 2
    if u < 1.0:
        ee = (er + 1) / 2 + (er - 1) / 2 * (
            1 / math.sqrt(1 + 12 / u) + 0.04 * (1 - u) ** 2)
    else:
        ee = (er + 1) / 2 + (er - 1) / 2 / math.sqrt(1 + 12 / u)
    if u <= 1.0:
        z0 = 60 / math.sqrt(ee) * math.log(8 / u + u / 4)
    else:
        z0 = 120 * math.pi / (math.sqrt(ee) * (u + 1.393 + 0.667 * math.log(u + 1.444)))
    return z0, ee


def _microstrip_dispersion(z0: float, ee: float, w_m: float, h_m: float,
                           er: float, f_hz: float) -> Tuple[float, float]:
    """Hammerstad 色散修正（频率很高时才明显）。"""
    u = w_m / h_m
    fp = C0 / (2 * math.pi * h_m * math.sqrt(er)) if h_m > 0 else 1e30
    # 归一化频率
    fn = f_hz / fp if fp > 0 else 0.0
    p1 = 0.27488 + (0.6315 + 0.525 / (1 + 0.0157 * fn) ** 20) * u - 0.065683 * math.exp(-8.7513 * u)
    p2 = 0.33622 * (1 - math.exp(-0.03442 * er))
    p3 = 0.0363 * math.exp(-4.6 * u) * (1 - math.exp(-(fn / 38.7) ** 4.97))
    p4 = 1 + 2.751 * (1 - math.exp(-(er / 15.916) ** 8))
    p = p1 * p2 * ((0.1844 + p3 * p4) * fn) ** 1.5763
    ee_f = er - (er - ee) / (1 + p)
    z0_f = z0 * math.sqrt(ee / ee_f)
    return z0_f, ee_f


def microstrip_z0_eeff(w_mm: float, h_mm: float, er: float, f_hz: float = 0.0) -> Tuple[float, float]:
    """微带线特性阻抗与有效介电常数（含色散）。"""
    w_m, h_m = w_mm * 1e-3, h_mm * 1e-3
    z0, ee = _microstrip_quasi(w_m, h_m, er)
    if f_hz > 0:
        z0, ee = _microstrip_dispersion(z0, ee, w_m, h_m, er, f_hz)
    return z0, ee


def microstrip_synthesize(z0_target: float, h_mm: float, er: float) -> float:
    """给定 Z0 求线宽（mm）：对 W/h 做二分。"""
    if z0_target <= 0:
        raise ValueError("特性阻抗必须为正")
    lo, hi = 1e-4, 50.0          # W/h 搜索区间
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        z, _ = _microstrip_quasi(mid * h_mm * 1e-3, h_mm * 1e-3, er)
        if z > z0_target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi) * h_mm


@dataclass
class Component:
    """一个电路元件。"""
    cid: str
    kind: str                      # R / L / C / TL / MS / PORT
    nodes: List[str]
    params: Dict[str, Any] = field(default_factory=dict)
    note: str = ""

    # ---------- 显示 ----------
    def param_text(self) -> str:
        p = self.params
        if self.kind == "R":
            return f"R={p.get('r', 50):g} Ω"
        if self.kind == "L":
            return f"L={p.get('l', 1):g} nH"
        if self.kind == "C":
            return f"C={p.get('c', 1):g} pF"
        if self.kind == "TL":
            return (f"Z0={p.get('z0', 50):g} Ω, 长度={p.get('len', 10):g} mm, "
                    f"εr={p.get('er', 1):g}")
        if self.kind == "COAX":
            return (f"同轴 D/d={p.get('d_out', 3.0):g}/{p.get('d_in', 0.91):g} mm, "
                    f"εr={p.get('er', 2.1):g}, 长度={p.get('len', 100):g} mm")
        if self.kind == "MS":
            return (f"W={p.get('w', 1):g} mm, 长度={p.get('len', 10):g} mm, "
                    f"h={p.get('h', 0.5):g} mm, εr={p.get('er', 4.4):g}")
        if self.kind == "S2P":
            import os
            return f"S2P: {os.path.basename(str(p.get('path', ''))) or '（未指定）'}"
        if self.kind in ("RLCS", "RLCP"):
            mode = "串联" if self.kind == "RLCS" else "并联"
            return (f"{mode} RLC: R={p.get('r', 50):g} Ω, L={p.get('l', 2):g} nH, "
                    f"C={p.get('c', 1):g} pF")
        return self.kind

    def describe(self) -> str:
        return f"{self.cid}  {self.kind}  {self.param_text()}  节点 {'-'.join(self.nodes)}"

    # ---------- 物理 ----------
    def stamp(self, f_hz: float) -> Tuple[List[str], List[List[complex]]]:
        """返回 (节点列表, 导纳矩阵)。"""
        w = 2 * math.pi * f_hz
        p = self.params

        if self.kind == "R":
            r = max(p.get("r", 50.0), 1e-9)
            y = 1.0 / r
            return self.nodes, [[y, -y], [-y, y]]

        if self.kind == "L":
            l_h = max(p.get("l", 1.0), 0.0) * 1e-9
            y = 1.0 / (1j * w * l_h) if l_h > 0 and w > 0 else complex(1e12, 0)
            return self.nodes, [[y, -y], [-y, y]]

        if self.kind == "C":
            c_f = max(p.get("c", 1.0), 0.0) * 1e-12
            y = 1j * w * c_f
            return self.nodes, [[y, -y], [-y, y]]

        if self.kind in ("RLCS", "RLCP"):
            r = max(float(p.get("r", 50.0)), 1e-9)
            l_h = max(float(p.get("l", 1.0)), 0.0) * 1e-9
            c_f = max(float(p.get("c", 1.0)), 0.0) * 1e-12
            z = complex(r, 0.0)
            if l_h > 0 and w > 0:
                z += 1j * w * l_h
            if c_f > 0 and w > 0:
                z += 1.0 / (1j * w * c_f)
            if self.kind == "RLCP":
                inv = 1.0 / complex(r, 0)
                if l_h > 0 and w > 0:
                    inv += 1.0 / (1j * w * l_h)
                if c_f > 0 and w > 0:
                    inv += 1j * w * c_f
                z = 1.0 / inv if abs(inv) > 1e-30 else complex(1e12, 0)
            if abs(z) < 1e-30:
                z = complex(1e-9, 0)
            y = 1.0 / z
            return self.nodes, [[y, -y], [-y, y]]

        if self.kind == "S2P":
            path = str(p.get("path", ""))
            if not path:
                raise ValueError(f"{self.cid}: 未指定 S2P 文件")
            return self.nodes, _s2p_admittance(path, float(p.get("z0", 50.0)), f_hz)

        if self.kind == "TL":
            return self.nodes, self._tl_matrix(
                z0=float(p.get("z0", 50.0)),
                er=float(p.get("er", 1.0)),
                length_mm=float(p.get("len", 10.0)),
                loss_db_per_m=float(p.get("loss", 0.0)),
                f_hz=f_hz,
            )

        if self.kind == "COAX":
            d_in = float(p.get("d_in", 0.91))
            d_out = float(p.get("d_out", 3.0))
            er = float(p.get("er", 2.1))
            z0 = (60.0 / math.sqrt(max(er, 1.0))
                  * math.log(max(d_out, d_in * 1.000001) / max(d_in, 1e-9)))
            return self.nodes, self._tl_matrix(
                z0=z0, er=er, length_mm=float(p.get("len", 100.0)),
                loss_db_per_m=float(p.get("loss", 0.0)), f_hz=f_hz)

        if self.kind == "MS":
            z0, ee = microstrip_z0_eeff(
                float(p.get("w", 1.0)), float(p.get("h", 0.5)),
                float(p.get("er", 4.4)), f_hz)
            return self.nodes, self._tl_matrix(
                z0=z0, er=ee, length_mm=float(p.get("len", 10.0)),
                loss_db_per_m=float(p.get("loss", 0.0)), f_hz=f_hz)

        raise ValueError(f"未知元件类型：{self.kind}")

    @staticmethod
    def _tl_matrix(z0: float, er: float, length_mm: float,
                   loss_db_per_m: float, f_hz: float) -> List[List[complex]]:
        """传输线 Y 参数：y11=y22=Y0/tanh(γl)，y12=y21=-Y0/sinh(γl)。"""
        er = max(er, 1.0)
        length_m = length_mm * 1e-3
        v = C0 / math.sqrt(er)
        beta = 2 * math.pi * f_hz / v
        alpha = loss_db_per_m * math.log(10) / 20.0     # Np/m
        # 数值正则：无损线在 θ=nπ/2（尤其 λ/4）时 Y 参数奇异，加一个
        # 物理上可忽略的损耗底（1e-7 Np/m ≈ 8.7e-7 dB/m），让 Schur 补稳定。
        alpha = max(alpha, 1e-7)
        gl = complex(alpha * length_m, beta * length_m)
        y0 = 1.0 / max(z0, 1e-9)
        if abs(gl) < 1e-12:
            # 极短/极低频：当作短路线（导纳很大）
            big = 1e12
            return [[big, -big], [-big, big]]
        sh = cmath.sinh(gl)
        th = cmath.tanh(gl)
        if abs(sh) < 1e-30:
            sh = 1e-30
        y11 = y0 / th if abs(th) > 1e-30 else 1e12
        y12 = -y0 / sh
        return [[y11, y12], [y12, y11]]

    def to_dict(self) -> dict:
        return {"id": self.cid, "kind": self.kind,
                "nodes": list(self.nodes), "params": dict(self.params),
                "note": self.note}

    @staticmethod
    def from_dict(d: dict) -> "Component":
        params: Dict[str, Any] = {}
        for k, v in (d.get("params") or {}).items():
            try:
                params[k] = float(v)
            except (TypeError, ValueError):
                params[k] = v
        return Component(cid=str(d["id"]), kind=str(d["kind"]),
                         nodes=[str(x) for x in d.get("nodes", [])],
                         params=params, note=str(d.get("note", "")))