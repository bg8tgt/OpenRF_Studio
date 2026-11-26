"""电路求解引擎：节点导纳矩阵（MNA）→ 端口 Y 矩阵 → S 参数。

算法（全部为公开的标准方法）：
  1. 对每个频点，把所有元件的导纳矩阵"盖章"进全局 Y 矩阵；
  2. 把非端口节点用 Schur 补消去：
        Yp = Ypp - Ypi · Yii^{-1} · Yip
  3. 等参考阻抗 Z0（实数）时：
        S = (I - Z0·Yp) · (I + Z0·Yp)^{-1}
     （I ± Z0·Yp 是 Yp 的多项式，二者可交换，乘序不影响结果）
"""
from __future__ import annotations

import cmath
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .complexmath import identity, inverse, matmul, sub, zeros

# dB 计算共用的幅度下限：20*log10(1e-300) = -600 dB。
# db() 与 summary_at() 必须用同一常量，否则同一份数据在两处显示不同（2026 审计项 3）。
DB_FLOOR = 1e-300
from .components import Component, is_ground


@dataclass
class Port:
    pid: str
    node: str
    z0: Optional[float] = None      # 每端口参考阻抗；None = 用网络全局 z0

    def effective_z0(self, default: float) -> float:
        return self.z0 if self.z0 and self.z0 > 0 else default

    def to_dict(self) -> dict:
        d = {"id": self.pid, "node": self.node}
        if self.z0:
            d["z0"] = self.z0
        return d


@dataclass
class Analysis:
    start_ghz: float = 1.0
    stop_ghz: float = 6.0
    points: int = 401
    sweep: str = "linear"        # linear | log
    step_ghz: float = 0.0        # >0 时按步进取点（步进优先于点数）
    single: bool = False         # 单点分析：只算起始频点

    def frequencies(self) -> List[float]:
        if self.single:
            return [self.start_ghz * 1e9]
        if self.stop_ghz < self.start_ghz:
            raise ValueError(
                f"终止频率必须不低于起始频率：start={self.start_ghz:g} GHz, "
                f"stop={self.stop_ghz:g} GHz（扫描方向不能反向）")
        if self.step_ghz and self.step_ghz > 0:
            f0, f1, st = self.start_ghz * 1e9, self.stop_ghz * 1e9, self.step_ghz * 1e9
            out = []
            f = f0
            # 容差只用于把「恰好落在终点」的最后一个点收进来：取步进的 1e-9，
            # 即相对步进（不是相对频率）的微量松弛，不改变点间隔、与 f1 大小无关。
            tol = st * 1e-9
            while f <= f1 + tol and len(out) < 200000:
                out.append(f)
                f += st
            if len(out) < 2:
                out.append(f1 if out and out[0] < f1 else f0 + st)
            return out
        n = max(int(self.points), 2)
        if self.sweep == "log":
            if self.start_ghz <= 0 or self.stop_ghz <= 0:
                raise ValueError("对数扫频要求起止频率 > 0")
            lo, hi = math.log10(self.start_ghz), math.log10(self.stop_ghz)
            return [10 ** (lo + (hi - lo) * i / (n - 1)) * 1e9 for i in range(n)]
        return [self.start_ghz * 1e9 + (self.stop_ghz - self.start_ghz) * 1e9 * i / (n - 1)
                for i in range(n)]

    def to_dict(self) -> dict:
        return {"start_ghz": self.start_ghz, "stop_ghz": self.stop_ghz,
                "points": self.points, "sweep": self.sweep,
                "step_ghz": self.step_ghz, "single": self.single}

    @staticmethod
    def from_dict(d: dict) -> "Analysis":
        return Analysis(float(d.get("start_ghz", 1.0)), float(d.get("stop_ghz", 6.0)),
                        int(d.get("points", 401)), str(d.get("sweep", "linear")),
                        float(d.get("step_ghz", 0.0)), bool(d.get("single", False)))


