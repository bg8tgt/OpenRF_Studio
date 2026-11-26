"""主窗口：OpenRF Studio 射频工作台。

左侧：电路元件表 + 端口 + 分析设置；右侧：幅度响应 / Smith 圆图 / 数据表 / 日志。
"""
from __future__ import annotations

import os
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Optional

from ..components import Component, is_ground
from ..engine import Analysis, Network, Port, SweepResult
from ..project import Project, new_demo_project
from ..touchstone import read_touchstone, write_touchstone
from . import dialogs
from ..catalog import KIND_NAME, code_for_kind
from ..units import FREQ_UNITS, freq_to_hz, freq_to_disp, fmt_freq_smart


def ghz_to_disp(ghz: float, unit: str) -> float:
    return ghz * 1e9 / FREQ_UNITS.get(unit, 1e9)


from .plots import MagnitudePlot
from .rf_workbench import RFWorkbench
from . import theme
from .schematic import SchematicView
from .match_dialog import MatchDialog
from .optimize_dialog import OptimizeDialog
from .line_dialog import LineImpedanceDialog
from .ai_panel import AIPanel
from ..rfmath import fmt_db, fmt_num, fmt_vswr

APP_NAME = "OpenRF Studio 射频工作台"
VERSION = "3.0.9"


def asset_path(name: str) -> str:
    """资源路径：源码运行取项目 assets/，PyInstaller 运行时取 _MEIPASS/assets/。"""
    base = getattr(__import__("sys"), "_MEIPASS", None)
    if not base:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "assets", name)


