"""Canvas 绘图：幅度-频率曲线 + Smith 圆图（不依赖 matplotlib）。"""
from __future__ import annotations

import math
import tkinter as tk
from typing import List, Optional, Tuple

from ..engine import SweepResult
from ..rfmath import fmt_db, fmt_vswr, fmt_num
from ..units import fmt_freq_smart

BG = "#ffffff"
FG = "#1f2937"
GRID = "#e5e7eb"
AXIS = "#6b7280"
CURVE_COLORS = ["#2563eb", "#dc2626", "#16a34a", "#d97706"]


def set_theme(pal: dict) -> None:
    """由主题模块推送配色（浅色/深色）。"""
    global BG, FG, GRID, AXIS, CURVE_COLORS
    BG = pal.get("canvas", BG)
    FG = pal.get("fg", FG)
    GRID = pal.get("grid", GRID)
    AXIS = pal.get("axis", AXIS)
    CURVE_COLORS = list(pal.get("curve", CURVE_COLORS))


def nice_ticks(lo: float, hi: float, n: int = 7) -> List[float]:
    """取"好看"的刻度（1/2/2.5/5 × 10^k）。"""
    if not (hi > lo):
        return [lo]
    raw = (hi - lo) / max(n - 1, 1)
    exp = math.floor(math.log10(raw)) if raw > 0 else 0
    base = 10.0 ** exp
    step = base
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * base + 1e-15:
            step = m * base
            break
    start = math.ceil(lo / step) * step
    out = []
    v = start
    while v <= hi + step * 1e-9:
        out.append(round(v, 12))
        v += step
        if len(out) > 200:
            break
    return out


def fmt_tick(v: float) -> str:
    if abs(v) >= 1000:
        return f"{v:.0f}"
    if abs(v) >= 10:
        return f"{v:.0f}"
    if abs(v) >= 1:
        return f"{v:.3g}"
    return f"{v:.3g}"


class BasePlot(tk.Canvas):
    def __init__(self, master, **kw):
        super().__init__(master, background=BG, highlightthickness=0, **kw)
        self._cw = int(kw.get("width", 720))
        self._ch = int(kw.get("height", 420))
        self._funit = "MHz"
        self._fdiv = 1e6
        self._resize_job = None
        self._last_size = None
        self.bind("<Configure>", self._on_resize)
        self.bind("<Destroy>", self._on_destroy)

    def _on_resize(self, ev):
        """窗口拖动时合并重绘。

        拖动一次窗口会触发几十上百个 <Configure>；每个都整图重画的话，
        主线程会被绘图吃掉（实测 4.6 ms/次 × 60~100 次 ≈ 0.3~0.5 s 卡顿）。
        这里只同步更新尺寸（绘制代码随时要读 _cw/_ch），重绘交给 33 ms
        后的定时器做一次，期间的新事件一律合并掉。
        """
        w, h = max(ev.width, 120), max(ev.height, 120)
        self._cw, self._ch = w, h          # 同步更新，不能延迟
        if (w, h) == self._last_size:
            return                          # 尺寸没变，不排重绘
        self._last_size = (w, h)
        if self._resize_job is not None:
            return                          # 已有排队的重绘，合并
        self._resize_job = self.after(33, self._flush_resize)

    def _flush_resize(self):
        self._resize_job = None
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self.redraw()

    def _on_destroy(self, ev):
        if ev.widget is not self:
            return
        if self._resize_job is not None:
            try:
                self.after_cancel(self._resize_job)
            except Exception:
                pass
            self._resize_job = None

    def set_funit(self, unit: str):
        """设置频率显示单位（Hz/kHz/MHz/GHz），并重绘。"""
        try:
            from ..units import FREQ_UNITS
            self._fdiv = FREQ_UNITS[unit]
        except Exception:
            self._fdiv, unit = 1e6, "MHz"
        self._funit = unit
        self.redraw()

    def redraw(self):
        pass

    def empty_hint(self, text: str):
        self.create_text(self._cw / 2, self._ch / 2, text=text,
                         fill="#9ca3af", font=("Microsoft YaHei UI", 12))