class Network:
    """一个 N 端口线性网络。"""

    def __init__(self, z0: float = 50.0):
        self.components: List[Component] = []
        self.ports: List[Port] = []
        self.z0 = z0

    # ---------- 编辑 ----------
    def add(self, c: Component) -> None:
        if any(x.cid == c.cid for x in self.components):
            raise ValueError(f"元件编号重复：{c.cid}")
        self.components.append(c)

    def remove(self, cid: str) -> None:
        self.components = [c for c in self.components if c.cid != cid]

    def get(self, cid: str) -> Optional[Component]:
        return next((c for c in self.components if c.cid == cid), None)

    def next_id(self, kind: str) -> str:
        i = 1
        while any(c.cid == f"{kind}{i}" for c in self.components):
            i += 1
        return f"{kind}{i}"

    # ---------- 求解 ----------
    def node_list(self) -> List[str]:
        names = set()
        for c in self.components:
            for n in c.nodes:
                if not is_ground(n):
                    names.add(n)
        for p in self.ports:
            if not is_ground(p.node):
                names.add(p.node)
        return sorted(names, key=lambda s: (len(s), s))

    def port_nodes(self) -> List[str]:
        return [p.node for p in self.ports]

    def build_y(self, f_hz: float) -> Tuple[List[str], List[List[complex]]]:
        nodes = self.node_list()
        idx = {n: i for i, n in enumerate(nodes)}
        y = zeros(len(nodes))
        for c in self.components:
            cnodes, cmat = c.stamp(f_hz)
            for i, ni in enumerate(cnodes):
                if is_ground(ni):
                    continue
                ii = idx[ni]
                for j, nj in enumerate(cnodes):
                    if is_ground(nj):
                        continue
                    y[ii][idx[nj]] += cmat[i][j]
        return nodes, y

    def port_admittance(self, f_hz: float) -> List[List[complex]]:
        """消去内部节点后的端口导纳矩阵。"""
        nodes, y = self.build_y(f_hz)
        pnodes = [n for n in self.port_nodes() if not is_ground(n)]
        np_ = len(pnodes)
        if np_ == 0:
            raise ValueError("没有定义端口")
        idx = {n: i for i, n in enumerate(nodes)}
        pidx = [idx[n] for n in pnodes]
        pset = set(pidx)      # 提到循环外：原写法对每个 i 重建一次集合（O(n^2)）
        iidx = [i for i in range(len(nodes)) if i not in pset]
        ypp = [[y[p][q] for q in pidx] for p in pidx]
        if not iidx:
            return ypp
        ypi = [[y[p][q] for q in iidx] for p in pidx]
        yii = [[y[p][q] for q in iidx] for p in iidx]
        yip = [[y[p][q] for q in pidx] for p in iidx]
        inv_yii = inverse(yii)
        return sub(ypp, matmul(matmul(ypi, inv_yii), yip))

    def port_z0(self) -> List[float]:
        return [p.effective_z0(self.z0) for p in self.ports]

    def s_matrix(self, f_hz: float) -> List[List[complex]]:
        """S = (I − √Z·Yp·√Z)(I + √Z·Yp·√Z)⁻¹，Z 为各端口参考阻抗（可不同）。"""
        yp = self.port_admittance(f_hz)
        n = len(yp)
        # 只对未接地的端口取参考阻抗，与 port_admittance 的 pnodes 顺序严格同源
        sq = [math.sqrt(p.effective_z0(self.z0)) for p in self.ports if not is_ground(p.node)]
        ys = [[yp[i][j] * sq[i] * sq[j] for j in range(n)] for i in range(n)]
        a = sub(identity(n), ys)
        b = [[ys[i][j] for j in range(n)] for i in range(n)]
        for i in range(n):
            b[i][i] += 1 + 0j
        return matmul(a, inverse(b))

    # ---------- 一次性扫频 ----------
    def sweep(self, ana: Analysis) -> "SweepResult":
        freqs = ana.frequencies()
        data = [self.s_matrix(f) for f in freqs]
        return SweepResult(freqs=freqs, s=data, z0=self.z0,
                           port_names=[p.pid for p in self.ports])

    # ---------- 序列化 ----------
    def to_dict(self) -> dict:
        return {"z0": self.z0,
                "components": [c.to_dict() for c in self.components],
                "ports": [p.to_dict() for p in self.ports]}

    @staticmethod
    def from_dict(d: dict) -> "Network":
        net = Network(z0=float(d.get("z0", 50.0)))
        for cd in d.get("components", []):
            net.components.append(Component.from_dict(cd))
        for pd in d.get("ports", []):
            pz = pd.get("z0")
            net.ports.append(Port(str(pd.get("id", "P1")), str(pd.get("node", "n1")),
                                  float(pz) if pz else None))
        return net


