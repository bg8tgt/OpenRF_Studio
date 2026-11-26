"""对话框：元件编辑、滤波器向导、微带线计算器、帮助/关于。"""
from __future__ import annotations

import cmath
import math
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Dict, List, Optional

from ..components import Component
from ..synthesis import bandpass_lc, lowpass_lc
from .. import inverse, tline
from ..units import (FREQ_UNITS, LENGTH_UNITS, fmt_freq_smart,
                     length_from_mm, length_to_mm)
from ..engine import Port
from ..rfmath import fmt_vswr as _fv

FONT = ("Microsoft YaHei UI", 10)
FONT_S = ("Microsoft YaHei UI", 9)
FONT_B = ("Microsoft YaHei UI", 10, "bold")

KINDS = ["R", "L", "C", "RLCS", "RLCP", "TL", "MS", "COAX"]
KIND_CN = {"R": "电阻", "L": "电感", "C": "电容",
           "RLCS": "串联 RLC", "RLCP": "并联 RLC",
           "TL": "理想传输线", "MS": "微带线", "COAX": "同轴线"}
KIND_FIELDS = {
    "R": [("r", "阻值 R (Ω)", "50")],
    "L": [("l", "电感 L (nH)", "2")],
    "C": [("c", "电容 C (pF)", "1")],
    "RLCS": [("r", "电阻 R (Ω)", "10"), ("l", "电感 L (nH)", "5"),
             ("c", "电容 C (pF)", "1")],
    "RLCP": [("r", "电阻 R (Ω)", "100"), ("l", "电感 L (nH)", "5"),
             ("c", "电容 C (pF)", "1")],
    "TL": [("z0", "特性阻抗 Z0 (Ω)", "50"), ("er", "有效介电常数 εeff", "1"),
           ("len", "长度 (mm)", "10"), ("loss", "损耗 (dB/m，0=无损)", "0")],
    "MS": [("w", "线宽 W (mm)", "1"), ("h", "基板厚度 h (mm)", "0.5"),
           ("er", "基板 εr", "4.4"), ("len", "长度 (mm)", "10"),
           ("loss", "损耗 (dB/m，0=无损)", "0")],
    "COAX": [("d_in", "内导体直径 d (mm)", "0.91"), ("d_out", "外导体内径 D (mm)", "3.0"),
             ("er", "介质 εr", "2.1"), ("len", "长度 (mm)", "100"),
             ("loss", "损耗 (dB/m，0=无损)", "0")],
}
FREQ_UNIT_VALUES = ["Hz", "kHz", "MHz", "GHz"]


def freq_hz(text, unit: str) -> float:
    """「数值 + 单位」→ Hz。"""
    return float(text) * FREQ_UNITS[unit]


def freq_ghz(text, unit: str) -> float:
    """「数值 + 单位」→ GHz。"""
    return float(text) * FREQ_UNITS[unit] / 1e9


def add_freq_unit(parent, row, col, unit_var, padx=(6, 0)):
    """在表单里放一个频率单位下拉（Hz/kHz/MHz/GHz）。"""
    cb = ttk.Combobox(parent, textvariable=unit_var, values=FREQ_UNIT_VALUES,
                      state="readonly", width=6)
    cb.grid(row=row, column=col, sticky="w", padx=padx)
    return cb


def show_error(parent, title: str, exc, hint: str = "") -> None:
    """统一的错误弹窗：异常原文 + 一句可执行的下一步。"""
    msg = str(exc) or type(exc).__name__
    if hint:
        msg += "\n\n下一步：" + hint
    messagebox.showerror(title, msg, parent=parent)


class ModalDialog(tk.Toplevel):
    def __init__(self, master, title: str, w: int = 380, h: int = 320):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.transient(master)
        self.result = None
        self.geometry(f"{w}x{h}")
        self.update_idletasks()
        try:
            x = master.winfo_rootx() + (master.winfo_width() - w) // 2
            y = master.winfo_rooty() + (master.winfo_height() - h) // 3
            # 钳制到屏幕可见范围：对话框若落在屏幕外，它仍会抓住 grab，
            # 主窗口就再也点不动了——表现正是"弹窗不出来 + 卡死"。
            sw, sh = master.winfo_screenwidth(), master.winfo_screenheight()
            x = max(0, min(int(x), max(sw - w - 8, 0)))
            y = max(0, min(int(y), max(sh - h - 48, 0)))
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass
        self.bind("<Escape>", lambda e: self.destroy())
        # 先占住底部按钮条，避免内容区把它挤扁导致按钮文字被裁掉
        self._btn_bar = ttk.Frame(self)
        self._btn_bar.pack(side="bottom", fill="x", padx=10, pady=8)
        self._btn_bar.pack_propagate(False)
        self._btn_bar.configure(height=44)

        # 窗口映射后才能 grab_set；在未映射时调用会抛 TclError。
        # 这里延后一拍再激活，失败有限重试，绝不无限重试（否则事件循环被塞满）。
        self._grab_tries = 0
        self.after(50, self._activate)

    def _activate(self):
        try:
            if not self.winfo_exists():
                return
            self.deiconify()
            self.lift()
            self.focus_force()
            if not self.winfo_viewable():
                raise RuntimeError("窗口还没映射")
            self.grab_set()
        except Exception:
            self._grab_tries += 1
            if self._grab_tries < 8:
                try:
                    self.after(60, self._activate)
                except Exception:
                    pass

    def destroy(self):
        """销毁时一定要释放 grab，否则第二次弹窗会抓不到、界面看起来像卡死。"""
        try:
            self.grab_release()
        except Exception:
            pass
        super().destroy()

    def buttons(self, ok_text="确定", on_ok=None):
        bar = self._btn_bar
        for w in bar.winfo_children():
            w.destroy()
        ttk.Button(bar, text="取消", command=self.destroy,
                   padding=(16, 5)).pack(side="right", padx=4, pady=6)
        ttk.Button(bar, text=ok_text, command=on_ok or self._ok,
                   padding=(16, 5)).pack(side="right", padx=4, pady=6)

    def _ok(self):
        self.destroy()


