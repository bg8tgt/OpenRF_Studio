"""圆图工作台（全新重写的界面层）。

结构：
  ChartCanvas  —— 纯 Canvas 绘制的史密斯圆图（单位圆、等 r/x 圆、VSWR 圆、
                  波长刻度、负载/输入标记、仿真 S11 叠加、缩放/平移/拖拽）
  LMatchDialog —— L 型匹配解列表（可一键落到电路）
  RFWorkbench  —— 左侧参数/按钮/显示选项，右侧圆图与读数

交互约定：
  * 圆内拖动 = 移动负载点（可实时重建电路并仿真）；
  * 圆外拖动 = 平移；滚轮缩放；双击复位；
  * 悬停显示 Γ、|Γ|、角度与朝源/朝负载波长数。
"""
# 功能参考：著作权人自有软件（经授权）；代码为本项目独立实现。

from __future__ import annotations

import math
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Optional, Tuple

from .. import rfmath as R
from .. import smith as S
from ..engine import SweepResult
from . import theme

FONT = ("Microsoft YaHei UI", 9)
FONT_S = ("Microsoft YaHei UI", 8)
FONT_MONO = ("Consolas", 8)
FONT_T = ("Microsoft YaHei UI", 10, "bold")

C_GRID = "#e5e7eb"
C_AXIS = "#9ca3af"
C_UNIT = "#374151"
C_LOAD = "#059669"
C_IN = "#dc2626"
C_OVER = "#2563eb"
C_RIM = "#6b7280"
PAL = theme.palette()


def _sync_palette() -> None:
    global PAL, C_GRID, C_AXIS, C_UNIT, C_LOAD, C_IN, C_OVER, C_RIM
    PAL = theme.palette()
    C_GRID = PAL["grid"]
    C_AXIS = PAL["axis"]
    C_UNIT = PAL["fg"]
    C_LOAD = PAL["curve"][2]
    C_IN = PAL["curve"][1]
    C_OVER = PAL["curve"][0]
    C_RIM = PAL["muted"]


_FREQ_UNIT = "MHz"          # 全局频率显示单位（由主界面推送）


def _fmt_freq(hz: float) -> str:
    """频率格式化统一走 units.fmt_freq，避免两处格式各写一套。"""
    from ..units import FREQ_UNITS, fmt_freq_smart
    u = _FREQ_UNIT if _FREQ_UNIT in FREQ_UNITS else "MHz"
    return fmt_freq_smart(hz, u)


def _fmt_vswr(v: float) -> str:
    return "∞" if not math.isfinite(v) else f"{v:.4f}"