class MagnitudePlot(BasePlot):
    """直角坐标图 — 支持三种测量：幅度(dB) / 驻波比(VSWR) / 群时延(ns)。"""

    MODES = {"dB": "幅度 (dB)", "vswr": "驻波比 VSWR", "gd": "群时延 (ns)",
             "rl": "回波损耗 (dB)"}

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.result: Optional[SweepResult] = None
        self.cursor: int = -1
        self.ref: Optional[SweepResult] = None
        self.ref_name = "参考文件"
        self.mode = "dB"
        self.hover_idx = -1
        self.pinned_idx = -1
        self.on_readout = None
        self._geom = None
        self.bind("<Motion>", self._on_motion)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Double-Button-1>", lambda e: self.clear_marker())

    def set_mode(self, mode: str):
        if mode in self.MODES:
            self.mode = mode
            self.redraw()

    def set_cursor(self, idx: int, readout=None) -> None:
        self.cursor = idx
        self.redraw()
        if idx < 0 or not self.result or not self.result.freqs:
            return
        k = max(0, min(idx, len(self.result.freqs) - 1))
        L, T, pw, ph, x0, x1, ymin, ymax = self._geom
        f = self.result.freqs[k] / 1e9
        px = L + (f - x0) / (x1 - x0) * pw
        self.create_line(px, T, px, T + ph, fill="#f59e0b", width=2, dash=(5, 3))
        n = self.result.n_ports()
        for i in range(1, n + 1):
            for j in range(1, n + 1):
                vals = self._values(self.result, i, j)
                if not vals:
                    continue
                v = max(min(vals[k], ymax), ymin)
                py = T + (ymax - v) / (ymax - ymin) * ph
                self.create_oval(px - 4, py - 4, px + 4, py + 4,
                                 fill="#f59e0b", outline="#b45309")
        if readout:
            self.create_text(L + 8, T + 8, anchor="nw", text=readout,
                             fill="#b45309", font=("Consolas", 9))

    def set_data(self, result: Optional[SweepResult], ref: Optional[SweepResult] = None):
        self.result = result
        self.ref = ref
        self.pinned_idx = -1
        self.hover_idx = -1
        self.redraw()

    # ---------- 鼠标定位读数 ----------
    def _idx_at(self, x: float) -> int:
        if not self.result or not self.result.freqs or not self._geom:
            return -1
        L, T, pw, ph, x0, x1, ymin, ymax = self._geom
        if not (L <= x <= L + pw):
            return -1
        f = x0 + (x - L) / pw * (x1 - x0)
        div = getattr(self, "_fdiv", 1e9)
        freqs = [fr / div for fr in self.result.freqs]
        k = min(range(len(freqs)), key=lambda i: abs(freqs[i] - f))
        return k

    def marker_text(self, k: int) -> str:
        res = self.result
        ang = math.degrees(math.atan2(res.s[k][0][0].imag, res.s[k][0][0].real))
        line1 = (f"f={fmt_freq_smart(res.freqs[k], self._funit)}"
                 f"   S11={fmt_db(res.db(1,1)[k])} dB")
        if res.n_ports() >= 2:
            line1 += f"   S21={fmt_db(res.db(2,1)[k])} dB"
        line2 = (f"VSWR={fmt_vswr(res.vswr(1)[k], 3)}   "
                 f"GD={fmt_num(res.group_delay_ns(1,1)[k], 3)} ns   ∠S11={ang:.1f}°")
        return line1 + "\n" + line2

    def _draw_marker(self, k: int, tag: str) -> None:
        L, T, pw, ph, x0, x1, ymin, ymax = self._geom
        res = self.result
        f = res.freqs[k] / getattr(self, "_fdiv", 1e9)
        px = L + (f - x0) / (x1 - x0) * pw
        self.create_line(px, T, px, T + ph, fill="#dc2626", width=1,
                         dash=(4, 3), tags=tag)
        n = res.n_ports()
        for i in range(1, n + 1):
            for j in range(1, n + 1):
                vals = self._values(res, i, j)
                if not vals:
                    continue
                v = max(min(vals[k], ymax), ymin)
                py = T + (ymax - v) / (ymax - ymin) * ph
                self.create_oval(px - 4, py - 4, px + 4, py + 4,
                                 fill="#dc2626", outline="white", tags=tag)
        text = self.marker_text(k)
        lines = text.split("\n")
        tw = max(240, min(pw, int(max(len(x) for x in lines) * 7.2) + 20))
        bx = L + 6
        by = T + 6
        self.create_rectangle(bx, by, bx + tw, by + 34, fill="#fffbeb",
                              outline="#dc2626", tags=tag)
        self.create_text(bx + 8, by + 9, anchor="nw", text=lines[0], fill="#7f1d1d",
                         font=("Consolas", 8), tags=tag)
        self.create_text(bx + 8, by + 24, anchor="nw", text=lines[1], fill="#7f1d1d",
                         font=("Consolas", 8), tags=tag)

    def _on_motion(self, ev) -> None:
        if not self.result or not self._geom:
            return
        k = self._idx_at(ev.x)
        if k < 0:
            self.delete("hover")
            self.hover_idx = -1
            return
        self.hover_idx = k
        self._emit_freq(k)
        self.delete("hover")
        self._draw_marker(k, "hover")
        if self.on_readout:
            self.on_readout(self.marker_text(k))

    def _on_click(self, ev) -> None:
        k = self._idx_at(ev.x)
        if k < 0:
            return
        if self.pinned_idx == k:
            self.clear_marker()
            return
        self.delete("pin")
        self.pinned_idx = k
        self._emit_freq(k)
        self._draw_marker(k, "pin")
        if self.on_readout:
            self.on_readout(self.marker_text(k))

    def clear_marker(self) -> None:
        self.pinned_idx = -1
        self.hover_idx = -1
        self.delete("pin")
        self.delete("hover")

    def _emit_freq(self, k: int) -> None:
        """把选中频点回传出去。单位 GHz，与 mark_at_freq 入参一致。"""
        cb = getattr(self, "on_freq_pick", None)
        if cb is None or not self.result or not self.result.freqs:
            return
        if 0 <= k < len(self.result.freqs):
            try:
                cb(self.result.freqs[k] / 1e9)
            except Exception:
                pass

    def mark_at_freq(self, f_ghz: float) -> str:
        if not self.result or not self.result.freqs:
            return ""
        k = min(range(len(self.result.freqs)),
                key=lambda i: abs(self.result.freqs[i] / 1e9 - f_ghz))
        self.pinned_idx = k
        self.redraw()
        self._draw_marker(k, "pin")
        text = self.marker_text(k)
        if self.on_readout:
            self.on_readout(text)
        return text

    def _values(self, res: SweepResult, i: int, j: int) -> List[float]:
        if self.mode == "vswr":
            return res.vswr(i) if i == j else []
        if self.mode == "gd":
            return res.group_delay_ns(i, j)
        if self.mode == "rl":
            return [-v for v in res.db(i, j)] if i == j else []
        return res.db(i, j)

    def redraw(self):
        self.delete("all")
        w, h = self._cw, self._ch
        L, R, T, B = 66, 20, 38, 50
        pw, ph = max(w - L - R, 40), max(h - T - B, 40)
        title = f"直角坐标图 · {self.MODES.get(self.mode, self.mode)}"
        self.create_text(w / 2, 18, text=title, fill=FG,
                         font=("Microsoft YaHei UI", 11, "bold"))
        if not self.result or not self.result.freqs:
            self.empty_hint("尚无数据 —— 点击「运行仿真」")
            return
        freqs = [f / self._fdiv for f in self.result.freqs]
        x0, x1 = min(freqs), max(freqs)
        if x1 - x0 < 1e-12:
            x1 = x0 + 1e-9
        n = self.result.n_ports()
        all_vals = []
        for i in range(1, n + 1):
            for j in range(1, n + 1):
                all_vals.extend(self._values(self.result, i, j))
        if not all_vals:
            all_vals = [0.0]
        if self.mode in ("db", "dB"):
            ymin = min(max(math.floor(min(all_vals) / 10) * 10, -140), -20)
            ymax = 5.0
        elif self.mode == "vswr":
            # 阻带 |S11|→1 时 VSWR→∞，显示上限 20 保证通带可读
            ymin, ymax = 1.0, 20.0
        else:
            lo, hi = min(all_vals), max(all_vals)
            if hi - lo < 1e-9:
                lo, hi = lo - 1, hi + 1
            pad = (hi - lo) * 0.1
            ymin, ymax = lo - pad, hi + pad

        self._geom = (L, T, pw, ph, x0, x1, ymin, ymax)

        def XY(f, v):
            return (L + (f - x0) / (x1 - x0) * pw,
                    T + (ymax - v) / (ymax - ymin) * ph)

        # 边框 + 网格
        self.create_rectangle(L, T, L + pw, T + ph, outline=AXIS)
        for tx in nice_ticks(x0, x1, 8):
            px, _ = XY(tx, ymin)
            self.create_line(px, T, px, T + ph, fill=GRID)
            self.create_text(px, T + ph + 14, text=fmt_tick(tx), fill=AXIS,
                             font=("Consolas", 8))
        for ty in nice_ticks(ymin, ymax, 7):
            _, py = XY(x0, ty)
            self.create_line(L, py, L + pw, py, fill=GRID)
            self.create_text(L - 8, py, text=f"{ty:g}", anchor="e", fill=AXIS,
                             font=("Consolas", 8))
        self.create_text(L + pw / 2, T + ph + 36, text="频率 (" + self._funit + ")", fill=FG,
                         font=("Microsoft YaHei UI", 9))
        ylabel = {"dB": "幅度 (dB)", "vswr": "VSWR（上限 20）",
                  "gd": "群时延 (ns)"}.get(self.mode, "")
        self.create_text(16, T + ph / 2, text=ylabel, fill=FG, angle=90,
                         font=("Microsoft YaHei UI", 9))
        self.create_text(L, T - 14, anchor="w",
                         text=f"Z0 = {self.result.z0:g} Ω    {len(freqs)} 个频点",
                         fill=AXIS, font=("Microsoft YaHei UI", 8))
        if getattr(self, "pinned_idx", -1) is not None and self.pinned_idx >= 0:
            try:
                self._draw_marker(min(self.pinned_idx, len(freqs) - 1), "pin")
            except Exception:
                pass

        # 曲线（S11/S21 优先，S12/S22 更细）
        order = []
        for i in range(1, n + 1):
            for j in range(1, n + 1):
                order.append((i, j))
        order.sort(key=lambda p: (p not in ((1, 1), (2, 1))))
        legend = []
        for idx, (i, j) in enumerate(order):
            vals = self._values(self.result, i, j)
            if not vals:
                continue
            color = CURVE_COLORS[idx % len(CURVE_COLORS)]
            width = 1.8 if (i, j) in ((1, 1), (2, 1)) else 1.0
            pts = []
            for f, v in zip(freqs, vals):
                vv = v
                if self.mode == "vswr":
                    vv = min(max(v, ymin), ymax)
                pts.extend(XY(f, max(min(vv, ymax), ymin)))
            if len(pts) >= 4:
                self.create_line(*pts, fill=color, width=width)
            legend.append((f"S{i}{j}", color))

        # 参考文件（灰色虚线）
        if self.ref and self.ref.freqs:
            rf = [f / 1e9 for f in self.ref.freqs]
            for (i, j) in ((1, 1), (2, 1)):
                if i > self.ref.n_ports() or j > self.ref.n_ports():
                    continue
                pts = []
                for f, v in zip(rf, self.ref.db(i, j)):
                    if x0 - 1e-9 <= f <= x1 + 1e-9:
                        pts.extend(XY(f, max(min(v, ymax), ymin)))
                if len(pts) >= 4:
                    self.create_line(*pts, fill="#9ca3af", width=1.0, dash=(4, 3))
            self.create_text(L + pw - 10, T + ph - 12, anchor="se",
                             text=f"灰色虚线：{self.ref_name}", fill="#9ca3af",
                             font=("Microsoft YaHei UI", 8))

        # 图例（右上角白底框，避免压曲线）
        if legend:
            lh = 16 * len(legend) + 10
            lw = 62
            lx, ly = L + pw - lw - 8, T + 8
            self.create_rectangle(lx, ly, lx + lw, ly + lh, fill="#ffffff",
                                  outline="#d1d5db")
            for k, (label, color) in enumerate(legend):
                yy = ly + 8 + k * 16
                self.create_line(lx + 6, yy, lx + 22, yy, fill=color, width=2)
                self.create_text(lx + 26, yy, anchor="w", text=label, fill=color,
                                 font=("Consolas", 8))