class ComponentDialog(ModalDialog):
    """新增/编辑元件。"""

    def __init__(self, master, comp: Optional[Component] = None,
                 default_kind: str = "R", existing_nodes: Optional[List[str]] = None):
        super().__init__(master, "元件参数", 420, 380 if comp and comp.kind in ("TL", "MS") else 340)
        self.comp = comp
        self.existing_nodes = existing_nodes or ["n1", "n2"]
        top = ttk.Frame(self, padding=12)
        top.pack(fill="both", expand=True)
        ttk.Label(top, text="编号").grid(row=0, column=0, sticky="w", pady=4)
        self.var_id = tk.StringVar(value=comp.cid if comp else "")
        ttk.Entry(top, textvariable=self.var_id, width=18).grid(row=0, column=1, sticky="w")
        ttk.Label(top, text="类型").grid(row=1, column=0, sticky="w", pady=4)
        self.var_kind = tk.StringVar(value=comp.kind if comp else default_kind)
        cb = ttk.Combobox(top, textvariable=self.var_kind, values=KINDS,
                          state="readonly", width=16)
        cb.grid(row=1, column=1, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda e: self._build_fields())
        self.fields_frame = ttk.LabelFrame(top, text="参数", padding=8)
        self.fields_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=8)
        self.vars: Dict[str, tk.StringVar] = {}
        self._build_fields()

        ttk.Label(top, text="节点 1").grid(row=3, column=0, sticky="w", pady=4)
        self.var_n1 = tk.StringVar(value=comp.nodes[0] if comp else self.existing_nodes[0])
        ttk.Entry(top, textvariable=self.var_n1, width=18).grid(row=3, column=1, sticky="w")
        ttk.Label(top, text="节点 2（地填 0）").grid(row=4, column=0, sticky="w", pady=4)
        self.var_n2 = tk.StringVar(value=comp.nodes[1] if comp else
                                   (self.existing_nodes[1] if len(self.existing_nodes) > 1 else "0"))
        ttk.Entry(top, textvariable=self.var_n2, width=18).grid(row=4, column=1, sticky="w")
        ttk.Label(top, text="提示：并联元件把节点 2 设为 0（地）。",
                  foreground="#6b7280", font=FONT_S).grid(row=5, column=0, columnspan=2,
                                                         sticky="w", pady=(6, 0))
        self.buttons("保存", self._ok)

    def _build_fields(self):
        for w in self.fields_frame.winfo_children():
            w.destroy()
        self.vars.clear()
        kind = self.var_kind.get()
        for r, (key, label, default) in enumerate(KIND_FIELDS[kind]):
            ttk.Label(self.fields_frame, text=label).grid(row=r, column=0, sticky="w", pady=3)
            val = default
            if self.comp and self.comp.kind == kind:
                val = f"{self.comp.params.get(key, float(default)):g}"
            v = tk.StringVar(value=val)
            self.vars[key] = v
            ttk.Entry(self.fields_frame, textvariable=v, width=16).grid(row=r, column=1, sticky="w")

    def _ok(self):
        cid = self.var_id.get().strip()
        if not cid:
            messagebox.showwarning("提示", "编号不能为空", parent=self)
            return
        kind = self.var_kind.get()
        params = {}
        for key, var in self.vars.items():
            txt = var.get().strip()
            try:
                params[key] = float(txt)
            except ValueError:
                messagebox.showwarning("提示", f"参数 {key} 不是数字：{txt}", parent=self)
                return
        nodes = [self.var_n1.get().strip() or "n1", self.var_n2.get().strip() or "0"]
        self.result = Component(cid, kind, nodes, params)
        self.destroy()