class ChartCanvas(tk.Canvas):
    def __init__(self, master, on_hover: Optional[Callable[[str], None]] = None,
                 on_point: Optional[Callable[[complex], None]] = None, **kw):
        super().__init__(master, background="#ffffff", highlightthickness=0, **kw)
        self.on_hover = on_hover
        self.on_point = on_point
        self.z0 = 50.0
        self.zl = complex(25, 25)
        self.d = 0.0
        self.manual: Optional[complex] = None
        self.overlay: Optional[SweepResult] = None
        self.overlay_ij: Tuple[int, int] = (1, 1)
        self.play_idx: int = -1
        self.opts = {"grid": True, "labels": True, "rim": True,
                     "vswr": True, "load": True, "legend": True,
                     "aux": False, "q": False}
        self._scale = 120.0
        self._cx = 200.0
        self._cy = 200.0
        self._fitted = False
        self._pan: Optional[Tuple[float, float, float, float]] = None
        self.bind("<Configure>", self._on_configure)
        self.bind("<Motion>", self._on_motion)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "_pan", None))
        self.bind("<Double-Button-1>", lambda e: self.reset_view())
        self.bind("<MouseWheel>", self._on_wheel)

    # ---------------------------------------------------------------- 几何
    @property
    def line(self) -> R.Line:
        return R.Line(self.z0, self.zl, self.d)

    @property
    def gamma_load(self) -> complex:
        return self.line.gamma_load

    @property
    def gamma_in(self) -> complex:
        return self.manual if self.manual is not None else self.line.gamma_in

    def to_px(self, g: complex) -> Tuple[float, float]:
        return self._cx + g.real * self._scale, self._cy - g.imag * self._scale

    def to_world(self, x: float, y: float) -> complex:
        return complex((x - self._cx) / self._scale, (self._cy - y) / self._scale)

    def _on_configure(self, _ev=None) -> None:
        if not self._fitted:
            self.fit()
        else:
            self.redraw()

    def fit(self) -> None:
        w, h = max(self.winfo_width(), 200), max(self.winfo_height(), 200)
        self._scale = min(w, h) * 0.40
        self._cx, self._cy = w / 2.0, h / 2.0
        self._fitted = True
        self.redraw()

    def reset_view(self) -> None:
        self.manual = None
        self.fit()

    def zoom(self, factor: float, at: Optional[Tuple[float, float]] = None) -> None:
        if at is None:
            at = (self._cx, self._cy)
        wx, wy = self.to_world(*at)
        self._scale = max(20.0, min(2000.0, self._scale * factor))
        self._cx = at[0] - wx * self._scale
        self._cy = at[1] + wy * self._scale
        self.redraw()

    # ---------------------------------------------------------------- 事件
    def _emit(self) -> None:
        if self.on_point:
            self.on_point(self.gamma_in)

    def _on_press(self, ev) -> None:
        g = self.to_world(ev.x, ev.y)
        if abs(g) <= 1.0:
            self.manual = g
            self.redraw()
            self._emit()
        else:
            self._pan = (ev.x, ev.y, self._cx, self._cy)

    def _on_drag(self, ev) -> None:
        if self._pan:
            x0, y0, cx0, cy0 = self._pan
            self._cx = cx0 + (ev.x - x0)
            self._cy = cy0 + (ev.y - y0)
            self.redraw()
        elif self.manual is not None:
            g = self.to_world(ev.x, ev.y)
            if abs(g) > 0.999:
                g = g / abs(g) * 0.999
            self.manual = g
            self.redraw()
            self._emit()

    def _on_wheel(self, ev) -> None:
        self.zoom(1.1 if ev.delta > 0 else 1 / 1.1, (ev.x, ev.y))

    def _on_motion(self, ev) -> None:
        if not self.on_hover:
            return
        g = self.to_world(ev.x, ev.y)
        tag = ""
        if abs(g) > 1.0:
            tag = "（圆外）"
        elif abs(g.imag) < 1e-9:
            tag = "（实轴）"
        ang = math.atan2(g.imag, g.real)
        self.on_hover(
            f"Γ = {abs(g):.4f} ∠{math.degrees(ang):.1f}° {tag}   "
            f"λ朝源={S.wtg_at(ang):.4f}   λ朝负载={S.wtl_at(ang):.4f}")

    # ---------------------------------------------------------------- 绘制
    def _circle(self, c: R.Circle, color: str, width: float = 1.0) -> None:
        if not math.isfinite(c.r) or c.r > 50:
            return
        x0, y0 = self.to_px(complex(c.cx - c.r, c.cy + c.r))
        x1, y1 = self.to_px(complex(c.cx + c.r, c.cy - c.r))
        self.create_oval(x0, y0, x1, y1, outline=color, width=width)

    def redraw(self) -> None:
        _sync_palette()
        self.configure(background=PAL["canvas"])
        self.delete("all")
        w, h = max(self.winfo_width(), 200), max(self.winfo_height(), 200)
        self.create_text(w / 2, 16, text="史密斯圆图（拖圆内改负载）",
                         font=FONT_T, fill=PAL["fg"])
        # 等 r / 等 x 圆（先画网格，避免覆盖单位圆）
        if self.opts.get("grid"):
            for r in (0.2, 0.5, 1.0, 2.0, 5.0):
                self._circle(R.r_circle(r), C_GRID, 1.0)
            for x in (-5.0, -2.0, -1.0, -0.5, 0.5, 1.0, 2.0, 5.0):
                self._circle(R.x_circle(x), C_GRID, 1.0)
            self.create_line(*self.to_px(-1), *self.to_px(1), fill=C_GRID)
        # 单位圆（最后画，保证可见）
        x0, y0 = self.to_px(-1 - 1j)
        x1, y1 = self.to_px(1 + 1j)
        self.create_oval(x0, y0, x1, y1, outline=C_UNIT, width=1.8)
        # 等 Q 曲线（|X|/R = Q）
        if self.opts.get("q"):
            for qv in (0.5, 1.0, 2.0, 5.0):
                for sgn in (1, -1):
                    pts = []
                    for k in range(80):
                        rr = 10 ** (-2 + 4 * k / 79)
                        g = R.gamma_of_z(complex(rr, sgn * qv * rr), 1.0)
                        if abs(g) <= 1.0:
                            pts.extend(self.to_px(g))
                    if len(pts) >= 4:
                        self.create_line(*pts, fill=C_RIM, dash=(3, 3))
        # VSWR 圆
        if self.opts.get("vswr") and self.opts.get("load"):
            self._circle(R.vswr_circle(self.gamma_load), "#f59e0b")
        # 波长刻度（外圈）
        if self.opts.get("rim"):
            for k in range(0, 360, 15):
                a = math.radians(k)
                p1 = self.to_px(complex(math.cos(a), math.sin(a)))
                p2 = self.to_px(complex(1.03 * math.cos(a), 1.03 * math.sin(a)))
                self.create_line(*p1, *p2, fill=C_RIM)
            self.create_text(*self.to_px(0.9 + 1.12j), text="wtg", fill=C_RIM, font=FONT_S)
            self.create_text(*self.to_px(0.9 - 1.12j), text="wtl", fill=C_RIM, font=FONT_S)
        # 仿真叠加
        if self.overlay and self.overlay.freqs:
            i, j = self.overlay_ij
            pts = []
            for k in range(len(self.overlay.freqs)):
                pts.extend(self.to_px(self.overlay.s[k][i - 1][j - 1]))
            if len(pts) >= 4:
                self.create_line(*pts, fill=C_OVER, width=2, smooth=False)
        # 标记
        gl = self.gamma_load
        if self.opts.get("load"):
            self._marker(gl, C_LOAD, "ΓL")
        gin = self.gamma_in
        self._marker(gin, C_IN, "Γin" if self.manual is not None else "Γin（仿真/模型）")
        # 播放光标
        if self.overlay and 0 <= self.play_idx < len(self.overlay.freqs):
            k = self.play_idx
            g = self.overlay.s[k][0][0]
            x, y = self.to_px(g)
            self.create_oval(x - 7, y - 7, x + 7, y + 7,
                             outline="#f59e0b", width=3)
            fv = self.overlay.freqs[k]
            if fv >= 1e9:
                ftxt = f"{fv/1e9:.3f}G"
            elif fv >= 1e6:
                ftxt = f"{fv/1e6:.3f}M"
            elif fv >= 1e3:
                ftxt = f"{fv/1e3:.3f}k"
            else:
                ftxt = f"{fv:.1f}Hz"
            self.create_text(x + 10, y + 12, text=ftxt,
                             fill="#b45309", font=FONT_S)
        # 图例
        if self.opts.get("legend"):
            self._legend()

    def _marker(self, g: complex, color: str, label: str) -> None:
        x, y = self.to_px(g)
        self.create_oval(x - 4, y - 4, x + 4, y + 4, fill=color, outline="")
        self.create_text(x + 8, y - 8, text=label, fill=color, font=FONT_S)

    def _legend(self) -> None:
        items = [(C_LOAD, "ΓL 负载"), (C_IN, "Γin 输入"),
                 (C_OVER, "仿真 S11"), ("#f59e0b", "VSWR 圆")]
        x, y = 12, 30
        for color, text in items:
            self.create_line(x, y + 6, x + 18, y + 6, fill=color, width=2)
            self.create_text(x + 24, y + 6, text=text, anchor="w",
                             font=FONT_S, fill=PAL["fg"])
            y += 16


