"""线阻抗（Line Impedance）计算面板：由 Z0、ZL、线长求输入阻抗与指标。"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .. import rfmath as R
from .dialogs import ModalDialog, FONT_S


class LineImpedanceDialog(ModalDialog):
    def __init__(self, master):
        super().__init__(master, "线阻抗计算", 560, 460)
        box = ttk.Frame(self, padding=12)
        box.pack(fill="both", expand=True)
        self.v_z0 = tk.StringVar(value="50")
        self.v_rl = tk.StringVar(value="25")
        self.v_xl = tk.StringVar(value="25")
        self.v_d = tk.StringVar(value="0.125")
        self.v_f = tk.StringVar(value="1000")
        self.v_funit = tk.StringVar(value="MHz")
        self.v_vf = tk.StringVar(value="1.0")
        rows = (("特性阻抗 Z0 (Ω)", self.v_z0), ("负载电阻 RL (Ω)", self.v_rl),
                ("负载电抗 XL (Ω)", self.v_xl), ("线长 d (λ)", self.v_d),
                ("频率", self.v_f), ("速度因子 VF", self.v_vf))
        for i, (text, var) in enumerate(rows):
            ttk.Label(box, text=text).grid(row=i, column=0, sticky="w", pady=2)
            ttk.Entry(box, textvariable=var, width=14).grid(row=i, column=1, sticky="w", padx=6)
        ttk.Combobox(box, textvariable=self.v_funit,
                     values=["Hz", "kHz", "MHz", "GHz"], state="readonly",
                     width=6).grid(row=4, column=2, sticky="w", padx=(2, 0))
        ttk.Button(box, text="计算", command=self.compute).grid(
            row=len(rows), column=1, sticky="w", pady=8)
        self.out = tk.Text(box, height=10, font=FONT_S, wrap="word",
                           relief="solid", borderwidth=1)
        self.out.grid(row=len(rows) + 1, column=0, columnspan=2, sticky="nsew")
        box.rowconfigure(len(rows) + 1, weight=1)
        self.out.insert("1.0", "输入 Z0/ZL/线长后点「计算」。\n")
        self.buttons("关闭")

    def compute(self):
        try:
            z0 = float(self.v_z0.get())
            zl = complex(float(self.v_rl.get()), float(self.v_xl.get()))
            d = float(self.v_d.get())
            f_hz = float(self.v_f.get()) * {"Hz": 1.0, "kHz": 1e3,
                                            "MHz": 1e6, "GHz": 1e9}[self.v_funit.get()]
            vf = float(self.v_vf.get())
        except ValueError:
            messagebox.showwarning("参数有误", "请输入数字", parent=self)
            return
        if z0 <= 0 or f_hz <= 0 or vf <= 0:
            messagebox.showwarning("参数有误", "Z0/频率/速度因子必须 > 0", parent=self)
            return
        line = R.Line(z0, zl, d)
        zin = line.zin
        lam = R.wavelength_m(f_hz, vf)
        plen = R.physical_length_m(d, f_hz, vf)
        text = [f"负载 ZL = {R.fmt_complex(zl, 4)} Ω",
                f"输入 Zin = {R.fmt_complex(zin, 4)} Ω",
                f"归一化 zin = {R.fmt_complex(zin / z0, 4)}",
                f"VSWR(负载) = {R.fmt_vswr(line.vswr)}",
                f"回波损耗 = {line.return_loss:.2f} dB",
                f"失配损耗 = {line.mismatch_loss:.3f} dB",
                f"波长 λ = {lam * 1e3:.4f} mm，物理线长 = {plen * 1e3:.4f} mm",
                f"电长度 = {d * 360:.2f}°"]
        self.out.delete("1.0", "end")
        self.out.insert("1.0", "\n".join(text))