class FilterWizard(ModalDialog):
    """低通/带通 LC 滤波器向导（切比雪夫或巴特沃斯）。"""

    def __init__(self, master, z0: float = 50.0):
        super().__init__(master, "滤波器设计向导", 460, 430)
        f = ttk.Frame(self, padding=14)
        f.pack(fill="both", expand=True)
        self.var_topo = tk.StringVar(value="lowpass")
        ttk.Label(f, text="响应类型").grid(row=0, column=0, sticky="w", pady=4)
        box = ttk.Frame(f)
        box.grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(box, text="低通", value="lowpass", variable=self.var_topo).pack(side="left")
        ttk.Radiobutton(box, text="带通", value="bandpass", variable=self.var_topo).pack(side="left")

        ttk.Label(f, text="逼近方式").grid(row=1, column=0, sticky="w", pady=4)
        self.var_kind = tk.StringVar(value="chebyshev")
        ttk.Combobox(f, textvariable=self.var_kind, state="readonly", width=18,
                     values=["chebyshev", "butterworth"]).grid(row=1, column=1, sticky="w")

        self.var_n = tk.StringVar(value="3")
        ttk.Label(f, text="阶数 n").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Spinbox(f, from_=1, to=12, textvariable=self.var_n, width=8).grid(row=2, column=1, sticky="w")

        self.var_funit = tk.StringVar(value="MHz")
        self.var_fc = tk.StringVar(value="3000")
        ttk.Label(f, text="截止频率 fc").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.var_fc, width=18).grid(row=3, column=1, sticky="w")
        add_freq_unit(f, 3, 2, self.var_funit)

        self.var_f1 = tk.StringVar(value="2300")
        self.var_f2 = tk.StringVar(value="2700")
        ttk.Label(f, text="带通下边频").grid(row=4, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.var_f1, width=18).grid(row=4, column=1, sticky="w")
        ttk.Label(f, text="带通上边频").grid(row=5, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.var_f2, width=18).grid(row=5, column=1, sticky="w")

        self.var_ripple = tk.StringVar(value="0.5")
        ttk.Label(f, text="通带纹波 (dB)").grid(row=6, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.var_ripple, width=18).grid(row=6, column=1, sticky="w")

        self.var_z0 = tk.StringVar(value=f"{z0:g}")
        ttk.Label(f, text="系统阻抗 Z0 (Ω)").grid(row=7, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.var_z0, width=18).grid(row=7, column=1, sticky="w")

        ttk.Label(f, text="说明：生成理想 LC 梯形网络（不含寄生/版图）；\n"
                          "带通将自动展开为串联 LC / 并联 LC 支路。",
                  foreground="#6b7280", font=FONT_S).grid(row=8, column=0, columnspan=2,
                                                         sticky="w", pady=(8, 0))
        self.buttons("生成电路", self._ok)

    def _ok(self):
        try:
            n = int(float(self.var_n.get()))
            z0 = float(self.var_z0.get())
            ripple = float(self.var_ripple.get())
            topo = self.var_topo.get()
            kind = self.var_kind.get()
            u = self.var_funit.get()
            if topo == "lowpass":
                fc_hz = freq_hz(self.var_fc.get(), u)
                items = lowpass_lc(n, fc_hz, z0, ripple, kind)
                desc = (f"{n} 阶{'切比雪夫' if kind == 'chebyshev' else '巴特沃斯'}"
                        f"低通 fc={fmt_freq_smart(fc_hz, u)}")
            else:
                f1_hz = freq_hz(self.var_f1.get(), u)
                f2_hz = freq_hz(self.var_f2.get(), u)
                items = bandpass_lc(n, f1_hz, f2_hz, z0, ripple, kind)
                desc = (f"{n} 阶{'切比雪夫' if kind == 'chebyshev' else '巴特沃斯'}"
                        f"带通 {fmt_freq_smart(f1_hz, u)}–{fmt_freq_smart(f2_hz, u)}")
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("参数错误", str(e), parent=self)
            return
        self.result = {"items": items, "z0": z0, "desc": desc,
                       "topo": topo, "n": n, "ripple": ripple}
        self.destroy()


# ---- 基板预设（公开数据手册典型值） ----
SUBSTRATES = [
    ("自定义", None, None),
    ("FR-4（εr 4.4, h 1.6mm）", 4.4, 1.6),
    ("Rogers RO4350B（3.66, 0.762mm）", 3.66, 0.762),
    ("Rogers RO4003C（3.55, 0.813mm）", 3.55, 0.813),
    ("氧化铝 99.6%（9.8, 0.635mm）", 9.8, 0.635),
    ("空气（1.0）", 1.0, 1.0),
]