class LMatchDialog(tk.Toplevel):
    """L 型匹配解列表；可一键落到电路。"""

    def __init__(self, master, tab, zl: complex, z0: float, f_hz: float):
        super().__init__(master)
        self.title("L 型匹配")
        self.transient(master)
        self.resizable(False, False)
        self.after(50, self._activate)

    def _activate(self):
        """映射后再抓取；失败有限重试。"""
        self._tries = getattr(self, "_tries", 0)
        try:
            if not self.winfo_exists():
                return
            self.lift()
            self.grab_set()
        except Exception:
            self._tries += 1
            if self._tries < 8:
                try:
                    self.after(60, self._activate)
                except Exception:
                    pass

    def destroy(self):
        try:
            self.grab_release()
        except Exception:
            pass
        super().destroy()

    def _noop(self):
        pass
        self.tab = tab
        self.z0, self.zl, self.f = z0, zl, f_hz
        self.solutions = S.solve_l_network(zl, z0, f_hz)
        self._build()
        self.geometry("640x420")
        self.update_idletasks()
        try:
            x = master.winfo_rootx() + (master.winfo_width() - 640) // 2
            y = master.winfo_rooty() + (master.winfo_height() - 420) // 3
            sw, sh = master.winfo_screenwidth(), master.winfo_screenheight()
            x = max(0, min(int(x), max(sw - 648, 0)))
            y = max(0, min(int(y), max(sh - 468, 0)))
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass
        self.bind("<Escape>", lambda e: self.destroy())

    def _build(self) -> None:
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text=f"ZL = {S.fmt_complex(self.zl, 3)} Ω",
                  font=FONT_T).pack(side="left")
        ttk.Label(top, text=f"Z0 = {self.z0:g} Ω", font=FONT_T).pack(side="left", padx=16)
        ttk.Label(top, text=f"f = {_fmt_freq(self.f)}", font=FONT_T).pack(side="left")

        self.lst = tk.Listbox(self, height=8, font=FONT_MONO, exportselection=False)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.lst.yview)
        self.lst.configure(yscrollcommand=sb.set)
        self.lst.pack(side="left", fill="both", expand=True, padx=(10, 0))
        sb.pack(side="left", fill="y")
        self.info = ttk.Label(self, text="", justify="left", font=FONT_MONO,
                              wraplength=600)
        self.info.pack(fill="x", padx=10, pady=6)
        bar = ttk.Frame(self, padding=10)
        bar.pack(fill="x")
        ttk.Button(bar, text="关闭", command=self.destroy,
                   padding=(14, 5)).pack(side="right", padx=4)
        ttk.Button(bar, text="应用到电路", command=self._apply,
                   padding=(14, 5)).pack(side="right", padx=4)
        if not self.solutions:
            self.info.configure(text="无可行解：负载已匹配，或超出 L 型网络可匹配范围。")
            return
        for k, s in enumerate(self.solutions, 1):
            self.lst.insert("end", f"{k}. {s.summary_text()}")
        self.lst.selection_set(0)
        self.lst.bind("<<ListboxSelect>>", lambda e: self._detail())
        self._detail()

    def _detail(self) -> None:
        sel = self.lst.curselection()
        if not sel or sel[0] >= len(self.solutions):
            return
        s = self.solutions[sel[0]]
        self.info.configure(text=f"{s.desc}\n{s.elements_text()}\n"
                                 f"Q = {s.q:.4f}   校验 Zin = {S.fmt_complex(s.z_result, 3)} Ω")

    def _apply(self) -> None:
        sel = self.lst.curselection()
        if not sel or sel[0] >= len(self.solutions):
            return
        if self.tab.apply_solution(self.solutions[sel[0]]):
            self.destroy()


