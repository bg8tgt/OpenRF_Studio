"""参数优化器（无导数 Nelder–Mead，带边界与进度历史）。

用于把电路指标（带内最大 |S11|、带内最小 |S21|、指定频点插损）调到目标值。
变量为元件参数（L nH / C pF / TL-MS 线长 mm 等），全部有上下界。
"""
# 功能参考：著作权人自有软件（经授权）；代码为本项目独立实现。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .engine import Analysis, Network


@dataclass
class Parameter:
    cid: str
    key: str
    lo: float
    hi: float
    value: float

    @property
    def label(self) -> str:
        unit = {"l": "nH", "c": "pF", "len": "mm", "z0": "Ω", "w": "mm",
                "h": "mm", "r": "Ω"}.get(self.key, "")
        return f"{self.cid}.{self.key} ({unit})"


@dataclass
class Spec:
    kind: str                 # s11 | s21min | s21at
    f1_ghz: float = 1.0
    f2_ghz: float = 2.0
    target_db: float = -20.0
    weight: float = 1.0
    note: str = ""


@dataclass
class Result:
    ok: bool
    cost: float
    params: List[Parameter]
    history: List[Tuple[float, List[float]]] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)
    message: str = ""


def collect_parameters(net: Network) -> List[Parameter]:
    """可优化参数：L/C 值、TL/MS 长度（默认上下界 = 现值 ×[0.2, 5]）。"""
    out: List[Parameter] = []
    for c in net.components:
        for key, lo_scale, hi_scale in (("l", 0.2, 5.0), ("c", 0.2, 5.0),
                                        ("len", 0.2, 5.0)):
            if key in c.params:
                v = float(c.params[key])
                if v <= 0:
                    continue
                out.append(Parameter(c.cid, key, v * lo_scale, v * hi_scale, v))
    return out


def apply_values(net: Network, params: List[Parameter], x: List[float]) -> None:
    by_id = {c.cid: c for c in net.components}
    for p, v in zip(params, x):
        c = by_id.get(p.cid)
        if c is not None:
            c.params[p.key] = float(max(p.lo, min(p.hi, v)))


def measure(net: Network, spec: Spec, ana: Analysis) -> Dict[str, float]:
    res = net.sweep(ana)
    freqs = res.freqs
    lo, hi = spec.f1_ghz * 1e9, spec.f2_ghz * 1e9
    idx = [i for i, f in enumerate(freqs) if lo - 1e-6 <= f <= hi + 1e-6] or \
          list(range(len(freqs)))
    s11 = [res.db(1, 1)[i] for i in idx]
    n = res.n_ports()
    s21 = [res.db(2, 1)[i] for i in idx] if n >= 2 else [0.0] * len(idx)
    out = {"s11_max_db": max(s11), "s11_min_db": min(s11),
           "s21_min_db": min(s21), "s21_max_db": max(s21),
           "points": float(len(idx))}
    if spec.kind == "s21at":
        target = spec.f1_ghz * 1e9
        k = min(range(len(freqs)), key=lambda i: abs(freqs[i] - target))
        out["s21_at_db"] = res.db(2, 1)[k] if n >= 2 else 0.0
        out["f_at_hz"] = freqs[k]
    return out


def cost_of(metrics: Dict[str, float], spec: Spec) -> float:
    if spec.kind == "s11":
        return metrics["s11_max_db"] - spec.target_db
    if spec.kind == "s21min":
        return spec.target_db - metrics["s21_min_db"]
    # s21at：指定频点插损贴近目标
    return abs(metrics.get("s21_at_db", 0.0) - spec.target_db)


def _nelder_mead(fun: Callable[[List[float]], float], x0: List[float],
                 lo: List[float], hi: List[float], max_iter: int,
                 tol: float = 1e-6) -> Tuple[List[float], float, List[Tuple[float, List[float]]]]:
    n = len(x0)
    clip = lambda x: [max(lo[i], min(hi[i], x[i])) for i in range(n)]
    simp = [clip(list(x0))]
    for i in range(n):
        x = list(x0)
        step = 0.2 * (hi[i] - lo[i]) if hi[i] > lo[i] else 0.05 * max(abs(x0[i]), 1e-3)
        x[i] = max(lo[i], min(hi[i], x[i] + step))
        simp.append(clip(x))
    vals = [fun(p) for p in simp]
    history: List[Tuple[float, List[float]]] = []
    for it in range(max_iter):
        order = sorted(range(n + 1), key=lambda i: vals[i])
        simp = [simp[i] for i in order]
        vals = [vals[i] for i in order]
        history.append((vals[0], list(simp[0])))
        if abs(vals[-1] - vals[0]) < tol:
            break
        centroid = [sum(simp[i][j] for i in range(n)) / n for j in range(n)]
        xr = clip([centroid[j] + (centroid[j] - simp[-1][j]) for j in range(n)])
        fr = fun(xr)
        if fr < vals[0]:
            xe = clip([centroid[j] + 2 * (centroid[j] - simp[-1][j]) for j in range(n)])
            fe = fun(xe)
            if fe < fr:
                simp[-1], vals[-1] = xe, fe
            else:
                simp[-1], vals[-1] = xr, fr
        elif fr < vals[-2]:
            simp[-1], vals[-1] = xr, fr
        else:
            xc = clip([centroid[j] + 0.5 * (simp[-1][j] - centroid[j]) for j in range(n)])
            fc = fun(xc)
            if fc < vals[-1]:
                simp[-1], vals[-1] = xc, fc
            else:
                for i in range(1, n + 1):
                    simp[i] = clip([simp[0][j] + 0.5 * (simp[i][j] - simp[0][j])
                                    for j in range(n)])
                    vals[i] = fun(simp[i])
    order = sorted(range(n + 1), key=lambda i: vals[i])
    return simp[order[0]], vals[order[0]], history


def optimize(net: Network, params: List[Parameter], spec: Spec,
             ana: Optional[Analysis] = None, max_iter: int = 160) -> Result:
    if not params:
        return Result(False, 0.0, [], message="没有可优化参数")
    ana = ana or Analysis(spec.f1_ghz, spec.f2_ghz, 201)
    x0 = [max(p.lo, min(p.hi, p.value)) for p in params]
    lo = [p.lo for p in params]
    hi = [p.hi for p in params]
    calls = {"n": 0}

    def fun(x: List[float]) -> float:
        calls["n"] += 1
        apply_values(net, params, x)
        try:
            return cost_of(measure(net, spec, ana), spec)
        except Exception:
            return 1e9

    best_x, best_f, hist = _nelder_mead(fun, x0, lo, hi, max_iter)
    apply_values(net, params, best_x)
    metrics = measure(net, spec, ana)
    for p, v in zip(params, best_x):
        p.value = v
    return Result(True, best_f, params, hist, metrics,
                  f"迭代 {len(hist)} 次，评估 {calls['n']} 次")