def enable_dpi():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME}  v{VERSION}")
        self.geometry("1440x900")
        self.minsize(1200, 720)
        self._set_icon()
        self.project = new_demo_project()
        self.result: Optional[SweepResult] = None
        self.ref_result: Optional[SweepResult] = None
        self.ref_name = ""
        self.dirty = False
        self.playing = False
        self.play_after = None
        self.play_idx = 0
        self._want_play = False
        self.var_anim = tk.BooleanVar(value=True)
        self.var_speed = tk.StringVar(value="5")

        self._theme_name = "light"
        self._theme_choice = tk.StringVar(value="light")
        self._init_style()
        self._build_menu()
        self._build_toolbar()
        self._build_status()      # 先占住底部，避免被主体挤掉
        self._build_body()

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<F5>", lambda e: self.run_sim())
        self.bind("<F1>", lambda e: dialogs.HelpDialog(self))
        self.bind("<Control-s>", lambda e: self.save_project())
        self.bind("<Control-o>", lambda e: self.open_project())
        self.after(120, self.refresh_all)
        self.after(400, self.run_sim)

    # ---------------------------------------------------------------- 兜底
    def report_callback_exception(self, exc, val, tb):
        """任何回调里的未捕获异常都要看得见。

        打包成窗口程序后 sys.stderr 是 None，tkinter 默认的打印实现会再抛
        AttributeError，把事件循环带崩——表现就是"点了没反应、卡死"。
        """
        import traceback
        text = "".join(traceback.format_exception(exc, val, tb))
        try:
            log_dir = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                                   "OpenRF_Studio")
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, "error.log"), "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception:
            pass
        try:
            if sys.stderr is not None:
                sys.stderr.write(text)
        except Exception:
            pass
        try:
            messagebox.showerror(
                "操作失败",
                "%s: %s\n\n详情已记录到 %APPDATA%\\OpenRF_Studio\\error.log"
                % (exc.__name__, val), parent=self)
        except Exception:
            pass

    # ---------------------------------------------------------------- 外观
    def _set_icon(self):
        """窗口/任务栏图标（assets/openrf.ico，打包后同样生效）。"""
        try:
            ico = asset_path("openrf.ico")
            if os.path.exists(ico):
                try:
                    self.iconbitmap(ico)
                except Exception:
                    pass
            png = asset_path("openrf_256.png")
            if os.path.exists(png):
                self._icon_img = tk.PhotoImage(file=png)
                self.iconphoto(True, self._icon_img)
        except Exception:
            pass

    def _init_style(self):
        self.option_add("*Font", ("Microsoft YaHei UI", 10))
        theme.apply(self, self._theme_name)

    def _build_menu(self):
        m = tk.Menu(self)
        fm = tk.Menu(m, tearoff=0)
        fm.add_command(label="新建工程", accelerator="Ctrl+N", command=self.new_project)
        fm.add_command(label="打开工程…", accelerator="Ctrl+O", command=self.open_project)
        fm.add_separator()
        fm.add_command(label="保存", accelerator="Ctrl+S", command=self.save_project)
        fm.add_command(label="另存为…", command=lambda: self.save_project(ask=True))
        fm.add_separator()
        fm.add_command(label="导入 Touchstone…", command=self.import_touchstone)
        fm.add_command(label="导出 Touchstone…", command=self.export_touchstone)
        fm.add_command(label="导出数据 CSV…", command=self.export_csv)
        fm.add_separator()
        fm.add_command(label="退出", command=self.on_close)
        m.add_cascade(label="文件", menu=fm)

        dm = tk.Menu(m, tearoff=0)
        dm.add_command(label="低通/带通滤波器向导…", command=self.filter_wizard)
        dm.add_command(label="传输线计算器…", command=lambda: dialogs.TransmissionLineDialog(self))
        dm.add_command(label="反向计算…", command=lambda: dialogs.InverseDialog(self))
        dm.add_command(label="匹配计算器…", command=lambda: MatchDialog(self, self))
        dm.add_command(label="优化器…", command=lambda: OptimizeDialog(self, self))
        dm.add_command(label="线阻抗计算…", command=lambda: LineImpedanceDialog(self))
        dm.add_command(label="导入 S2P 元件…", command=self.import_s2p)
        dm.add_command(label="Smith 工具（读数与匹配）…", command=self.show_smith_tool)
        dm.add_separator()
        dm.add_command(label="添加元件…", command=lambda: self.edit_component(None))
        m.add_cascade(label="设计", menu=dm)

        am = tk.Menu(m, tearoff=0)
        am.add_command(label="运行仿真", accelerator="F5", command=self.run_sim)
        am.add_separator()
        am.add_command(label="分析设置", command=lambda: self.nb.select(0))
        m.add_cascade(label="分析", menu=am)

        hm = tk.Menu(m, tearoff=0)
        hm.add_command(label="使用说明", accelerator="F1", command=lambda: dialogs.HelpDialog(self))
        hm.add_command(label="AI 设置（自定义模型）…",
                       command=lambda: self.ai_panel.open_settings())
        hm.add_separator()
        hm.add_command(label="关于", command=lambda: dialogs.AboutDialog(self, VERSION))
        vm = tk.Menu(m, tearoff=0)
        vm.add_radiobutton(label="浅色模式", value="light",
                           variable=self._theme_choice,
                           command=lambda: self._apply_theme("light"))
        vm.add_radiobutton(label="深色模式", value="dark",
                           variable=self._theme_choice,
                           command=lambda: self._apply_theme("dark"))
        m.add_cascade(label="视图", menu=vm)

        m.add_cascade(label="帮助", menu=hm)
        self.config(menu=m)

    def _build_toolbar(self):
        head = ttk.Frame(self, style="Header.TFrame", padding=(14, 8))
        head.pack(side="top", fill="x")
        ttk.Label(head, text=APP_NAME, style="Header.TLabel").pack(side="left")
        ttk.Label(head, text=f"v{VERSION}", style="Header.TLabel").pack(side="left", padx=10)
        self.var_theme = tk.StringVar(value="浅色")
        ttk.Button(head, text="切换浅色/深色", command=self._toggle_theme).pack(side="right")
        ttk.Label(head, textvariable=self.var_theme, style="Header.TLabel").pack(
            side="right", padx=8)
        bar = ttk.Frame(self, padding=(8, 6))
        bar.pack(side="top", fill="x")
        ttk.Button(bar, text="▶ 运行仿真", style="Accent.TButton",
                   command=self.run_sim).pack(side="left")
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(bar, text="＋ 添加", width=8,
                   command=lambda: self.edit_component(None)).pack(side="left", padx=2)
        ttk.Button(bar, text="✎ 编辑", width=8,
                   command=self.edit_selected).pack(side="left", padx=2)
        ttk.Button(bar, text="✕ 删除", width=8,
                   command=self.delete_selected).pack(side="left", padx=2)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(bar, text="向导", width=8,
                   command=self.filter_wizard).pack(side="left", padx=2)
        ttk.Button(bar, text="传输线", width=8,
                   command=lambda: dialogs.TransmissionLineDialog(self)).pack(side="left", padx=2)
        ttk.Button(bar, text="反算", width=8,
                   command=lambda: dialogs.InverseDialog(self)).pack(side="left", padx=2)
        ttk.Button(bar, text="Smith", width=8,
                   command=self.show_smith_tool).pack(side="left", padx=2)
        ttk.Button(bar, text="匹配", width=8,
                   command=lambda: MatchDialog(self, self)).pack(side="left", padx=2)
        ttk.Button(bar, text="优化", width=8,
                   command=lambda: OptimizeDialog(self, self)).pack(side="left", padx=2)
        ttk.Button(bar, text="AI", width=8,
                   command=lambda: self.nb.select(self.nb.index(self.ai_panel))).pack(side="left", padx=2)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        # 测量选择放在工具条下方独立一行，避免窄窗口被挤出
        row2 = ttk.Frame(self, padding=(10, 0, 10, 4))
        row2.pack(side="top", fill="x")
        ttk.Label(row2, text="图表测量").pack(side="left")
        self.var_measure = tk.StringVar(value="幅度 dB")
        cb = ttk.Combobox(row2, textvariable=self.var_measure, state="readonly", width=12,
                          values=["幅度 dB", "驻波比 VSWR", "群时延 ns"])
        cb.pack(side="left", padx=(6, 0))
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_measure())
        ttk.Label(row2, text="（直角坐标图显示的量）",
                  foreground="#6b7280", font=("Microsoft YaHei UI", 8)).pack(side="left", padx=8)
        ttk.Button(row2, text="导出", command=self.export_touchstone).pack(side="right", padx=2)
        ttk.Button(row2, text="保存", command=self.save_project).pack(side="right", padx=2)
        ttk.Button(row2, text="打开", command=self.open_project).pack(side="right", padx=2)
        ttk.Button(row2, text="■ 停止", command=self.stop_play).pack(side="right", padx=2)
        ttk.Button(row2, text="▶ 播放", command=self.toggle_play).pack(side="right", padx=2)
        ttk.Combobox(row2, textvariable=self.var_speed, width=4, state="readonly",
                     values=["1", "5", "10", "20", "50"]).pack(side="right")
        ttk.Label(row2, text="速度").pack(side="right")
        ttk.Checkbutton(row2, text="运行后自动播放",
                        variable=self.var_anim).pack(side="right", padx=6)

    # ---------------------------------------------------------------- 主体
    def _build_body(self):
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        left = ttk.Frame(paned, width=560)
        paned.add(left, weight=0)
        right = ttk.Frame(paned)
        paned.add(right, weight=1)

        # 元件表
        box = ttk.LabelFrame(left, text="电路元件", padding=6)
        box.pack(fill="both", expand=True)
        cols = ("cid", "kind", "param", "nodes")
        self.tree = ttk.Treeview(box, columns=cols, show="headings", height=12)
        heads = {"cid": ("编号", 70), "kind": ("类型", 60),
                 "param": ("参数", 230), "nodes": ("节点", 110)}
        for c in cols:
            t, w = heads[c]
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        vs = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.edit_selected())
        self.tree.bind("<Delete>", lambda e: self.delete_selected())

        # 端口 + 分析设置
        bottom = ttk.Frame(left)
        bottom.pack(fill="x", pady=(6, 0))

        pbox = ttk.LabelFrame(bottom, text="端口（按顺序编号）", padding=6)
        pbox.pack(side="top", fill="x")
        self.port_list = tk.Listbox(pbox, height=3, font=("Consolas", 9),
                                    exportselection=False)
        self.port_list.pack(fill="both", expand=True)
        pbar = ttk.Frame(pbox)
        pbar.pack(fill="x", pady=(4, 0))
        ttk.Button(pbar, text="添加端口", width=9, command=self.add_port).pack(side="left")
        ttk.Button(pbar, text="删除", width=6, command=self.del_port).pack(side="left", padx=3)

        abox = ttk.LabelFrame(bottom, text="分析设置（频率 / 单位 / 步进 / 单点）", padding=6)
        abox.pack(side="top", fill="x", pady=(6, 0))
        _u = self.project.freq_unit
        self.var_start = tk.StringVar(value=f"{ghz_to_disp(self.project.analysis.start_ghz, _u):g}")
        self.var_stop = tk.StringVar(value=f"{ghz_to_disp(self.project.analysis.stop_ghz, _u):g}")
        self.var_pts = tk.StringVar(value=str(self.project.analysis.points))
        self.var_step = tk.StringVar(value="0")
        self.var_z0 = tk.StringVar(value=f"{self.project.network.z0:g}")
        self.var_sweep = tk.StringVar(value=self.project.analysis.sweep)
        self.var_single = tk.BooleanVar(value=False)
        self.var_funit = tk.StringVar(value=self.project.freq_unit)

        def lab(text):
            return ttk.Label(abox, text=text, font=("Microsoft YaHei UI", 9))

        lab("起始").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Entry(abox, textvariable=self.var_start, width=9).grid(row=0, column=1, sticky="w")
        lab("终止").grid(row=0, column=2, sticky="w", padx=(8, 0))
        ttk.Entry(abox, textvariable=self.var_stop, width=9).grid(row=0, column=3, sticky="w")

        lab("单位").grid(row=1, column=0, sticky="w", pady=2)
        cb_u = ttk.Combobox(abox, textvariable=self.var_funit, values=list(FREQ_UNITS),
                            state="readonly", width=7)
        cb_u.grid(row=1, column=1, sticky="w")
        cb_u.bind("<<ComboboxSelected>>", self._on_freq_unit)
        lab("扫频").grid(row=1, column=2, sticky="w", padx=(8, 0))
        ttk.Combobox(abox, textvariable=self.var_sweep, values=["linear", "log"],
                     state="readonly", width=7).grid(row=1, column=3, sticky="w")

        lab("点数").grid(row=2, column=0, sticky="w", pady=2)
        ttk.Entry(abox, textvariable=self.var_pts, width=9).grid(row=2, column=1, sticky="w")
        lab("步进(0=不用)").grid(row=2, column=2, sticky="w", padx=(8, 0))
        ttk.Entry(abox, textvariable=self.var_step, width=9).grid(row=2, column=3, sticky="w")

        lab("Z0 (Ω)").grid(row=3, column=0, sticky="w", pady=2)
        ttk.Entry(abox, textvariable=self.var_z0, width=9).grid(row=3, column=1, sticky="w")
        ttk.Checkbutton(abox, text="单点", variable=self.var_single).grid(
            row=3, column=2, columnspan=2, sticky="w", padx=(8, 0))

        # 右侧 notebook
        self.nb = ttk.Notebook(right)
        self.nb.pack(fill="both", expand=True)

        # 直角坐标图 与 史密斯圆图 同居一页、左右分栏：
        # 仍是两块各自独立的画布（各有自己的坐标系/鼠标绑定），不合并、不叠加；
        # 两边只共享「频点实时同步」。
        self.dual = ttk.Frame(self.nb)
        self.dual_pane = ttk.PanedWindow(self.dual, orient="horizontal")
        self.dual_pane.pack(fill="both", expand=True)

        self.mag = MagnitudePlot(self.dual_pane)
        self.mag.on_readout = lambda text: self.status.set("定位：" + text)
        self.mag.on_freq_pick = self._mag_freq_pick
        self.smith = None  # 见下方：Smith 圆图 = 右半的 RFWorkbench
        self.dual_pane.add(self.mag, weight=1)

        self.smith_tool = RFWorkbench(self.dual_pane, self)
        self.smith = self.smith_tool   # 兼容旧引用：Smith 圆图即右半工具面板
        self.dual_pane.add(self.smith_tool, weight=1)

        self.nb.add(self.dual, text="  圆图 / 直角图  ")
        self.rl_plot = MagnitudePlot(self.nb)
        self.rl_plot.set_mode("rl")
        self.nb.add(self.rl_plot, text="  回损曲线  ")
        gainf = ttk.Frame(self.nb, padding=4)
        cols = ("f", "s11", "s21", "vswr", "gd")
        self.gain_tree = ttk.Treeview(gainf, columns=cols, show="headings", height=10)
        for col, title, w in (("f", f"频率 ({self.project.freq_unit})", 110),
                              ("s11", "|S11| (dB)", 100),
                              ("s21", "|S21| (dB)", 100), ("vswr", "VSWR", 80),
                              ("gd", "群时延 (ns)", 110)):
            self.gain_tree.heading(col, text=title)
            self.gain_tree.column(col, width=w, anchor="center")
        vsb = ttk.Scrollbar(gainf, orient="vertical", command=self.gain_tree.yview)
        self.gain_tree.configure(yscrollcommand=vsb.set)
        self.gain_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.nb.add(gainf, text="  增益表  ")
        self.sch = SchematicView(self.nb)
        self.nb.add(self.sch, text="  原理图  ")

        tab = ttk.Frame(self.nb)
        self.table = ttk.Treeview(tab, show="headings", height=18)
        vs2 = ttk.Scrollbar(tab, orient="vertical", command=self.table.yview)
        hs2 = ttk.Scrollbar(tab, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=vs2.set, xscrollcommand=hs2.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        vs2.grid(row=0, column=1, sticky="ns")
        hs2.grid(row=1, column=0, sticky="ew")
        tab.rowconfigure(0, weight=1)
        tab.columnconfigure(0, weight=1)
        self.nb.add(tab, text="  数据表  ")

        logf = ttk.Frame(self.nb)
        self.log = tk.Text(logf, font=("Consolas", 9), wrap="word", state="disabled")
        lv = ttk.Scrollbar(logf, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=lv.set)
        self.log.pack(side="left", fill="both", expand=True)
        lv.pack(side="right", fill="y")
        self.nb.add(logf, text="  日志  ")
        self.ai_panel = AIPanel(self.nb, self)
        self.nb.add(self.ai_panel, text="  AI 助手  ")

    def _build_status(self):
        bar = ttk.Frame(self, padding=(10, 4))
        bar.pack(side="bottom", fill="x")
        self.status = tk.StringVar(value="就绪")
        ttk.Label(bar, textvariable=self.status, font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.file_label = tk.StringVar(value="（未保存）")
        ttk.Label(bar, textvariable=self.file_label, foreground="#6b7280",
                  font=("Microsoft YaHei UI", 9)).pack(side="right")

    # ---------------------------------------------------------------- 工具
    def say(self, msg: str):
        self.log.configure(state="normal")
        self.log.insert("end", time.strftime("[%H:%M:%S] ") + msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        self.status.set(msg)

    def _collect_analysis(self) -> Analysis:
        u = self.var_funit.get()
        start_ghz = freq_to_hz(float(self.var_start.get()), u) / 1e9
        stop_ghz = freq_to_hz(float(self.var_stop.get()), u) / 1e9
        try:
            step_ghz = float(self.var_step.get() or 0)
        except ValueError:
            step_ghz = 0.0
        return Analysis(start_ghz, stop_ghz, int(float(self.var_pts.get())),
                        self.var_sweep.get(), step_ghz, bool(self.var_single.get()))

    def _on_freq_unit(self, _ev=None):
        """切换频率单位时，把输入框数值换算过去。"""
        new_unit = self.var_funit.get()
        old_unit = getattr(self, "_freq_unit_last", "GHz")
        if new_unit == old_unit:
            return
        k = FREQ_UNITS[old_unit] / FREQ_UNITS[new_unit]
        for var in (self.var_start, self.var_stop):
            try:
                var.set(f"{float(var.get()) * k:g}")
            except ValueError:
                pass
        self._freq_unit_last = new_unit
        self.project.freq_unit = new_unit
        self._apply_freq_unit(new_unit)

    def _apply_freq_unit(self, unit: str):
        """把当前频率单位同步到所有显示频率的地方。"""
        self.project.freq_unit = unit
        for plot in (getattr(self, "mag", None), getattr(self, "rl_plot", None)):
            if plot is not None:
                try:
                    plot.set_funit(unit)
                except Exception:
                    pass
        try:
            self.gain_tree.heading("f", text=f"频率 ({unit})")
        except Exception:
            pass
        if self.result is not None:
            for fn in (getattr(self, "_fill_gain", None),
                       getattr(self, "_fill_table", None)):
                try:
                    if fn:
                        fn(self.result)
                except Exception:
                    pass
        try:
            self.smith_tool.set_funit(unit)
        except Exception:
            pass

    def _on_measure(self):
        mode = {"幅度 dB": "dB", "驻波比 VSWR": "vswr", "群时延 ns": "gd"}.get(
            self.var_measure.get(), "dB")
        self.mag.set_mode(mode)
        self.say(f"图表测量切换为：{self.var_measure.get()}")

    def refresh_all(self):
        self.project.analysis = self._collect_analysis()
        self.project.network.z0 = float(self.var_z0.get())
        self._refresh_tree()
        self._refresh_ports()

    def _refresh_schematic(self):
        try:
            self.sch.set_network(self.project.network)
        except Exception:
            pass

    def _refresh_tree(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._refresh_schematic()
        for c in self.project.network.components:
            code = code_for_kind(c.kind)
            self.tree.insert("", "end", iid=c.cid,
                             values=(c.cid, f"{code} {KIND_NAME.get(c.kind, c.kind)}", c.param_text(),
                                     "-".join(c.nodes)))

    def _refresh_ports(self):
        self.port_list.delete(0, "end")
        for p in self.project.network.ports:
            self.port_list.insert("end", f"{p.pid} → {p.node}")

    def _selected_cid(self) -> Optional[str]:
        sel = self.tree.selection()
        return sel[0] if sel else None

    # ---------------------------------------------------------------- 编辑
    def edit_component(self, comp: Optional[Component]):
        nodes = list(dict.fromkeys(
            [n for c in self.project.network.components for n in c.nodes if not is_ground(n)]
            + [p.node for p in self.project.network.ports] + ["n1", "n2"]))
        dlg = dialogs.ComponentDialog(self, comp, "R", nodes)
        self.wait_window(dlg)
        if not dlg.result:
            return
        new = dlg.result
        if comp:
            idx = next((i for i, c in enumerate(self.project.network.components)
                        if c.cid == comp.cid), None)
            if any(c.cid == new.cid and c is not comp for c in self.project.network.components):
                dialogs.show_error(self, "编号重复", f"编号 {new.cid} 已存在",
                         "换一个编号，或先删除同名元件")
                return
            if idx is not None:
                self.project.network.components[idx] = new
        else:
            if self.project.network.get(new.cid):
                dialogs.show_error(self, "编号重复", f"编号 {new.cid} 已存在",
                         "换一个编号，或先删除同名元件")
                return
            self.project.network.components.append(new)
        self.dirty = True
        self._refresh_tree()
        self.say(f"已保存元件 {new.describe()}")

    def edit_selected(self):
        cid = self._selected_cid()
        if not cid:
            messagebox.showinfo("提示", "请先在元件表里选中一行", parent=self)
            return
        c = self.project.network.get(cid)
        if c:
            self.edit_component(c)

    def delete_selected(self):
        cid = self._selected_cid()
        if not cid:
            return
        if messagebox.askyesno("确认", f"删除元件 {cid}？", parent=self):
            self.project.network.remove(cid)
            self.dirty = True
            self._refresh_tree()
            self.say(f"已删除 {cid}")

    def add_port(self):
        node = simpledialog.askstring("添加端口", "端口接在哪个节点？（如 n2）",
                                      parent=self)
        if not node:
            return
        node = node.strip()
        n = len(self.project.network.ports) + 1
        self.project.network.ports.append(Port(f"P{n}", node))
        self.dirty = True
        self._refresh_ports()
        self.say(f"已添加端口 P{n} → {node}")

    def del_port(self):
        sel = self.port_list.curselection()
        if not sel:
            return
        i = sel[0]
        pid = self.project.network.ports[i].pid
        del self.project.network.ports[i]
        for k, p in enumerate(self.project.network.ports, 1):
            p.pid = f"P{k}"
        self.dirty = True
        self._refresh_ports()
        self.say(f"已删除端口 {pid}")

    # ---------------------------------------------------------------- 仿真
    def run_sim(self):
        try:
            self.project.analysis = self._collect_analysis()
            self.project.network.z0 = float(self.var_z0.get())
            if not self.project.network.ports:
                messagebox.showwarning("提示", "请先添加端口", parent=self)
                return
            t0 = time.time()
            res = self.project.network.sweep(self.project.analysis)
            dt = (time.time() - t0) * 1000
            self.result = res
            self._refresh_schematic()
            self.mag.set_data(res, self.ref_result)
            self.rl_plot.set_data(res, self.ref_result)
            self._fill_gain(res)
            self.smith_tool.set_result(res)
            self._fill_table(res)
            self.say(f"仿真完成：{len(res.freqs)} 点 × {res.n_ports()} 端口，"
                     f"耗时 {dt:.0f} ms（{self.project.analysis.sweep} 扫频）")
            k = len(res.freqs) // 2
            if res.n_ports() >= 2:
                self.say(f"mid-band @ {fmt_freq_smart(res.freqs[k], self.project.freq_unit)}："
                         f"|S11|={res.db(1,1)[k]:.2f} dB，|S21|={res.db(2,1)[k]:.2f} dB")
        except Exception as e:  # noqa: BLE001
            dialogs.show_error(self, "仿真失败", e,
                            "检查元件节点是否连成通路、端口是否至少两个、Z0 是否大于 0")
            self.say(f"仿真失败：{e}")

    def import_s2p(self):
        """导入 2 端口 Touchstone 作为 S2P 元件。"""
        from tkinter import filedialog, messagebox, simpledialog
        from ..components import Component
        path = filedialog.askopenfilename(
            parent=self, title="选择 Touchstone 文件（2 端口）",
            filetypes=[("Touchstone", "*.s2p *.S2P"), ("所有文件", "*.*")])
        if not path:
            return
        n1 = simpledialog.askstring("S2P 元件", "节点 1（默认 n1）", initialvalue="n1", parent=self)
        n2 = simpledialog.askstring("S2P 元件", "节点 2（默认 n2）", initialvalue="n2", parent=self)
        if not n1 or not n2:
            return
        try:
            from ..touchstone import read_touchstone
            freqs, data, z0, nport = read_touchstone(path)
            if nport != 2:
                messagebox.showerror("不支持", f"该文件是 {nport} 端口；S2P 元件目前只支持 2 端口。", parent=self)
                return
            cid = self.project.network.next_id("S2P")
            self.project.network.components.append(
                Component(cid, "S2P", [n1, n2], {"path": path, "z0": z0}))
            self.project.analysis.start_ghz = max(freqs[0] / 1e9, 1e-6)
            self.project.analysis.stop_ghz = freqs[-1] / 1e9
            self.var_start.set(f"{self.project.analysis.start_ghz:g}")
            self.var_stop.set(f"{self.project.analysis.stop_ghz:g}")
            self._refresh_tree()
            self._refresh_ports()
            self.dirty = True
            self.say(f"已导入 S2P 元件 {cid}：{path}")
        except Exception as e:  # noqa: BLE001
            dialogs.show_error(self, "导入失败", e,
                            "确认是 Touchstone 文件（.s2p/.s3p），且格式头与频率单位正确")

    def ai_out_dir(self) -> str:
        """AI 自动保存/导出时的输出目录。"""
        import os
        base = os.path.dirname(os.path.abspath(self.project.path)) if self.project.path else os.getcwd()
        d = os.path.join(base, "ai_output")
        os.makedirs(d, exist_ok=True)
        return d

    def ai_finish_agent(self, res: dict):
        """自动执行结束后同步界面：结果曲线、表格、原理图、页签与工具。"""
        if res.get("result") is not None:
            self.result = res["result"]
            self._fill_table(self.result)
            k = len(self.result.freqs) // 2
            msg = (f"AI 执行后：mid-band @ {fmt_freq_smart(self.result.freqs[k], self.project.freq_unit)}；"
                   f"|S11|={self.result.db(1, 1)[k]:.2f} dB")
            if self.result.n_ports() >= 2:
                msg += f"，|S21|={self.result.db(2, 1)[k]:.2f} dB"
            self.status.set(msg)
            self.mag.set_data(self.result, self.ref_result)
            self.rl_plot.set_data(self.result, self.ref_result)
            self._fill_gain(self.result)
            self.smith_tool.set_result(self.result)
            self._refresh_schematic()
        self._refresh_tree()
        self._refresh_ports()
        tab = res.get("tab_hint")
        if tab:
            cn = {"plot": "直角坐标图", "smith": "史密斯圆图", "schematic": "原理图",
                  "table": "数据表", "log": "日志", "ai": "AI 助手",
                  "smith_tool": "Smith 工具"}.get(tab)
            # 直角坐标图 / 史密斯圆图 / Smith 工具 现在同属一页，统一落到该页
            if cn in ("直角坐标图", "史密斯圆图", "Smith 工具"):
                self.nb.select(self.nb.index(self.dual))
            else:
                for i in range(self.nb.index("end")):
                    if cn and self.nb.tab(i, "text").strip() == cn:
                        self.nb.select(i)
                        break
        tool = res.get("tool_hint")
        if tool == "filter_wizard":
            dialogs.FilterWizard(self)
        elif tool == "tline":
            dialogs.TransmissionLineDialog(self)
        elif tool == "inverse":
            dialogs.InverseDialog(self)
        elif tool == "smith_tool":
            self.show_smith_tool()
        elif tool == "about":
            dialogs.AboutDialog(self, VERSION)
        elif tool == "help":
            dialogs.HelpDialog(self)

    def ai_apply_actions(self, actions) -> list:
        """把 AI 建议应用到工程：校验后的动作 → 改电路 → 同步界面 → 需要时跑仿真。"""
        from ..ai.actions import apply_actions

        report = apply_actions(self.project, actions)
        a = self.project.analysis
        self.var_start.set(f"{a.start_ghz:g}")
        self.var_stop.set(f"{a.stop_ghz:g}")
        self.var_pts.set(str(a.points))
        self.var_sweep.set(a.sweep)
        self.var_z0.set(f"{self.project.network.z0:g}")
        self.var_single.set(bool(a.single))
        self.dirty = True
        self._refresh_tree()
        self._refresh_ports()
        self._refresh_schematic()
        if any(x.get("op") == "run" for x in actions):
            self.run_sim()
        return report

    def _fill_gain(self, res):
        try:
            self.gain_tree.delete(*self.gain_tree.get_children())
        except Exception:
            return
        if not res or not res.freqs:
            return
        n = res.n_ports()
        unit = self.project.freq_unit
        try:
            self.gain_tree.heading("f", text=f"频率 ({unit})")
        except Exception:
            pass
        for k, f in enumerate(res.freqs):
            s11 = res.db(1, 1)[k]
            s21 = res.db(2, 1)[k] if n >= 2 else float("nan")
            vswr = res.vswr(1)[k]
            gd = res.group_delay_ns(1, 1)[k]
            self.gain_tree.insert("", "end", values=(
                f"{freq_to_disp(f, unit):.6g}", fmt_db(s11, 3),
                fmt_db(s21, 3) if n >= 2 else "—",
                fmt_vswr(vswr, 4), fmt_num(gd, 4)))

    def export_csv(self):
        import csv
        if not self.result or not self.result.freqs:
            messagebox.showinfo("提示", "还没有仿真结果，先运行仿真。", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="导出数据 CSV", defaultextension=".csv",
            initialfile="sweep.csv", filetypes=[("CSV", "*.csv"), ("所有文件", "*.*")])
        if not path:
            return
        res = self.result
        n = res.n_ports()
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["freq_ghz", "s11_db", "s21_db", "vswr", "group_delay_ns"])
            def _csv(v):
                # 非有限值（∞ / 被 DB_FLOOR 钳出的极低值）写成空列，
                # 避免 Excel 把 "inf"/"-6000.0" 当有效数值参与绘图。
                import math as _m
                return f"{v:.6f}" if _m.isfinite(v) and v > -600.0 else ""
            for k, f in enumerate(res.freqs):
                w.writerow([f"{f/1e9:.9g}", _csv(res.db(1,1)[k]),
                            _csv(res.db(2,1)[k]) if n >= 2 else "",
                            _csv(res.vswr(1)[k]),
                            _csv(res.group_delay_ns(1,1)[k])])
        self.say(f"已导出 CSV：{path}")

    def _fill_table(self, res: SweepResult):
        pairs = [(i, j) for i in range(1, res.n_ports() + 1)
                 for j in range(1, res.n_ports() + 1)]
        cols = ["f"] + [f"{i}{j}" for i, j in pairs] + [f"ph{i}{j}" for i, j in pairs]
        self.table.configure(columns=cols)
        self.table.heading("f", text=f"频率 ({self.project.freq_unit})")
        self.table.column("f", width=110, anchor="e")
        for i, j in pairs:
            self.table.heading(f"{i}{j}", text=f"|S{i}{j}| dB")
            self.table.column(f"{i}{j}", width=90, anchor="e")
            self.table.heading(f"ph{i}{j}", text=f"∠S{i}{j} (°)")
            self.table.column(f"ph{i}{j}", width=90, anchor="e")
        for iid in self.table.get_children():
            self.table.delete(iid)
        for k, f in enumerate(res.freqs):
            row = [f"{freq_to_disp(f, self.project.freq_unit):.6g}"]
            for i, j in pairs:
                row.append(f"{res.db(i, j)[k]:.3f}")
            for i, j in pairs:
                v = res.s_ij(i, j)[k]
                import math
                row.append(f"{math.degrees(math.atan2(v.imag, v.real)):.1f}")
            self.table.insert("", "end", values=row)

    # ---------------------------------------------------------------- 向导
    def filter_wizard(self):
        dlg = dialogs.FilterWizard(self, float(self.var_z0.get()))
        self.wait_window(dlg)
        if not dlg.result:
            return
        self._apply_filter(dlg.result)

    def _apply_theme(self, name: str):
        """切换浅色/深色并刷新绘图。"""
        pal = theme.apply(self, name)
        self._theme_name = pal["name"]
        self._theme_choice.set(pal["name"])
        try:
            self.var_theme.set("深色" if pal["name"] == "dark" else "浅色")
        except Exception:
            pass
        for w in (getattr(self, "mag", None), getattr(self, "sch", None),
                  getattr(self, "rl_plot", None)):
            try:
                w.redraw()
            except Exception:
                pass
        try:
            self.smith_tool.apply_theme()
        except Exception:
            pass
        for w in (getattr(self, "mag", None), getattr(self, "sch", None),
                  getattr(self, "smith_tool", None)):
            try:
                w.configure(bg=pal["canvas"])
            except Exception:
                pass
        self.say(f"界面主题：{'深色' if pal['name'] == 'dark' else '浅色'}")

    def _toggle_theme(self):
        self._apply_theme("dark" if theme.current_name() == "light" else "light")

    def show_smith_tool(self):
        """切到 Smith 工具页签（菜单/工具条/AI 共用入口）。"""
        self.nb.select(self.nb.index(self.dual))
        self.say("史密斯圆图：拖动圆内点即改变负载并实时仿真，滚轮缩放，双击复位")
    def set_analysis_display(self, start_ghz: float, stop_ghz: float):
        u = self.var_funit.get()
        self.var_start.set(f"{ghz_to_disp(start_ghz, u):g}")
        self.var_stop.set(f"{ghz_to_disp(stop_ghz, u):g}")

    def _mag_freq_pick(self, f_ghz: float):
        """直角图选中频点 -> 圆图按该频点重算自身模型（频点级同步）。

        只同步频率：不调 run_sim、不改电路；圆图自己的 Line 模型按新频率
        重画并高亮。防回环靠 _syncing。
        """
        if getattr(self, "_syncing", False) or f_ghz <= 0:
            return
        tool = getattr(self, "smith_tool", None)
        if tool is None:
            return
        self._syncing = True
        try:
            tool.set_freq_hz(f_ghz * 1e9)   # 按圆图当前选择的单位换算
            tool.compute(quiet=True)
            self.status.set(f"圆图同步：f = {fmt_freq_smart(f_ghz * 1e9, self.project.freq_unit)}")
        except Exception:
            pass
        finally:
            self._syncing = False

    def _smith_sync_point(self, f_hz: float, text: str = ""):
        """Smith 工具数值变化时：保证频点在扫频内、仿真并把光标打到直角坐标图。"""
        if getattr(self, "_syncing", False):
            return
        if f_hz <= 0:
            return
        g = f_hz / 1e9
        ana = self.project.analysis
        if not (ana.start_ghz <= g <= ana.stop_ghz) or ana.single:
            ana.single = False
            ana.start_ghz = max(g * 0.7, 1e-10)
            ana.stop_ghz = g * 1.3
            self.set_analysis_display(ana.start_ghz, ana.stop_ghz)
        self.run_sim()
        try:
            self.mag.mark_at_freq(g)
        except Exception:
            pass
        if text:
            self.status.set("Smith 同步：" + text)

    def run_and_play(self):
        self._want_play = bool(self.var_anim.get())
        self.run_sim()
        if self._want_play:
            self.start_play()
        self._want_play = False

    def toggle_play(self):
        if self.playing:
            self.stop_play()
        else:
            self.start_play()

    def start_play(self):
        if not self.result or not self.result.freqs:
            return
        self.stop_play()
        self.playing = True
        self.play_idx = -1
        self._play_tick()

    def _play_tick(self):
        self.play_after = None
        if not self.playing or not self.result or not self.result.freqs:
            return
        n = len(self.result.freqs)
        try:
            step = max(1, int(float(self.var_speed.get() or 5)))
        except ValueError:
            step = 5
        self.play_idx = (self.play_idx + step) % n
        k = self.play_idx
        res = self.result
        f = res.freqs[k]
        text = f"f={fmt_freq_smart(f, self.project.freq_unit)}  |S11|={fmt_db(res.db(1,1)[k])} dB"
        if res.n_ports() >= 2:
            text += f"  |S21|={fmt_db(res.db(2,1)[k])} dB"
        text += f"  VSWR={fmt_vswr(res.vswr(1)[k], 3)}"
        try:
            self.mag.set_cursor(k, text)
        except Exception:
            pass
        try:
            self.smith_tool.set_play_cursor(k)
        except Exception:
            pass
        self.status.set("播放：" + text)
        self.play_after = self.after(60, self._play_tick)

    def stop_play(self):
        self.playing = False
        if self.play_after is not None:
            try:
                self.after_cancel(self.play_after)
            except Exception:
                pass
            self.play_after = None
        try:
            self.mag.set_cursor(-1)
        except Exception:
            pass
        try:
            self.smith_tool.set_play_cursor(-1)
        except Exception:
            pass

    def _smith_live_apply(self, zl, z0, f_hz, vf, d_lambda=0.0):
        """按 Smith 工具的负载/线长重建电路并仿真（拖拽实时调用）。"""
        import math as _m
        from ..components import Component
        from ..engine import Network, Port
        if f_hz <= 0 or z0 <= 0:
            return
        er = 1.0 / max(vf * vf, 1e-9)
        lam_m = 299792458.0 / (f_hz * _m.sqrt(er))
        length_mm = max(d_lambda, 0.0) * lam_m * 1000.0
        net = Network(z0)
        node = "p"
        if length_mm > 1e-6:
            net.add(Component("LT1", "TL", ["p", "a"],
                              {"z0": z0, "er": er, "len": length_mm}))
            node = "a"
        net.add(Component("LD_R", "R", [node, "b"], {"r": max(abs(zl.real), 1e-6)}))
        if zl.imag >= 0:
            L = zl.imag / (2 * _m.pi * f_hz) * 1e9
            net.add(Component("LD_X", "L", ["b", "0"], {"l": max(L, 1e-6)}))
        else:
            C = 1.0 / (2 * _m.pi * f_hz * abs(zl.imag)) * 1e12
            net.add(Component("LD_X", "C", ["b", "0"], {"c": max(C, 1e-6)}))
        net.ports = [Port("P1", "p", z0)]
        self.project.network = net
        ana = self.project.analysis
        ana.sweep = "linear"
        ana.points = 1001
        self.var_sweep.set("linear")
        self.var_pts.set("1001")
        ana.start_ghz = max(f_hz / 1e9 * 0.7, 1e-10)
        ana.stop_ghz = f_hz / 1e9 * 1.3
        self.set_analysis_display(ana.start_ghz, ana.stop_ghz)
        self.dirty = True
        self._refresh_tree()
        self._refresh_ports()
        self.run_sim()
        try:
            self.mag.mark_at_freq(f_hz / 1e9)
        except Exception:
            pass

    def _smith_apply_solution(self, sol):
        """把 L 型匹配解插到 P1 与电路之间，并重新仿真验证。"""
        from .. import smith as smith_mod

        net = self.project.network
        added = smith_mod.apply_to_network(net, sol, port_id="P1")
        if not added:
            raise ValueError("该解退化为直通，无需新增元件")
        self.dirty = True
        self._refresh_tree()
        self._refresh_ports()
        self.run_sim()
        names = "、".join(f"{c.cid}={c.param_text()}" for c in added)
        self.say(f"Smith 匹配已落地：{names}（P1 已接到新节点）")
        self.nb.select(self.nb.index(self.dual))

    def _apply_filter(self, r: dict):
        """用向导结果替换当前电路（统一走 builders，避免偶数阶末端悬空）。"""
        from ..builders import ladder_to_network

        net = ladder_to_network(r["items"], r["z0"])
        net.ports[0].pid = "P1"
        net.ports[1].pid = "P2"
        self.project.network = net
        self.project.name = r["desc"]
        self.var_z0.set(f"{r['z0']:g}")
        self.dirty = True
        self._refresh_tree()
        self._refresh_ports()
        self.say("已生成：" + r["desc"])
        self.run_sim()

    # ---------------------------------------------------------------- 文件
    def new_project(self):
        if not self._confirm_discard():
            return
        self.project = Project("新建工程")
        self.result = None
        self.ref_result = None
        self.project.network.ports = [Port("P1", "n1"), Port("P2", "n2")]
        self._sync_to_ui()
        self.say("已新建工程")

    def _sync_to_ui(self):
        self.var_start.set(f"{ghz_to_disp(self.project.analysis.start_ghz, self.project.freq_unit):g}")
        self.var_stop.set(f"{ghz_to_disp(self.project.analysis.stop_ghz, self.project.freq_unit):g}")
        self.var_pts.set(str(self.project.analysis.points))
        self.var_z0.set(f"{self.project.network.z0:g}")
        self.var_sweep.set(self.project.analysis.sweep)
        self.var_funit.set(self.project.freq_unit)
        self._freq_unit_last = self.project.freq_unit
        self._apply_freq_unit(self.project.freq_unit)
        self.var_step.set(f"{self.project.analysis.step_ghz:g}")
        self.var_single.set(bool(self.project.analysis.single))
        self._refresh_tree()
        self._refresh_ports()
        self._refresh_schematic()
        self.mag.set_data(None)
        self.rl_plot.set_data(None)
        self._fill_gain(None)
        self.smith_tool.set_result(None)
        self.smith_tool.load_dict(getattr(self.project, "smith", {}) or {})
        self.file_label.set(self.project.path or "（未保存）")
        self.dirty = False

    def open_project(self):
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(title="打开工程",
                                          filetypes=[("OpenRF 工程", "*.json"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            self.project = Project.load(path)
            self._sync_to_ui()
            self.say(f"已打开：{path}")
            self.run_sim()
        except Exception as e:  # noqa: BLE001
            dialogs.show_error(self, "打开失败", e,
                            "确认是 .json 工程文件，且没有被其它程序占用")

    def save_project(self, ask: bool = False):
        path = self.project.path
        if ask or not path:
            path = filedialog.asksaveasfilename(
                title="保存工程", defaultextension=".json",
                filetypes=[("OpenRF 工程", "*.json")],
                initialfile=(self.project.name + ".json"))
            if not path:
                return
        try:
            self.project.analysis = self._collect_analysis()
            self.project.network.z0 = float(self.var_z0.get())
            self.project.freq_unit = self.var_funit.get()
            self.project.smith = self.smith_tool.to_dict()
            self.project.save(path)
            self.file_label.set(path)
            self.dirty = False
            self.say(f"已保存：{path}")
        except Exception as e:  # noqa: BLE001
            dialogs.show_error(self, "保存失败", e,
                            "确认目标目录可写、文件没有被占用")

    def export_touchstone(self):
        if not self.result:
            self.run_sim()
        if not self.result:
            return
        n = self.result.n_ports()
        path = filedialog.asksaveasfilename(
            title="导出 Touchstone", defaultextension=f".s{n}p",
            filetypes=[(f"{n} 端口 S 参数", f"*.s{n}p"), ("所有文件", "*.*")],
            initialfile=f"{self.project.name}.s{n}p")
        if not path:
            return
        try:
            write_touchstone(path, self.result.freqs, self.result.s,
                             self.result.z0, comment=self.project.name)
            self.say(f"已导出：{path}")
        except Exception as e:  # noqa: BLE001
            dialogs.show_error(self, "导出失败", e,
                            "确认目标路径可写、文件没有被 Excel 之类的程序打开")

    def import_touchstone(self):
        path = filedialog.askopenfilename(
            title="导入 Touchstone（作为灰色虚线参考）",
            filetypes=[("Touchstone", "*.s?p"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            f, s, z0, n = read_touchstone(path)
            self.ref_result = SweepResult(freqs=f, s=s, z0=z0,
                                          port_names=[f"P{i}" for i in range(1, n + 1)])
            self.ref_name = os.path.basename(path)
            self.mag.ref_name = self.ref_name
            self.mag.set_data(self.result, self.ref_result)
            self.rl_plot.set_data(self.result, self.ref_result)
            self._fill_gain(self.result)
            self.say(f"已导入参考：{self.ref_name}（{len(f)} 点，{n} 端口，Z0={z0:g}Ω）")
        except Exception as e:  # noqa: BLE001
            dialogs.show_error(self, "导入失败", e,
                            "确认是 Touchstone 文件（.s2p/.s3p），且格式头与频率单位正确")

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        r = messagebox.askyesnocancel("未保存", "工程有修改，是否先保存？", parent=self)
        if r is None:
            return False
        if r:
            self.save_project()
        return True

    def on_close(self):
        self.stop_play()
        if self._confirm_discard():
            self.destroy()


def selftest() -> int:
    """自检：逐个打开对话框，确认能弹出、能关闭。

    打包成 exe 后才能复现"点了按钮没反应"这类问题，所以留一个
    `OpenRF_Studio.exe --selftest` 入口，装完直接跑一遍。
    """
    import traceback
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    from .ai_panel import AISettingsDialog
    from .line_dialog import LineImpedanceDialog
    from .rf_workbench import LMatchDialog

    ok, bad = 0, []
    app = App()
    app.geometry("+6000+6000")      # 挪到屏幕外，不打扰
    app.update()

    def check(name, factory):
        nonlocal ok
        dlg = None
        try:
            dlg = factory()
            # 等对话框完成"映射 -> 抓取"（激活是在 after(50) 里做的）
            deadline = time.time() + 2.0
            while time.time() < deadline:
                app.update()
                if (dlg.winfo_exists() and dlg.winfo_viewable()
                        and dlg.grab_current() is dlg):
                    break
                time.sleep(0.02)
            viewable = bool(dlg.winfo_viewable())
            grabbed = dlg.grab_current() is dlg
            state = ""
            try:
                state = dlg.state()
            except Exception:
                pass
            try:
                dlg.grab_release()
            except Exception:
                pass
            dlg.destroy()
            app.update()
            if viewable and grabbed:
                ok += 1
                print("  [OK]   %s（可见且已抓取）" % name)
            else:
                bad.append(name)
                print("  [FAIL] %s 可见=%s 抓取=%s state=%s"
                      % (name, viewable, grabbed, state))
        except Exception as exc:  # noqa: BLE001
            bad.append(name)
            print("  [FAIL] %s -> %s: %s" % (name, type(exc).__name__, exc))
            traceback.print_exc()

    check("反向计算", lambda: dialogs.InverseDialog(app))
    check("匹配计算器", lambda: MatchDialog(app, app))
    check("滤波器向导", lambda: dialogs.FilterWizard(app))
    check("传输线计算器", lambda: dialogs.TransmissionLineDialog(app))
    check("线阻抗计算", lambda: LineImpedanceDialog(app))
    check("L 型匹配", lambda: LMatchDialog(app, app, 100 + 0j, 50.0, 2.4e9))
    check("AI 设置", lambda: AISettingsDialog(app, app.ai_panel.cfg))
    check("元件参数", lambda: dialogs.ComponentDialog(app))

    app.destroy()
    print()
    # 控制台代码页是 GBK 时，✔ 这类符号会抛 UnicodeEncodeError，只用可编码字符
    print("自检通过（%d 项）" % ok if not bad else "自检失败：%s" % "、".join(bad))
    return 0 if not bad else 1


def main():
    enable_dpi()
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()