class RFWorkbench(ttk.Frame):
    READOUTS = (
        ("gl", "ΓL"), ("gin", "Γin"), ("zin", "Zin (Ω)"), ("yin", "Yin (S)"),
        ("vswr", "VSWR"), ("mag", "|ΓL|"), ("phase", "∠ΓL"),
        ("rl", "回波损耗 dB"), ("ml", "失配损耗 dB"), ("pr", "反射功率 %"),
        ("lam", "波长 λ"), ("plen", "物理线长"), ("wtg", "λ 朝源"), ("wtl", "λ 朝负载"),
    )

    def __init__(self, master, app=None):
        super().__init__(master, padding=0)
        self.app = app
        self.var_z0 = tk.StringVar(value="50")
        self.var_rl = tk.StringVar(value="25")
        self.var_xl = tk.StringVar(value="25")
        self.var_f = tk.StringVar(value="10")
        self.var_vf = tk.StringVar(value="1.0")
        self.var_d = tk.StringVar(value="0")
        self.var_hover = tk.StringVar(value="悬停圆图查看读数")
        self.var_live = tk.BooleanVar(value=True)
        self.var_norm = tk.BooleanVar(value=False)
        self.var_funit = tk.StringVar(value="MHz")
        self._funit_last = "MHz"
        self.vars = {k: tk.StringVar(value="—") for k, _ in self.READOUTS}
        self.opt_vars = {"grid": tk.BooleanVar(value=True),
                         "labels": tk.BooleanVar(value=True),
                         "rim": tk.BooleanVar(value=True),
                         "vswr": tk.BooleanVar(value=True),
                         "load": tk.BooleanVar(value=True),
                         "legend": tk.BooleanVar(value=True),
                         "aux": tk.BooleanVar(value=False),
                         "q": tk.BooleanVar(value=False)}
        self.model = R.Line(50.0, complex(25, 25), 0.0)
        self.result: Optional[SweepResult] = None
        self.last_solution = None
        self._live_after = None
        self._build()
        self.compute(quiet=True)

    # ---------------------------------------------------------------- 构建
    def _build(self) -> None:
        left = ttk.Frame(self, padding=(10, 8))
        left.pack(side="left", fill="y")
        right = ttk.Frame(self, padding=(0, 8, 8, 8))
        right.pack(side="right", fill="both", expand=True)

        box = ttk.LabelFrame(left, text=" 负载与传输线 ", padding=8)
        box.pack(fill="x")
        fields = (("特性阻抗 Z0 (Ω)", self.var_z0), ("负载电阻 RL (Ω)", self.var_rl),
                  ("负载电抗 XL (Ω)", self.var_xl), ("频率", self.var_f),
                  ("速度因子 VF", self.var_vf), ("距离 d (λ)", self.var_d))
        for row, (text, var) in enumerate(fields):
            ttk.Label(box, text=text).grid(row=row, column=0, sticky="w", pady=1)
            ent = ttk.Entry(box, textvariable=var, width=12)
            ent.grid(row=row, column=1, sticky="w", padx=(6, 0))
            ent.bind("<Return>", lambda e: self.compute())
        ttk.Combobox(box, textvariable=self.var_funit,
                     values=["Hz", "kHz", "MHz", "GHz"], state="readonly",
                     width=5).grid(row=3, column=2, sticky="w", padx=(4, 0))
        self.var_funit.trace_add("write", lambda *a: self._on_funit())

        ops = ttk.Frame(left)
        ops.pack(fill="x", pady=(8, 0))
        for k, (text, cmd) in enumerate((
                ("计算", self.compute), ("取仿真 S11", self.take_s11),
                ("适应窗口", self.canvas_fit), ("导出 SVG", self.export_svg),
                ("L 型匹配…", self.open_match), ("应用上次解", self.apply_last))):
            ttk.Button(ops, text=text, command=cmd, padding=(10, 4)).grid(
                row=k // 2, column=k % 2, sticky="ew", padx=1, pady=2)
        ops.columnconfigure(0, weight=1)
        ops.columnconfigure(1, weight=1)
        ttk.Checkbutton(left, text="实时联动（拖拽 → 重建电路并仿真）",
                        variable=self.var_live).pack(anchor="w", pady=(6, 0))
        ttk.Checkbutton(left, text="归一化显示（Z/Y 除以 Z0）",
                        variable=self.var_norm,
                        command=self.refresh_readouts).pack(anchor="w")
        ttk.Button(left, text="立即同步到电路", command=self.sync_live,
                   padding=(10, 4)).pack(fill="x", pady=(4, 0))

        disp = ttk.LabelFrame(left, text=" 显示选项 ", padding=8)
        disp.pack(fill="x", pady=(8, 0))
        names = (("grid", "网格"), ("labels", "标注"), ("rim", "波长图带"),
                 ("vswr", "驻波比圆"), ("load", "显示负载"),
                 ("legend", "图例"), ("aux", "辅助圆"), ("q", "Q 圆"))
        for k, (key, label) in enumerate(names):
            ttk.Checkbutton(disp, text=label, variable=self.opt_vars[key],
                            command=self._apply_opts).grid(
                row=k // 2, column=k % 2, sticky="w", padx=2)

        self.canvas = ChartCanvas(right, on_hover=self._on_hover,
                                  on_point=self._on_point, width=360, height=360)
        self.canvas.pack(fill="both", expand=True)

        rd = ttk.LabelFrame(right, text=" 计算结果 ", padding=(8, 4))
        rd.pack(fill="x", pady=(4, 0))
        for k, (key, label) in enumerate(self.READOUTS):
            cell = ttk.Frame(rd)
            cell.grid(row=k // 3, column=k % 3, sticky="w", padx=6, pady=1)
            ttk.Label(cell, text=label, foreground="#6b7280",
                      font=("Microsoft YaHei UI", 7)).pack(anchor="w")
            ttk.Label(cell, textvariable=self.vars[key], font=FONT_MONO).pack(anchor="w")
        ttk.Label(right, textvariable=self.var_hover, font=FONT_MONO,
                  foreground="#374151").pack(anchor="w", pady=(4, 0))

    # ---------------------------------------------------------------- 输入
    def read_inputs(self):
        try:
            z0 = float(self.var_z0.get())
            rl = float(self.var_rl.get())
            xl = float(self.var_xl.get())
            f_val = float(self.var_f.get())
            vf = float(self.var_vf.get())
            d = float(self.var_d.get())
        except ValueError as e:
            raise ValueError("请输入数字") from e
        if z0 <= 0:
            raise ValueError("Z0 必须 > 0")
        if f_val <= 0:
            raise ValueError("频率必须 > 0")
        if vf <= 0:
            raise ValueError("速度因子必须 > 0")
        return z0, complex(rl, xl), self._f_hz(), vf, d

    def _f_hz(self) -> float:
        from ..units import FREQ_UNITS
        return float(self.var_f.get()) * FREQ_UNITS.get(self.var_funit.get(), 1e6)

    def set_freq_hz(self, hz: float) -> None:
        from ..units import freq_to_disp
        self.var_f.set(f"{freq_to_disp(hz, self.var_funit.get()):g}")

    def _on_funit(self, _ev=None) -> None:
        """切换本工具频率单位：把输入框换算过去，并同步全局显示单位。"""
        from ..units import FREQ_UNITS
        new = self.var_funit.get()
        old = self._funit_last
        if new == old:
            return
        try:
            hz = float(self.var_f.get()) * FREQ_UNITS.get(old, 1e6)
            self.var_f.set(f"{hz / FREQ_UNITS[new]:g}")
        except ValueError:
            pass
        self._funit_last = new
        self.set_funit(new)

    def set_funit(self, unit: str) -> None:
        """只改显示单位（不动输入框数值），用于跟随主界面。"""
        global _FREQ_UNIT
        from ..units import FREQ_UNITS
        if unit not in FREQ_UNITS:
            return
        _FREQ_UNIT = unit
        try:
            self.canvas.redraw()
        except Exception:
            pass

    @property
    def freq_hz(self) -> float:
        return self._f_hz()

    def compute(self, quiet: bool = False) -> None:
        try:
            z0, zl, f_hz, vf, d = self.read_inputs()
        except ValueError as e:
            if not quiet:
                messagebox.showwarning("参数有误", str(e), parent=self)
            return
        self.model = R.Line(z0, zl, d)
        self.canvas.z0, self.canvas.zl, self.canvas.d = z0, zl, d
        self.canvas.manual = None
        self._update_readouts(f_hz, vf)
        self.canvas.redraw()
        if self.app is not None and not quiet:
            self.app.say(f"圆图：ZL={S.fmt_complex(zl, 2)} Ω，d={d:g}λ，"
                         f"VSWR={_fmt_vswr(self.model.vswr)}")
            try:
                self.app._smith_sync_point(f_hz, f"ZL={S.fmt_complex(zl, 2)} Ω")
            except Exception:
                pass

    def refresh_readouts(self) -> None:
        try:
            _z0, _zl, f_hz, vf, _d = self.read_inputs()
        except ValueError:
            return
        self._update_readouts(f_hz, vf)

    def _update_readouts(self, f_hz: float, vf: float) -> None:
        m = self.model
        gl = m.gamma_load
        gin = self.canvas.gamma_in
        zin = R.z_of_gamma(gin, m.z0)
        yin = R.y_of_gamma(gin, m.z0)
        if self.var_norm.get():
            zin = zin / m.z0
            yin = yin * m.z0
        lam = R.wavelength_m(f_hz, vf)
        plen = R.physical_length_m(m.d_lambda, f_hz, vf)
        ang = math.atan2(gl.imag, gl.real)
        self.vars["gl"].set(S.fmt_complex(gl, 4))
        self.vars["gin"].set(S.fmt_complex(gin, 4))
        self.vars["zin"].set(S.fmt_complex(zin, 3))
        self.vars["yin"].set(S.fmt_complex(yin, 6))
        self.vars["vswr"].set(_fmt_vswr(m.vswr))
        self.vars["mag"].set(f"{abs(gl):.4f}")
        self.vars["phase"].set(f"{math.degrees(ang):.2f}°")
        self.vars["rl"].set(f"{m.return_loss:.2f}")
        self.vars["ml"].set(f"{m.mismatch_loss:.3f}")
        self.vars["pr"].set(f"{m.reflected_power:.2f}")
        self.vars["lam"].set(f"{lam * 1e3:.4f} mm" if math.isfinite(lam) else "—")
        self.vars["plen"].set(f"{plen * 1e3:.4f} mm" if math.isfinite(plen) else "—")
        self.vars["wtg"].set(f"{S.wtg_at(ang):.4f} λ")
        self.vars["wtl"].set(f"{S.wtl_at(ang):.4f} λ")

    # ---------------------------------------------------------------- 交互
    def _on_hover(self, text: str) -> None:
        self.var_hover.set(text)

    def _on_point(self, g: complex) -> None:
        try:
            z0, _zl, f_hz, vf, _d = self.read_inputs()
        except ValueError:
            return
        zl = R.z_of_gamma(g, z0)
        self.var_rl.set(f"{zl.real:.6g}")
        self.var_xl.set(f"{zl.imag:.6g}")
        self.var_d.set("0")
        self.canvas.manual = None
        self.model = R.Line(z0, zl, 0.0)
        self.canvas.z0, self.canvas.zl, self.canvas.d = z0, zl, 0.0
        self._update_readouts(f_hz, vf)
        self.canvas.redraw()
        if self.var_live.get():
            self._schedule_live(zl, z0, f_hz, vf)

    def _schedule_live(self, zl, z0, f_hz, vf) -> None:
        if self._live_after is not None:
            try:
                self.after_cancel(self._live_after)
            except Exception:
                pass
        self._live_after = self.after(
            180, lambda: self._live_now(zl, z0, f_hz, vf))

    def _live_now(self, zl, z0, f_hz, vf) -> None:
        self._live_after = None
        if self.app is None or not hasattr(self.app, "_smith_live_apply"):
            return
        try:
            self.app._smith_live_apply(zl, z0, f_hz, vf, 0.0)
        except Exception as e:  # noqa: BLE001
            self.var_hover.set(f"实时联动失败：{e}")

    def sync_live(self) -> None:
        try:
            z0, zl, f_hz, vf, d = self.read_inputs()
        except ValueError as e:
            messagebox.showwarning("参数有误", str(e), parent=self)
            return
        self._live_now(zl, z0, f_hz, vf)

    def _apply_opts(self) -> None:
        for k, var in self.opt_vars.items():
            self.canvas.opts[k] = bool(var.get())
        self.canvas.redraw()

    def canvas_fit(self) -> None:
        self.canvas.reset_view()

    # ---------------------------------------------------------------- 仿真
    def apply_theme(self) -> None:
        _sync_palette()
        self.canvas.configure(background=PAL["canvas"])
        self.canvas.redraw()

    def set_result(self, res: Optional[SweepResult]) -> None:
        self.result = res
        self.canvas.overlay = res
        self.canvas.play_idx = -1
        self.canvas.redraw()

    def set_play_cursor(self, idx: int) -> None:
        self.canvas.play_idx = idx
        self.canvas.redraw()

    def take_s11(self) -> None:
        if not self.result or not self.result.freqs:
            messagebox.showinfo("提示", "还没有仿真结果，请先运行仿真（F5）。", parent=self)
            return
        try:
            z0, _zl, f_hz, _vf, _d = self.read_inputs()
        except ValueError as e:
            messagebox.showwarning("参数有误", str(e), parent=self)
            return
        freqs = self.result.freqs
        k = min(range(len(freqs)), key=lambda i: abs(freqs[i] - f_hz))
        g = self.result.s_ij(1, 1)[k]
        if abs(1 - g) < 1e-15:
            messagebox.showwarning("提示", "该频点 Γ=1（全反射），输入阻抗无定义。", parent=self)
            return
        zin = R.z_of_gamma(g, z0)
        self.var_rl.set(f"{zin.real:.6g}")
        self.var_xl.set(f"{zin.imag:.6g}")
        self.var_d.set("0")
        self.compute()
        if self.app is not None:
            self.app.say(f"圆图：取自仿真 {freqs[k]/1e9:.4f} GHz 的输入阻抗 "
                         f"{S.fmt_complex(zin, 3)} Ω")

    # ---------------------------------------------------------------- 匹配
    def open_match(self) -> None:
        try:
            z0, zl, f_hz, _vf, _d = self.read_inputs()
        except ValueError as e:
            messagebox.showwarning("参数有误", str(e), parent=self)
            return
        LMatchDialog(self, self, zl, z0, f_hz)

    def apply_last(self) -> None:
        if self.last_solution is None:
            messagebox.showinfo("提示", "还没有匹配解，请先点「L 型匹配…」。", parent=self)
            return
        self.apply_solution(self.last_solution)

    def apply_solution(self, sol) -> bool:
        self.last_solution = sol
        if self.app is None or not hasattr(self.app, "_smith_apply_solution"):
            messagebox.showinfo("提示", "当前环境无法修改电路。", parent=self)
            return False
        try:
            self.app._smith_apply_solution(sol)
            return True
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("应用失败", str(e), parent=self)
            return False

    # ---------------------------------------------------------------- 导出
    def export_svg(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self, title="导出圆图", defaultextension=".svg",
            initialfile="smith_chart.svg",
            filetypes=[("SVG 矢量图", "*.svg"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            svg = self._svg()
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(svg)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("导出失败", str(e), parent=self)
            return
        if self.app is not None:
            self.app.say(f"已导出圆图：{path}")

    def _svg(self) -> str:
        size, rad, cx, cy = 600.0, 240.0, 300.0, 300.0
        out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size:g}" '
               f'height="{size:g}" viewBox="0 0 {size:g} {size:g}">',
               '<rect width="100%" height="100%" fill="#ffffff"/>']

        def px(g: complex):
            return cx + g.real * rad, cy - g.imag * rad

        def circle(c, color: str, width: float = 1.0):
            if not math.isfinite(c.r) or c.r > 50:
                return
            x, y = px(complex(c.cx, c.cy))
            out.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{c.r*rad:.2f}" '
                       f'fill="none" stroke="{color}" stroke-width="{width:g}"/>')

        out.append(f'<circle cx="{cx:g}" cy="{cy:g}" r="{rad:g}" fill="none" '
                   f'stroke="#374151" stroke-width="2"/>')
        for r in (0.0, 0.5, 1.0, 2.0, 5.0):
            circle(R.r_circle(r), "#e5e7eb")
        for x in (-5.0, -2.0, -1.0, -0.5, 0.5, 1.0, 2.0, 5.0):
            circle(R.x_circle(x), "#f3f4f6")
        circle(R.vswr_circle(self.canvas.gamma_load), "#f59e0b")
        if self.canvas.overlay:
            pts = []
            for k in range(len(self.canvas.overlay.freqs)):
                g = self.canvas.overlay.s[k][0][0]
                pts.append("%.2f,%.2f" % px(g))
            out.append(f'<polyline points="{" ".join(pts)}" fill="none" '
                       f'stroke="#2563eb" stroke-width="2"/>')
        for g, color in ((self.canvas.gamma_load, "#059669"),
                         (self.canvas.gamma_in, "#dc2626")):
            x, y = px(g)
            out.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="5" fill="{color}"/>')
        out.append("</svg>")
        return "\n".join(out)

    # ---------------------------------------------------------------- 持久化
    def to_dict(self) -> dict:
        try:
            z0, zl, _f, vf, d = self.read_inputs()
        except ValueError:
            return {}
        return {"z0": z0, "rl": zl.real, "xl": zl.imag,
                "f_mhz": self._f_hz() / 1e6, "vf": vf, "d": d,
                "live": bool(self.var_live.get())}

    def load_dict(self, d: dict) -> None:
        if not d:
            return
        try:
            self.var_z0.set(str(d.get("z0", self.var_z0.get())))
            self.var_rl.set(str(d.get("rl", self.var_rl.get())))
            self.var_xl.set(str(d.get("xl", self.var_xl.get())))
            if "f_mhz" in d:
                self.set_freq_hz(float(d["f_mhz"]) * 1e6)
            self.var_vf.set(str(d.get("vf", self.var_vf.get())))
            self.var_d.set(str(d.get("d", self.var_d.get())))
            self.var_live.set(bool(d.get("live", True)))
        except Exception:
            return
        self.compute(quiet=True)