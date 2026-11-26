"""匹配计算器：单枝节（并联/串联，开路/短路）与 L 型匹配。

计算用 app/matching.py 与 app/inverse.py；「应用到电路」会构建
「端口—传输线—负载 + 枝节」的网络并重新仿真。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import inverse, matching
from ..components import Component
from ..engine import Network, Port
from .dialogs import ModalDialog, FONT_S

MODES = ["并联枝节（短路）", "并联枝节（开路）",
         "串联枝节（短路）", "串联枝节（开路）",
         "双枝节（并联，间距 λ/8）", "L 型匹配（低通）"]


class MatchDialog(ModalDialog):
    def __init__(self, master, app):
        super().__init__(master, "匹配计算器", 720, 620)
        self.app = app
        self.resizable(True, True)
        box = ttk.Frame(self, padding=12)
        box.pack(fill="both", expand=True)

        self.var_r = tk.StringVar(value="100")
        self.var_x = tk.StringVar(value="0")
        self.var_f = tk.StringVar(value="10000")
        self.var_funit = tk.StringVar(value="MHz")
        self.var_z0 = tk.StringVar(value="50")
        self.var_mode = tk.StringVar(value=MODES[0])

        rows = [("负载实部 R（Ω）", self.var_r), ("负载虚部 X（Ω）", self.var_x),
                ("频率", self.var_f), ("参考阻抗 Z0（Ω）", self.var_z0)]
        for i, (label, var) in enumerate(rows):
            ttk.Label(box, text=label).grid(row=i, column=0, sticky="w", pady=3)
            ttk.Entry(box, textvariable=var, width=14).grid(row=i, column=1, sticky="w", padx=6)
        ttk.Combobox(box, textvariable=self.var_funit,
                     values=["Hz", "kHz", "MHz", "GHz"], state="readonly",
                     width=6).grid(row=2, column=2, sticky="w", padx=(2, 0))

        ttk.Label(box, text="匹配方式").grid(row=4, column=0, sticky="w", pady=3)
        ttk.Combobox(box, textvariable=self.var_mode, state="readonly",
                     values=MODES, width=24).grid(row=4, column=1, sticky="w", padx=6)

        bar = ttk.Frame(box)
        bar.grid(row=5, column=0, columnspan=2, sticky="w", pady=8)
        ttk.Button(bar, text="计算", command=self.compute).pack(side="left", padx=3)
        ttk.Button(bar, text="应用到电路", command=self.apply).pack(side="left", padx=3)
        ttk.Button(bar, text="复制结果", command=self.copy).pack(side="left", padx=3)

        self.out = tk.Text(box, height=16, font=FONT_S, wrap="word",
                           relief="solid", borderwidth=1)
        self.out.grid(row=6, column=0, columnspan=2, sticky="nsew")
        box.rowconfigure(6, weight=1)
        box.columnconfigure(1, weight=1)
        self.out.insert("1.0", "填负载 ZL = R + jX、频率与 Z0，选匹配方式后点「计算」。\n"
                               "「应用到电路」会生成对应网络并自动仿真。\n")
        self.last = None
        self.buttons("关闭")

    # ------------------------------------------------------------------
    def _values(self):
        r = float(self.var_r.get())
        x = float(self.var_x.get())
        f = float(self.var_f.get()) * {"Hz": 1.0, "kHz": 1e3, "MHz": 1e6, "GHz": 1e9}[self.var_funit.get()]
        z0 = float(self.var_z0.get())
        if f <= 0 or z0 <= 0:
            raise ValueError("频率与 Z0 必须为正")
        return complex(r, x), f, z0

    def compute(self):
        try:
            zl, f, z0 = self._values()
            mode = self.var_mode.get()
            if mode.startswith("双枝节"):
                s = matching.double_stub(zl, z0, f, spacing_lambda=0.125,
                                         prefer="short")
                lines = [f"双枝节匹配：ZL = {zl.real:g}{zl.imag:+g}j Ω，"
                         f"间距 = λ/8 = {s['d12_mm']:.4f} mm",
                         f"  负载到枝节1：{s['d1_mm']:.4f} mm（{s['d1_lambda']:.4f}λ）",
                         f"  枝节1 = {s['stub1_mm']:.4f} mm（短路），B1={s['b1']:+.4f}",
                         f"  枝节2 = {s['stub2_mm']:.4f} mm（短路），B2={s['b2']:+.4f}"]
                self.last = ("double", (s, zl, f, z0))
                self._say("\n".join(lines))
                return

            if mode.startswith("L 型"):
                m = inverse.l_network_match(z0, zl.real if abs(zl.imag) < 1e-9 else abs(zl),
                                            f)
                if m.get("identity"):
                    self._say("源与负载相同，无需匹配。")
                    return
                lines = [f"L 型匹配：Rs={z0:g} Ω → Rl={zl.real:g} Ω，Q={m['q']:.4f}",
                         f"  {m['note']}"]
                for i, s in enumerate(m["solutions"], 1):
                    lines.append(f"  方案{i}：{s['shunt']['element']} "
                                 f"{s['shunt']['value']:.4g} {s['shunt']['unit']}，"
                                 f"{s['series']['element']} "
                                 f"{s['series']['value']:.4g} {s['series']['unit']}")
                self.last = ("L", m)
                self._say("\n".join(lines))
                return

            prefer = "short" if "短路" in mode else "open"
            if mode.startswith("并联"):
                s = matching.shunt_stub(zl, z0, f, prefer=prefer)
                norm = f"B = {s['b_norm']:+.4f}（归一化电纳）"
            else:
                s = matching.series_stub(zl, z0, f, prefer=prefer)
                norm = f"X = {s['x_norm']:+.4f}（归一化电抗）"
            lines = [f"枝节匹配：ZL = {zl.real:g}{zl.imag:+g}j Ω，f = {f/1e9:g} GHz",
                     f"  线长 d = {s['d_mm']:.4f} mm（{s['d_deg']:.2f}°）",
                     f"  枝节 = {s['stub_mm']:.4f} mm（{'短路' if prefer == 'short' else '开路'}）",
                     f"  {norm}"]
            alt = s.get("alternatives") or []
            for i, a in enumerate(alt[:2], 1):
                lines.append(f"  备选{i}：d={a['d_mm']:.4f} mm，"
                             f"枝节={a['stub_short_mm'] if prefer == 'short' else a['stub_open_mm']:.4f} mm")
            self.last = ("stub", (mode, s, zl, f, z0))
            self._say("\n".join(lines))
        except Exception as e:  # noqa: BLE001
            self._say(f"错误：{e}")

    def _say(self, text: str):
        self.out.delete("1.0", "end")
        self.out.insert("1.0", text)

    def copy(self):
        txt = self.out.get("1.0", "end").strip()
        try:
            self.clipboard_clear()
            self.clipboard_append(txt)
        except tk.TclError:
            pass

    def apply(self):
        if not self.last:
            self.compute()
        if not self.last:
            return
        try:
            if self.last[0] == "double":
                s, zl2, f2, z02 = self.last[1]
                net = self._build_double(s, zl2, f2, z02)
                desc = "双枝节匹配网络"
                self._f = f2
            elif self.last[0] == "L":
                net = self._build_l(self.last[1])
                desc = "L 型匹配网络"
            else:
                mode, s, zl, f, z0 = self.last[1]
                net = self._build_stub(mode, s, zl, f, z0)
                desc = "枝节匹配网络"
            self.app.project.network = net
            ana = self.app.project.analysis
            f = getattr(self, "_f", 2.4e9)
            ana.start_ghz = max(f / 1e9 * 0.5, 1e-6)
            ana.stop_ghz = f / 1e9 * 1.5
            ana.points = max(401, ana.points)
            self.app.say(f"已应用{desc}（{len(net.components)} 个元件）")
            for fn in ("_refresh_tree", "_refresh_ports", "_refresh_schematic"):
                try:
                    getattr(self.app, fn)()
                except Exception:
                    pass
            try:
                self.app.run_sim()
            except Exception as e:  # noqa: BLE001
                self.app.say(f"仿真失败：{e}")
            self.destroy()
        except Exception as e:  # noqa: BLE001
            self._say(f"应用失败：{e}")

    # ------------------------------------------------------------------
    def _build_stub(self, mode, s, zl, f, z0):
        net = Network(z0)
        d = s["d_mm"]
        stub = s["stub_mm"]
        net.add(Component("TL1", "TL", ["p", "a"], {"z0": z0, "er": 1.0, "len": d}))
        # 负载：串联 R + L/C
        if abs(zl.imag) >= 0:
            L = zl.imag / (2 * 3.141592653589793 * f) * 1e9
            net.add(Component("RL", "R", ["a", "b"], {"r": max(zl.real, 1e-6)}))
            net.add(Component("XL", "L", ["b", "0"], {"l": max(L, 1e-6)}))
        else:
            C = 1 / (2 * 3.141592653589793 * f * abs(zl.imag)) * 1e12
            net.add(Component("RL", "R", ["a", "b"], {"r": max(zl.real, 1e-6)}))
            net.add(Component("XC", "C", ["b", "0"], {"c": max(C, 1e-6)}))
        if mode.startswith("并联"):
            net.add(Component("STUB", "TL", ["p", "0"], {"z0": z0, "er": 1.0, "len": stub}))
            net.ports = [Port("P1", "p", z0)]
        else:
            # 串联枝节：端口 → 枝节线 → 节点 s，s 短路到地，再串主线到负载
            net.add(Component("STUB", "TL", ["p", "s"], {"z0": z0, "er": 1.0, "len": stub}))
            net.add(Component("SHRT", "R", ["s", "0"], {"r": 1e-6}))
            net.add(Component("TL0", "TL", ["p", "a2"], {"z0": z0, "er": 1.0, "len": d}))
            net.add(Component("RL2", "R", ["a2", "b2"], {"r": max(zl.real, 1e-6)}))
            if zl.imag >= 0:
                net.add(Component("X2", "L", ["b2", "0"],
                                  {"l": max(zl.imag / (2 * 3.141592653589793 * f) * 1e9, 1e-6)}))
            else:
                net.add(Component("X2", "C", ["b2", "0"],
                                  {"c": 1 / (2 * 3.141592653589793 * f * abs(zl.imag)) * 1e12}))
            net.ports = [Port("P1", "p", z0)]
        self._f = f
        return net

    def _build_double(self, s, zl, f, z0):
        net = Network(z0)
        net.add(Component("TL2", "TL", ["p", "A"],
                          {"z0": z0, "er": 1.0, "len": s["d12_mm"]}))
        net.add(Component("ST2", "TL", ["p", "0"],
                          {"z0": z0, "er": 1.0, "len": s["stub2_mm"]}))
        net.add(Component("TL1", "TL", ["A", "L"],
                          {"z0": z0, "er": 1.0, "len": s["d1_mm"]}))
        net.add(Component("ST1", "TL", ["A", "0"],
                          {"z0": z0, "er": 1.0, "len": s["stub1_mm"]}))
        net.add(Component("LD_R", "R", ["L", "b"], {"r": max(zl.real, 1e-6)}))
        if zl.imag >= 0:
            net.add(Component("LD_X", "L", ["b", "0"],
                              {"l": max(zl.imag / (2 * 3.141592653589793 * f) * 1e9, 1e-6)}))
        else:
            net.add(Component("LD_X", "C", ["b", "0"],
                              {"c": 1 / (2 * 3.141592653589793 * f * abs(zl.imag)) * 1e12}))
        net.ports = [Port("P1", "p", z0)]
        self._f = f
        return net

    def _build_l(self, m):
        z0 = float(self.var_z0.get())
        f = float(self.var_f.get()) * {"Hz": 1.0, "kHz": 1e3, "MHz": 1e6, "GHz": 1e9}[self.var_funit.get()]
        sol = m["solutions"][0]
        net = Network(z0)
        lk = lambda e: "l" if e["kind"] == "L" else "c"
        net.add(Component("XS", sol["series"]["kind"], ["p", "a"],
                          {lk(sol["series"]): sol["series"]["value"]}))
        if m["shunt_side"] == "load":
            net.add(Component("XP", sol["shunt"]["kind"], ["a", "0"],
                              {lk(sol["shunt"]): sol["shunt"]["value"]}))
            net.add(Component("RL", "R", ["a", "0"], {"r": m["r_high"]}))
        else:
            net.add(Component("XP", sol["shunt"]["kind"], ["p", "0"],
                              {lk(sol["shunt"]): sol["shunt"]["value"]}))
            net.add(Component("RL", "R", ["a", "0"], {"r": m["r_low"]}))
        net.ports = [Port("P1", "p", z0)]
        self._f = f
        return net