class SmithPlot(BasePlot):
    """阻抗 Smith 圆图（Γ 平面），支持鼠标读数与标记。"""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.result: Optional[SweepResult] = None
        self.which = (1, 1)
        self._hover = -1
        self._markers: List[int] = []
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Button-3>", self._on_right)

    def set_data(self, result: Optional[SweepResult], which: Tuple[int, int] = (1, 1)):
        self.result = result
        self.which = which
        self._hover = -1
        self._markers = []
        self.redraw()

    def _map(self, g: complex, cx: float, cy: float, R: float) -> Tuple[float, float]:
        return cx + g.real * R, cy - g.imag * R

    # ---------------------------------------------------------------- 交互
    def _geom(self):
        w, h = self._cw, self._ch
        return min(w, h) * 0.34, w / 2, h / 2 + 6

    def _screen_points(self):
        if not self.result or not self.result.freqs:
            return []
        R, cx, cy = self._geom()
        i, j = self.which
        pts = []
        for k, f in enumerate(self.result.freqs):
            g = self.result.s[k][i - 1][j - 1]
            pts.append((k, f, g, *self._map(g, cx, cy, R)))
        return pts

    def _nearest(self, ev) -> int:
        best, bi = 1e9, -1
        for k, f, g, x, y in self._screen_points():
            d = (x - ev.x) ** 2 + (y - ev.y) ** 2
            if d < best:
                best, bi = d, k
        return bi if best <= 22 ** 2 else -1

    def _on_motion(self, ev):
        k = self._nearest(ev)
        if k != self._hover:
            self._hover = k
            self.redraw()

    def _on_leave(self, _ev):
        if self._hover != -1:
            self._hover = -1
            self.redraw()

    def _on_click(self, ev):
        k = self._nearest(ev)
        if k >= 0:
            if k in self._markers:
                self._markers.remove(k)
            else:
                self._markers.append(k)
                self._markers = self._markers[-4:]
            self.redraw()

    def _on_right(self, _ev):
        if self._markers:
            self._markers.pop()
            self.redraw()

    # ---------------------------------------------------------------- 绘制
    def redraw(self):
        self.delete("all")
        w, h = self._cw, self._ch
        R, cx, cy = self._geom()
        i, j = self.which
        self.create_text(w / 2, 18, text=f"Smith 圆图（S{i}{j}） · 拖动/悬停读数，左键标记，右键取消",
                         fill=FG, font=("Microsoft YaHei UI", 10, "bold"))
        self.create_oval(cx - R, cy - R, cx + R, cy + R, outline=AXIS, width=1.5)
        # 等电阻圆
        for r in (0.0, 0.5, 1.0, 2.0, 5.0):
            c0 = r / (1 + r)
            rad = 1 / (1 + r)
            x0, y0 = self._map(complex(c0 - rad, 0), cx, cy, R)
            x1, y1 = self._map(complex(c0 + rad, 0), cx, cy, R)
            self.create_oval(x0, y0, x1, y1, outline=GRID, width=1)
        # 等电抗圆
        for x in (-5.0, -2.0, -1.0, -0.5, 0.5, 1.0, 2.0, 5.0):
            c0 = 1.0
            cyy = 1.0 / x
            rad = abs(1.0 / x)
            x0, y0 = self._map(complex(c0 - rad, cyy), cx, cy, R)
            x1, y1 = self._map(complex(c0 + rad, cyy), cx, cy, R)
            self.create_oval(x0, y0, x1, y1, outline=GRID, width=1)
        self.create_line(cx - R, cy, cx + R, cy, fill=GRID, width=1)
        self.create_line(cx, cy - R, cx, cy + R, fill=GRID, width=1)

        pts = self._screen_points()
        if not pts:
            self.empty_hint("尚无数据 —— 运行仿真后显示 S11 轨迹")
            return
        # 轨迹
        coords = []
        for k, f, g, x, y in pts:
            coords += [x, y]
        if len(coords) >= 4:
            self.create_line(*coords, fill=CURVE_COLORS[0], width=2)
        # 频点标记（起点/中点/终点）
        for idx in (0, len(pts) // 2, len(pts) - 1):
            k, f, g, x, y = pts[idx]
            self.create_oval(x - 3, y - 3, x + 3, y + 3, fill="#9ca3af", outline="")
            self.create_text(x, y - 10, text=f"{f/1e9:.3g}", fill="#6b7280",
                             font=("Microsoft YaHei UI", 7))
        # 持久标记
        for n, k in enumerate(self._markers, 1):
            if k >= len(pts):
                continue
            _, f, g, x, y = pts[k]
            self.create_oval(x - 6, y - 6, x + 6, y + 6, outline="#dc2626", width=2)
            self.create_text(x + 9, y + 9, text=f"M{n} {f/1e9:.3g}G",
                             fill="#dc2626", font=("Microsoft YaHei UI", 8))
        # 悬停读数
        if 0 <= self._hover < len(pts):
            k, f, g, x, y = pts[self._hover]
            self.create_oval(x - 5, y - 5, x + 5, y + 5, fill="#f59e0b",
                             outline="#b45309", width=1)
            self._draw_readout(f, g, x, y)

    def _draw_readout(self, f: float, g: complex, x: float, y: float):
        z0 = self.result.z0 if self.result else 50.0
        denom = 1 - g
        zin = z0 * (1 + g) / denom if abs(denom) > 1e-12 else complex(1e12, 0)
        mag = min(abs(g), 1.0)
        vswr = (1 + mag) / (1 - mag) if mag < 1 else float("inf")
        rl = -20 * math.log10(mag) if mag > 1e-12 else 999.0
        lines = [f"f = {fmt_freq_smart(f, self._funit)}",
                 f"Γ = {g.real:+.4f}{g.imag:+.4f}j",
                 f"Zin = {zin.real:.3f}{zin.imag:+.3f}j Ω",
                 f"VSWR = {fmt_vswr(vswr, 4)}",
                 f"回波损耗 = {rl:.2f} dB"]
        w, h = self._cw, self._ch
        bw, bh = 190, 96
        bx = x + 14 if x + bw + 20 < w else x - bw - 14
        by = y - bh - 10 if y - bh - 10 > 24 else y + 14
        self.create_rectangle(bx, by, bx + bw, by + bh, fill="#fffbeb",
                              outline="#f59e0b", width=1)
        for n, s in enumerate(lines):
            self.create_text(bx + 8, by + 10 + n * 17, text=s, anchor="w",
                             fill="#78350f", font=("Consolas", 8))