@dataclass
class SweepResult:
    freqs: List[float]
    s: List[List[List[complex]]]
    z0: float
    port_names: List[str]

    def s_ij(self, i: int, j: int) -> List[complex]:
        """取第 i 端口对第 j 端口的 S 参数（1 起）。越界抛 IndexError。"""
        n = self.n_ports()
        if not (1 <= i <= n and 1 <= j <= n):
            raise IndexError(f"端口序号越界：i={i}, j={j}（本网络 {n} 个端口，有效范围 1..{n}）")
        return [m[i - 1][j - 1] for m in self.s]

    def n_ports(self) -> int:
        return len(self.s[0]) if self.s else len(self.port_names)

    def db(self, i: int, j: int) -> List[float]:
        out = []
        for x in self.s_ij(i, j):
            m = abs(x)
            out.append(20 * math.log10(m if m > DB_FLOOR else DB_FLOOR))
        return out

    def return_loss_db(self, i: int = 1) -> List[float]:
        return self.db(i, i)

    def insertion_loss_db(self, i: int = 2, j: int = 1) -> List[float]:
        return self.db(i, j)

    def vswr(self, i: int = 1) -> List[float]:
        out = []
        for x in self.s_ij(i, i):
            m = abs(x)
            # |S| >= 1 对应负电阻/有源网络：VSWR 数学上为 +inf，不再钳到 0.999999
            # 编造出 2e6 这类假值（2026 审计项 2）。显示层需自行格式化 inf。
            if m >= 1.0:
                out.append(float("inf"))
            else:
                out.append((1 + m) / (1 - m))
        return out

    def stability(self, s11_idx: int = 1, s12_idx: int = 2,
                  s21_idx: int = 2, s22_idx: int = 2) -> List[float]:
        """二端口稳定性因子 K（Rollett）。"""
        out = []
        for k in range(len(self.freqs)):
            s11 = self.s[k][s11_idx - 1][s11_idx - 1]
            s12 = self.s[k][s11_idx - 1][s12_idx - 1]
            s21 = self.s[k][s21_idx - 1][s11_idx - 1]
            s22 = self.s[k][s22_idx - 1][s22_idx - 1]
            denom = abs(s12 * s21)
            if denom < 1e-30:
                out.append(float("inf"))
            else:
                out.append((1 - abs(s11) ** 2 - abs(s22) ** 2 + abs(s11 * s22 - s12 * s21) ** 2)
                           / (2 * denom))
        return out

    def group_delay_ns(self, i: int = 1, j: int = 1) -> List[float]:
        """群时延 τ = −dφ/dω（相位解缠绕后中心差分），单位 ns。"""
        import cmath
        vals = self.s_ij(i, j)
        n = len(vals)
        if n == 0:
            return []
        ph = [cmath.phase(v) for v in vals]
        # 解缠绕
        unwrapped = [ph[0]]
        for k in range(1, n):
            d = ph[k] - ph[k - 1]
            while d > math.pi:
                d -= 2 * math.pi
            while d < -math.pi:
                d += 2 * math.pi
            unwrapped.append(unwrapped[-1] + d)
        out = []
        for k in range(n):
            if n == 1:
                out.append(0.0)
                continue
            if k == 0:
                dphi = unwrapped[1] - unwrapped[0]
                dw = 2 * math.pi * (self.freqs[1] - self.freqs[0])
            elif k == n - 1:
                dphi = unwrapped[-1] - unwrapped[-2]
                dw = 2 * math.pi * (self.freqs[-1] - self.freqs[-2])
            else:
                dphi = unwrapped[k + 1] - unwrapped[k - 1]
                dw = 2 * math.pi * (self.freqs[k + 1] - self.freqs[k - 1])
            tau = -dphi / dw if dw else 0.0
            out.append(tau * 1e9)
        return out

    def summary_at(self, f_hz: float) -> Dict[str, float]:
        """最近频点的关键指标（用于界面状态栏）。"""
        if not self.freqs:
            return {}
        k = min(range(len(self.freqs)), key=lambda i: abs(self.freqs[i] - f_hz))
        out = {"频率_GHz": self.freqs[k] / 1e9}
        n = self.n_ports()
        for i in range(1, n + 1):
            out[f"|S{i}{i}|_dB"] = 20 * math.log10(max(abs(self.s[k][i - 1][i - 1]), DB_FLOOR))
        if n >= 2:
            out["|S21|_dB"] = 20 * math.log10(max(abs(self.s[k][1][0]), DB_FLOOR))
            out["K"] = self.stability()[k]
        return out