class TransmissionLineDialog(ModalDialog):
    """传输线计算器：微带 / 带状线 / 同轴。

    支持 mm/mil 与 GHz/MHz 单位切换；三类线都用公开公式：
      微带 Hammerstad-Jensen；带状线 IPC-2141 闭式；同轴精确解析。
    """

    def __init__(self, master):
        super().__init__(master, "传输线计算器", 660, 620)
        self.resizable(True, True)
        top = ttk.Frame(self, padding=(14, 10, 14, 0))
        top.pack(fill="x")
        ttk.Label(top, text="长度单位").pack(side="left")
        self.u_len = tk.StringVar(value="mm")
        ttk.Combobox(top, textvariable=self.u_len, values=list(LENGTH_UNITS),
                     state="readonly", width=6).pack(side="left", padx=(4, 14))
        ttk.Label(top, text="频率单位").pack(side="left")
        self.u_freq = tk.StringVar(value="MHz")
        ttk.Combobox(top, textvariable=self.u_freq, values=FREQ_UNIT_VALUES,
                     state="readonly", width=6).pack(side="left", padx=(4, 14))
        ttk.Label(top, text="频率").pack(side="left")
        self.v_f = tk.StringVar(value="2400")
        ttk.Entry(top, textvariable=self.v_f, width=10).pack(side="left", padx=4)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=12, pady=8)
        self.vars = {}
        self._build_microstrip()
        self._build_stripline()
        self._build_coax()

        self.out = tk.Text(self, height=9, font=FONT_S, wrap="word",
                           relief="solid", borderwidth=1)
        self.out.pack(fill="both", expand=False, padx=12)
        self.out.insert("1.0", "选择线型 → 填参数 → 点相应按钮。\n"
                               "公式：微带 Hammerstad-Jensen（含色散）；带状线 IPC-2141；同轴精确解析。\n")
        self.buttons("关闭")

    # ---------- 三个页签 ----------
    def _tab(self, key):
        fr = ttk.Frame(self.nb, padding=12)
        self.nb.add(fr, text={"ms": "  微带线  ", "sl": "  带状线  ", "cx": "  同轴  "}[key])
        self.vars[key] = {}
        return fr

    def _field(self, parent, key, label, default, row, col=0):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", pady=3)
        v = tk.StringVar(value=default)
        self.vars[key][label] = v
        ttk.Entry(parent, textvariable=v, width=14).grid(row=row, column=col + 1, sticky="w", padx=(4, 12))
        return v

    def _build_microstrip(self):
        fr = self._tab("ms")
        self._field(fr, "ms", "Z0 (Ω)", "50", 0)
        self._field(fr, "ms", "线宽 W", "1.0", 1)
        self._field(fr, "ms", "基板厚度 h", "1.6", 2)
        self._field(fr, "ms", "基板 εr", "4.4", 3)
        ttk.Label(fr, text="基板预设").grid(row=4, column=0, sticky="w", pady=(8, 3))
        self.sub_preset = tk.StringVar(value=SUBSTRATES[0][0])
        cb = ttk.Combobox(fr, textvariable=self.sub_preset,
                          values=[s[0] for s in SUBSTRATES], state="readonly", width=30)
        cb.grid(row=4, column=1, columnspan=2, sticky="w")
        cb.bind("<<ComboboxSelected>>", self._on_preset)
        bar = ttk.Frame(fr)
        bar.grid(row=5, column=0, columnspan=3, sticky="w", pady=10)
        ttk.Button(bar, text="由 Z0 算线宽", command=self.ms_design).pack(side="left", padx=3)
        ttk.Button(bar, text="分析（W→Z0）", command=self.ms_analyze).pack(side="left", padx=3)
        ttk.Button(bar, text="λ/4 长度", command=self.ms_quarter).pack(side="left", padx=3)

    def _build_stripline(self):
        fr = self._tab("sl")
        self._field(fr, "sl", "Z0 (Ω)", "50", 0)
        self._field(fr, "sl", "线宽 W", "0.66", 1)
        self._field(fr, "sl", "地间距 b", "1.6", 2)
        self._field(fr, "sl", "基板 εr", "4.4", 3)
        self._field(fr, "sl", "铜厚 t", "0", 4)
        bar = ttk.Frame(fr)
        bar.grid(row=5, column=0, columnspan=3, sticky="w", pady=10)
        ttk.Button(bar, text="由 Z0 算线宽", command=self.sl_design).pack(side="left", padx=3)
        ttk.Button(bar, text="分析（W→Z0）", command=self.sl_analyze).pack(side="left", padx=3)
        ttk.Button(bar, text="λ/4 长度", command=self.sl_quarter).pack(side="left", padx=3)

    def _build_coax(self):
        fr = self._tab("cx")
        self._field(fr, "cx", "Z0 (Ω)", "50", 0)
        self._field(fr, "cx", "内导体 d", "0.91", 1)
        self._field(fr, "cx", "外导体内径 D", "3.0", 2)
        self._field(fr, "cx", "介质 εr", "2.1", 3)
        bar = ttk.Frame(fr)
        bar.grid(row=4, column=0, columnspan=3, sticky="w", pady=10)
        ttk.Button(bar, text="由 Z0 算外径 D", command=self.cx_design).pack(side="left", padx=3)
        ttk.Button(bar, text="分析（D/d→Z0）", command=self.cx_analyze).pack(side="left", padx=3)
        ttk.Button(bar, text="λ/4 长度", command=self.cx_quarter).pack(side="left", padx=3)

    # ---------- 单位转换 ----------
    def _mm(self, key: str, label: str) -> float:
        return length_to_mm(float(self.vars[key][label].get()), self.u_len.get())

    def _f(self) -> float:
        return float(self.v_f.get()) * FREQ_UNITS[self.u_freq.get()]

    def _fmt(self, mm: float) -> str:
        return f"{length_from_mm(mm, self.u_len.get()):.4g} {self.u_len.get()}"

    def _say(self, text: str):
        self.out.delete("1.0", "end")
        self.out.insert("1.0", text)

    def _report(self, d: dict, title: str) -> str:
        lines = [f"【{title}】Z0 = {d['z0']:.3f} Ω，εeff = {d['eeff']:.4f}"]
        for k, label in (("w_mm", "线宽 W"), ("b_mm", "地间距 b"),
                         ("d_in_mm", "内导体 d"), ("d_out_mm", "外导体 D")):
            if k in d:
                lines.append(f"  {label} = {self._fmt(d[k])}")
        if d.get("quarter_mm"):
            lines.append(f"  λ/4 @ {self.v_f.get()} {self.u_freq.get()} = {self._fmt(d['quarter_mm'])}")
            lines.append(f"  电长度 = {d['elen_deg_per_mm'] * 1:.4g} °/mm"
                         f"（按当前 εeff，1 mm 计）")
        return "\n".join(lines)

    # ---------- 微带 ----------
    def _ms_inputs(self):
        return (self._mm("ms", "基板厚度 h"), float(self.vars["ms"]["基板 εr"].get()))

    def ms_design(self):
        try:
            h, er = self._ms_inputs()
            z0 = float(self.vars["ms"]["Z0 (Ω)"].get())
            d = tline.microstrip_design(z0, h, er, self._f())
            self.vars["ms"]["线宽 W"].set(f"{length_from_mm(d['w_mm'], self.u_len.get()):.4g}")
            self._say(self._report(d, "微带线综合"))
        except Exception as e:  # noqa: BLE001
            self._say(f"错误：{e}")

    def ms_analyze(self):
        try:
            h, er = self._ms_inputs()
            w = self._mm("ms", "线宽 W")
            d = tline.microstrip(w, h, er, self._f())
            self.vars["ms"]["Z0 (Ω)"].set(f"{d['z0']:.3f}")
            self._say(self._report(d, "微带线分析"))
        except Exception as e:  # noqa: BLE001
            self._say(f"错误：{e}")

    def ms_quarter(self):
        try:
            h, er = self._ms_inputs()
            w = self._mm("ms", "线宽 W")
            d = tline.microstrip(w, h, er, self._f())
            self._say(self._report(d, "微带线 λ/4"))
        except Exception as e:  # noqa: BLE001
            self._say(f"错误：{e}")

    def _on_preset(self, _ev=None):
        name = self.sub_preset.get()
        for nm, er, h in SUBSTRATES:
            if nm == name and er is not None:
                self.vars["ms"]["基板 εr"].set(f"{er:g}")
                self.vars["ms"]["基板厚度 h"].set(f"{length_from_mm(h, self.u_len.get()):.4g}")
                break

    # ---------- 带状线 ----------
    def _sl_inputs(self):
        return (self._mm("sl", "地间距 b"), float(self.vars["sl"]["基板 εr"].get()),
                self._mm("sl", "铜厚 t"))

    def sl_design(self):
        try:
            b, er, t = self._sl_inputs()
            z0 = float(self.vars["sl"]["Z0 (Ω)"].get())
            d = tline.stripline_design(z0, b, er, t, self._f())
            self.vars["sl"]["线宽 W"].set(f"{length_from_mm(d['w_mm'], self.u_len.get()):.4g}")
            self._say(self._report(d, "带状线综合（IPC-2141 近似）"))
        except Exception as e:  # noqa: BLE001
            self._say(f"错误：{e}")

    def sl_analyze(self):
        try:
            b, er, t = self._sl_inputs()
            w = self._mm("sl", "线宽 W")
            d = tline.stripline(w, b, er, t, self._f())
            self.vars["sl"]["Z0 (Ω)"].set(f"{d['z0']:.3f}")
            self._say(self._report(d, "带状线分析（IPC-2141 近似）"))
        except Exception as e:  # noqa: BLE001
            self._say(f"错误：{e}")

    def sl_quarter(self):
        try:
            b, er, t = self._sl_inputs()
            w = self._mm("sl", "线宽 W")
            d = tline.stripline(w, b, er, t, self._f())
            self._say(self._report(d, "带状线 λ/4"))
        except Exception as e:  # noqa: BLE001
            self._say(f"错误：{e}")

    # ---------- 同轴 ----------
    def _cx_inputs(self):
        return (self._mm("cx", "内导体 d"), float(self.vars["cx"]["介质 εr"].get()))

    def cx_design(self):
        try:
            d_in, er = self._cx_inputs()
            z0 = float(self.vars["cx"]["Z0 (Ω)"].get())
            d = tline.coax_design(z0, d_in, er, self._f())
            self.vars["cx"]["外导体内径 D"].set(f"{length_from_mm(d['d_out_mm'], self.u_len.get()):.4g}")
            self._say(self._report(d, "同轴综合"))
        except Exception as e:  # noqa: BLE001
            self._say(f"错误：{e}")

    def cx_analyze(self):
        try:
            d_in, er = self._cx_inputs()
            d_out = self._mm("cx", "外导体内径 D")
            d = tline.coax(d_in, d_out, er, self._f())
            self.vars["cx"]["Z0 (Ω)"].set(f"{d['z0']:.3f}")
            self._say(self._report(d, "同轴分析"))
        except Exception as e:  # noqa: BLE001
            self._say(f"错误：{e}")

    def cx_quarter(self):
        try:
            d_in, er = self._cx_inputs()
            d_out = self._mm("cx", "外导体内径 D")
            d = tline.coax(d_in, d_out, er, self._f())
            self._say(self._report(d, "同轴 λ/4"))
        except Exception as e:  # noqa: BLE001
            self._say(f"错误：{e}")


class InverseDialog(ModalDialog):
    """反向计算：由目标频率/阻抗反求要加或要换的元件。"""

    def __init__(self, master):
        super().__init__(master, "反向计算", 660, 600)
        self.resizable(True, True)
        top = ttk.Frame(self, padding=(12, 10, 12, 0))
        top.pack(fill="x")
        ttk.Label(top, text="频率单位").pack(side="left")
        self.var_funit = tk.StringVar(value="MHz")
        ttk.Combobox(top, textvariable=self.var_funit, values=FREQ_UNIT_VALUES,
                     state="readonly", width=6).pack(side="left", padx=(4, 8))
        ttk.Label(top, text="（下面所有频率输入都按这个单位）",
                  foreground="#6b7280", font=FONT_S).pack(side="left")
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        self.vars = {}
        self._build_lc()
        self._build_retune()
        self._build_match()
        self._build_from_s11()
        self.out = tk.Text(self, height=10, font=FONT_S, wrap="word",
                           relief="solid", borderwidth=1)
        self.out.pack(fill="both", expand=False, padx=12)
        self.out.insert("1.0", "选择页签 → 填已知量 → 点「计算」。\n"
                               "未使用的输入框留空即可（LC 谐振页）。\n")
        self.buttons("应用到电路", self.apply_last)

    # ---------- 工具 ----------
    def _tab(self, title):
        fr = ttk.Frame(self.nb, padding=12)
        self.nb.add(fr, text=title)
        return fr

    def _field(self, parent, tab, label, default, row, col=0, width=14):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", pady=3)
        v = tk.StringVar(value=default)
        self.vars.setdefault(tab, {})[label] = v
        ttk.Entry(parent, textvariable=v, width=width).grid(
            row=row, column=col + 1, sticky="w", padx=(4, 12))
        return v

    def _get(self, tab, label) -> str:
        return self.vars[tab][label].get().strip()

    def _f(self, tab, label) -> float:
        return float(self._get(tab, label))

    def _fhz(self, tab, label) -> float:
        """按当前选择的频率单位读入，返回 Hz。"""
        return float(self._get(tab, label)) * FREQ_UNITS[self.var_funit.get()]

    def _say(self, text: str):
        self.out.delete("1.0", "end")
        self.out.insert("1.0", text)

    # ---------- 1. LC 谐振 ----------
    def _build_lc(self):
        fr = self._tab("  LC 谐振  ")
        self._field(fr, "lc", "谐振频率", "2400", 0)
        self._field(fr, "lc", "电感 L (nH)", "10", 1)
        self._field(fr, "lc", "电容 C (pF)", "", 2)
        ttk.Label(fr, text="三个量中留空一个，程序求它；三个都填则校验实际谐振频率。",
                  foreground="#6b7280", font=FONT_S).grid(row=3, column=0, columnspan=2,
                                                         sticky="w", pady=(6, 0))
        ttk.Button(fr, text="计算", command=self.calc_lc).grid(row=4, column=1,
                                                               sticky="w", pady=10)

    def calc_lc(self):
        try:
            f_txt = self._get("lc", "谐振频率")
            l_txt = self._get("lc", "电感 L (nH)")
            c_txt = self._get("lc", "电容 C (pF)")
            f = self._fhz("lc", "谐振频率") if f_txt else None
            l = float(l_txt) if l_txt else None
            cc = float(c_txt) if c_txt else None
            r = inverse.lc_resonance(f, l, cc)
            self.last = ("lc", r, f)
            self._say(f"【LC 谐振】\n"
                      f"  频率 f0 = {fmt_freq_smart(r['f_hz'], self.var_funit.get())}\n"
                      f"  电感 L  = {r['l_nh']:.6g} nH\n"
                      f"  电容 C  = {r['c_pf']:.6g} pF\n"
                      f"  {r['note']}")
        except Exception as e:  # noqa: BLE001
            self._say(f"错误：{e}")

    # ---------- 2. 改频微调 ----------
    def _build_retune(self):
        fr = self._tab("  改频微调  ")
        self._field(fr, "rt", "当前电感 L (nH)", "4.2344", 0)
        self._field(fr, "rt", "当前电容 C (pF)", "1.16361", 1)
        self._field(fr, "rt", "目标频率", "2500", 2)
        ttk.Label(fr, text="保留哪个元件").grid(row=3, column=0, sticky="w", pady=3)
        self.var_keep = tk.StringVar(value="L")
        cb = ttk.Combobox(fr, textvariable=self.var_keep, state="readonly", width=12,
                          values=["L（换电容）", "C（换电感）"])
        cb.grid(row=3, column=1, sticky="w")
        self.cb_keep = cb
        ttk.Label(fr, text="用于：现有 LC 已焊好，只想换一个元件把频率调过去。",
                  foreground="#6b7280", font=FONT_S).grid(row=4, column=0, columnspan=2,
                                                         sticky="w", pady=(6, 0))
        ttk.Button(fr, text="计算", command=self.calc_retune).grid(row=5, column=1,
                                                                  sticky="w", pady=10)

    def calc_retune(self):
        try:
            keep = "L" if self.var_keep.get().startswith("L") else "C"
            r = inverse.retune_lc(self._f("rt", "当前电感 L (nH)"),
                                  self._f("rt", "当前电容 C (pF)"),
                                  self._fhz("rt", "目标频率"), keep)
            self.last = ("retune", r, self._fhz("rt", "目标频率"))
            delta = (f"  需要改的元件：C {r['delta_pf']:+.4g} pF" if keep == "L"
                     else f"  需要改的元件：L {r['delta_nh']:+.4g} nH")
            self._say(f"【改频微调】\n"
                      f"  当前谐振 = {fmt_freq_smart(r['f_now_hz'], self.var_funit.get())}\n"
                      f"  目标频率 = {fmt_freq_smart(r['f_target_hz'], self.var_funit.get())}\n"
                      f"  新 L = {r['l_nh']:.6g} nH，新 C = {r['c_pf']:.6g} pF\n"
                      f"  {delta}\n"
                      f"  校验谐振 = {fmt_freq_smart(r['f_check_hz'], self.var_funit.get(), 6)}\n"
                      f"  {r['note']}")
        except Exception as e:  # noqa: BLE001
            self._say(f"错误：{e}")

    # ---------- 3. 阻抗匹配 ----------
    def _build_match(self):
        fr = self._tab("  L 型匹配  ")
        self._field(fr, "mt", "源阻抗 Rs (Ω)", "50", 0)
        self._field(fr, "mt", "负载阻抗 Rl (Ω)", "100", 1)
        self._field(fr, "mt", "频率", "2400", 2)
        ttk.Label(fr, text="输出两种解：低通型（并 C + 串 L）与高通型（并 L + 串 C）。",
                  foreground="#6b7280", font=FONT_S).grid(row=3, column=0, columnspan=2,
                                                         sticky="w", pady=(6, 0))
        ttk.Button(fr, text="计算", command=self.calc_match).grid(row=4, column=1,
                                                                 sticky="w", pady=10)

    def calc_match(self):
        try:
            r = inverse.l_network_match(self._f("mt", "源阻抗 Rs (Ω)"),
                                        self._f("mt", "负载阻抗 Rl (Ω)"),
                                        self._fhz("mt", "频率"))
            if r.get("identity"):
                self._say("源与负载相等，无需匹配网络。")
                return
            self.last = ("match", r, self._fhz("mt", "频率"))
            lines = [f"【L 型匹配】Q = {r['q']:.4f}", f"  {r['note']}"]
            for i, s in enumerate(r["solutions"], 1):
                lines.append(f"  方案 {i}：{s['name']}")
                lines.append(f"    {s['shunt']['element']} = {s['shunt']['value']:.4g} "
                             f"{s['shunt']['unit']}")
                lines.append(f"    {s['series']['element']} = {s['series']['value']:.4g} "
                             f"{s['series']['unit']}")
            self._say("\n".join(lines))
        except Exception as e:  # noqa: BLE001
            self._say(f"错误：{e}")

    # ---------- 4. 由 S11 反算 ----------
    def _build_from_s11(self):
        fr = self._tab("  由 S11 反算  ")
        self._field(fr, "s11", "|S11|", "0.333", 0)
        self._field(fr, "s11", "∠S11 (°)", "0", 1)
        self._field(fr, "s11", "频率", "2400", 2)
        ttk.Label(fr, text="由反射系数求输入阻抗，再算需要串/并多大的电抗（用 L 或 C 实现）。",
                  foreground="#6b7280", font=FONT_S).grid(row=3, column=0, columnspan=2,
                                                         sticky="w", pady=(6, 0))
        ttk.Button(fr, text="计算", command=self.calc_s11).grid(row=4, column=1,
                                                               sticky="w", pady=10)

    def calc_s11(self):
        try:
            mag = self._f("s11", "|S11|")
            ph = self._f("s11", "∠S11 (°)")
            f = self._fhz("s11", "频率")
            g = cmath.rect(mag, math.radians(ph))
            r = inverse.match_from_s11(g, f)
            self.last = ("s11", r, f)
            lines = [f"【由 S11 反算】",
                     f"  Γ = {g.real:+.4f}{g.imag:+.4f}j",
                     f"  Zin = {r['zin'].real:.4f}{r['zin'].imag:+.4f}j Ω"
                     f"（归一 {r['zin_norm'].real:.4f}{r['zin_norm'].imag:+.4f}j）",
                     f"  VSWR = {_fv(r['vswr'])}"]
            if r["series"]:
                lines.append(f"  串联方案：{r['series']['text']}")
            if r["shunt"]:
                lines.append(f"  并联方案：{r['shunt']['text']}")
            for n in r["notes"]:
                lines.append(f"  · {n}")
            self._say("\n".join(lines))
        except Exception as e:  # noqa: BLE001
            self._say(f"错误：{e}")


    # ---------- 应用到电路（反算 → 建网 → 仿真 → 出图） ----------
    def apply_last(self):
        last = getattr(self, "last", None)
        if not last:
            self._say("请先点「计算」得到结果。")
            return
        app = self.master
        if not hasattr(app, "project"):
            self._say("当前环境无法修改电路。")
            return
        kind, payload, f_hz = last
        try:
            net, f = self._build_network(kind, payload, f_hz)
            app.project.network = net
            ana = app.project.analysis
            ana.start_ghz = max(f / 1e9 * 0.6, 1e-6)
            ana.stop_ghz = max(f / 1e9 * 1.4, ana.start_ghz + 1e-6)
            ana.points = max(401, ana.points)
            app.set_analysis_display(ana.start_ghz, ana.stop_ghz)
            for fn in ("_refresh_tree", "_refresh_ports", "_refresh_schematic"):
                try:
                    getattr(app, fn)()
                except Exception:
                    pass
            app.run_sim()
            try:
                app.nb.select(0)
            except Exception:
                pass
            self._say("已应用：电路已重建并完成仿真（看「直角坐标图」/「史密斯圆图」）。")
            self.destroy()
        except Exception as e:  # noqa: BLE001
            self._say(f"应用失败：{e}")

    def _build_network(self, kind, payload, f_hz):
        import math as _m
        from ..components import Component
        from ..engine import Network, Port
        z0 = 50.0
        net = Network(z0)
        if kind == "lc":
            r = payload
            net.add(Component("L1", "L", ["p", "a"], {"l": max(r["l_nh"], 1e-6)}))
            net.add(Component("C1", "C", ["a", "b"], {"c": max(r["c_pf"], 1e-6)}))
            net.add(Component("RL", "R", ["b", "0"], {"r": z0}))
            net.ports = [Port("P1", "p", z0)]
            return net, f_hz
        if kind == "retune":
            r = payload
            proj = self.master.project
            for c in proj.network.components:
                if c.kind == "L" and "l" in c.params:
                    c.params["l"] = max(r["l_nh"], 1e-6)
                    break
            for c in proj.network.components:
                if c.kind == "C" and "c" in c.params:
                    c.params["c"] = max(r["c_pf"], 1e-6)
                    break
            return proj.network, f_hz
        if kind == "match":
            m = payload
            sol = m["solutions"][0]
            lk = lambda e: "l" if e["kind"] == "L" else "c"
            net.add(Component("XS", sol["series"]["kind"], ["p", "a"],
                              {lk(sol["series"]): sol["series"]["value"]}))
            side = m.get("shunt_side", "load")
            if side == "load":
                net.add(Component("XP", sol["shunt"]["kind"], ["a", "0"],
                                  {lk(sol["shunt"]): sol["shunt"]["value"]}))
                net.add(Component("RL", "R", ["a", "0"], {"r": m["r_high"]}))
            else:
                net.add(Component("XP", sol["shunt"]["kind"], ["p", "0"],
                                  {lk(sol["shunt"]): sol["shunt"]["value"]}))
                net.add(Component("RL", "R", ["a", "0"], {"r": m["r_low"]}))
            net.ports = [Port("P1", "p", z0)]
            return net, f_hz
        r = payload
        zin = r["zin"]
        w = 2 * _m.pi * f_hz
        net.add(Component("RL", "R", ["a", "b"], {"r": max(zin.real, 1e-6)}))
        if zin.imag >= 0:
            net.add(Component("XL", "L", ["b", "0"],
                              {"l": max(zin.imag / w * 1e9, 1e-6)}))
        else:
            net.add(Component("XC", "C", ["b", "0"],
                              {"c": 1 / (w * abs(zin.imag)) * 1e12}))
        if r.get("series"):
            e = r["series"]
            net.add(Component("XS", e["kind"], ["p", "a"],
                              {"l" if e["kind"] == "L" else "c": e["value"]}))
        elif r.get("shunt"):
            e = r["shunt"]
            net.add(Component("XP", e["kind"], ["p", "0"],
                              {"l" if e["kind"] == "L" else "c": e["value"]}))
            net.add(Component("TL0", "TL", ["p", "a"], {"z0": z0, "er": 1.0, "len": 0.01}))
        else:
            raise ValueError("没有可应用的补偿元件")
        net.ports = [Port("P1", "p", z0)]
        return net, f_hz

HELP_TEXT = """【OpenRF Studio 射频工作台 使用说明】

一、基本流程
  1. 在左侧「电路元件」区点「添加元件」，选类型（电阻/电感/电容/理想传输线/微带线/同轴线），
     填参数与两个节点（并联元件把节点 2 填 0 表示接地）。
  2. 在「端口」区设置端口（默认 P1→n1、P2→n2）。
  3. 在「分析设置」填起止频率、单位、步进或点数、参考阻抗 Z0。
  4. 点工具栏「运行仿真」，右侧切换「直角坐标图」「史密斯圆图」「原理图」「数据表」查看结果。
  5. 「文件 → 导出 Touchstone」可导出 .sNp，供其他仿真器/测试仪器使用。

二、设计工具
  * 滤波器向导：输入阶数、截止频率、纹波，自动生成 LC 梯形网络。
  * 传输线计算器：微带 / 带状线 / 同轴，Z0 ↔ 尺寸双向，给 λ/4 与电长度。
  * 反向计算：给目标频率反求 L/C；给现有 L/C 求改频要换哪个元件；
    给源/负载阻抗求 L 型匹配网络；由 S11 反求输入阻抗与所需的串/并电抗。

三、AI 辅助设计（v1.3）
  「AI 助手」页签可以自然语言下指令，例如"设计 3 阶 2.4GHz 低通"、"50Ω 微带线 FR4 1.6mm"、
  "匹配 50 到 100"、"改频到 2.5GHz"、"分析当前结果"。
  模型可在「帮助 → AI 设置」里自定义：接口地址、模型名、密钥、温度、超时；
  支持任何 OpenAI 兼容接口（本地 Ollama/LM Studio 也可）。密钥只存在本机。
  模型的建议不会直接改电路，会先列出「待应用的建议」，点「应用」才生效。
  未配置模型时使用本地规则引擎，同样能完成上述常用操作。

四、原理图
  「原理图」页签按当前网表自动布局画电路图：串联元件画在连线上、并联元件向下接地，
  并标出编号与数值。修改元件或运行仿真后自动重画。

四、模型说明
  * 理想传输线：Y 参数模型，可设损耗 dB/m。
  * 微带线：准静态模型 + 一阶色散；损耗为用户输入的常数。
  * 同轴线：TEM 精确解析式。
  * 元件按集总/准静态处理，不含封装寄生、版图耦合与多模效应。

五、结果指标
  * 直角坐标图：幅度(dB) / 驻波比 / 群时延三种测量可切换。
  * 史密斯圆图：反射系数轨迹与频点标注。
  * 数据表：每个频点的幅度与相位，可复制到表格软件。

六、免责声明
  本软件为独立实现的工程计算工具，不包含任何商业软件的代码或数据。
  仿真结果仅供设计参考，量产前请用全波仿真与实测验证。
"""


class HelpDialog(ModalDialog):
    def __init__(self, master, title="使用说明", text=HELP_TEXT):
        super().__init__(master, title, 720, 620)
        self.resizable(True, True)
        txt = tk.Text(self, wrap="word", font=FONT_S, padx=12, pady=10)
        txt.pack(fill="both", expand=True, padx=8, pady=8)
        txt.insert("1.0", text)
        txt.configure(state="disabled")
        self.buttons("关闭")


class AboutDialog(ModalDialog):
    def __init__(self, master, version="1.3.0"):
        super().__init__(master, "关于", 540, 360)
        f = ttk.Frame(self, padding=18)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="OpenRF Studio", font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w")
        ttk.Label(f, text="射频工作台", font=("Microsoft YaHei UI", 11)).pack(anchor="w", pady=(0, 10))
        msg = (f"版本 {version}\n"
               "独立实现的射频/微波电路分析与综合工具。\n\n"
               "· 节点导纳法 S 参数引擎（任意端口数）\n"
               "· 集总元件 / 理想传输线 / 微带线 / 同轴线\n"
               "· 切比雪夫、巴特沃斯低通与带通综合\n"
               "· 反向计算：LC 反求、改频微调、L 型匹配、S11 反算\n"
               "· AI 辅助设计（可自定义 OpenAI 兼容模型，未配置时本地规则）\n"
               "· 直角坐标图、史密斯圆图、自动原理图、Touchstone 读写\n\n"
               "数学与公式均来自公开教材与标准，不含任何商业软件代码。")
        ttk.Label(f, text=msg, justify="left", font=FONT_S).pack(anchor="w")
        self.buttons("关闭")