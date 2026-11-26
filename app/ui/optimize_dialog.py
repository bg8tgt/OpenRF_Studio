"""优化器对话框：把带内指标调到目标值（Nelder–Mead，线程内运行）。"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import List

from ..engine import Analysis
from ..optimize import Parameter, Spec, collect_parameters, optimize
from .dialogs import ModalDialog, FONT_S

KINDS = {
    "带内最大 |S11|（dB）": "s11",
    "带内最小 |S21|（dB）": "s21min",
    "指定频点插损 |S21|（dB）": "s21at",
}


class OptimizeDialog(ModalDialog):
    def __init__(self, master, app):
        super().__init__(master, "优化器", 720, 620)
        self.app = app
        self.best: List[Parameter] = []
        self.snapshot = {}
        self._busy = False
        box = ttk.Frame(self, padding=12)
        box.pack(fill="both", expand=True)

        self.var_kind = tk.StringVar(value=list(KINDS)[0])
        self.var_f1 = tk.StringVar(value="1")
        self.var_f2 = tk.StringVar(value="20")
        self.var_funit = tk.StringVar(value="MHz")
        self.var_target = tk.StringVar(value="-20")
        self.var_iter = tk.StringVar(value="160")

        ttk.Label(box, text="优化目标").grid(row=0, column=0, sticky="w")
        ttk.Combobox(box, textvariable=self.var_kind, state="readonly", width=28,
                     values=list(KINDS)).grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(box, text="频带").grid(row=1, column=0, sticky="w", pady=3)
        f = ttk.Frame(box)
        f.grid(row=1, column=1, sticky="w", padx=6)
        ttk.Entry(f, textvariable=self.var_f1, width=8).pack(side="left")
        ttk.Label(f, text="–").pack(side="left", padx=4)
        ttk.Entry(f, textvariable=self.var_f2, width=8).pack(side="left")
        ttk.Combobox(f, textvariable=self.var_funit, values=["Hz", "kHz", "MHz", "GHz"],
                     state="readonly", width=6).pack(side="left", padx=(6, 0))
        ttk.Label(box, text="目标值（dB）").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Entry(box, textvariable=self.var_target, width=10).grid(row=2, column=1, sticky="w", padx=6)
        ttk.Label(box, text="最大迭代").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Entry(box, textvariable=self.var_iter, width=10).grid(row=3, column=1, sticky="w", padx=6)

        ttk.Label(box, text="参与优化的参数").grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 2))
        self.lst = tk.Listbox(box, height=8, selectmode="multiple", exportselection=False,
                              font=FONT_S)
        self.lst.grid(row=5, column=0, columnspan=2, sticky="nsew")
        box.rowconfigure(5, weight=1)
        box.columnconfigure(1, weight=1)

        bar = ttk.Frame(box)
        bar.grid(row=6, column=0, columnspan=2, sticky="w", pady=8)
        ttk.Button(bar, text="开始优化", command=self.start).pack(side="left", padx=3)
        ttk.Button(bar, text="应用最优", command=self.apply).pack(side="left", padx=3)
        ttk.Button(bar, text="全选", command=lambda: self.lst.select_set(0, "end")).pack(side="left", padx=3)

        self.out = tk.Text(box, height=9, font=FONT_S, wrap="word",
                           relief="solid", borderwidth=1)
        self.out.grid(row=7, column=0, columnspan=2, sticky="nsew")
        box.rowconfigure(7, weight=1)
        self.out.insert("1.0", "参数默认全部选中；优化后点「应用最优」写回电路。\n")
        self._load_params()
        self.buttons("关闭")

    # ------------------------------------------------------------------
    def _load_params(self):
        self.params = collect_parameters(self.app.project.network)
        self.lst.delete(0, "end")
        for p in self.params:
            self.lst.insert("end", f"{p.label}  当前={p.value:.4g}  [{p.lo:.3g} ~ {p.hi:.3g}]")
        if self.params:
            self.lst.select_set(0, "end")

    def _selected(self) -> List[Parameter]:
        sel = self.lst.curselection() or range(len(self.params))
        return [self.params[i] for i in sel]

    def _spec(self) -> Spec:
        kind = KINDS[self.var_kind.get()]
        u = self.var_funit.get()
        k = {"Hz": 1.0, "kHz": 1e3, "MHz": 1e6, "GHz": 1e9}.get(u, 1e6)
        f1 = float(self.var_f1.get()) * k / 1e9
        f2 = float(self.var_f2.get()) * k / 1e9
        if kind == "s21at":
            f2 = f1 if f2 < f1 else f2
        return Spec(kind=kind, f1_ghz=min(f1, f2), f2_ghz=max(f1, f2),
                    target_db=float(self.var_target.get()))

    def _say(self, text: str):
        self.out.delete("1.0", "end")
        self.out.insert("1.0", text)

    def run_sync(self) -> dict:
        params = self._selected()
        if not params:
            return {"ok": False, "message": "没有选中参数"}
        self.snapshot = {c.cid: dict(c.params) for c in self.app.project.network.components}
        spec = self._spec()
        ana = Analysis(spec.f1_ghz, spec.f2_ghz, 201)
        res = optimize(self.app.project.network, params, spec, ana,
                       max_iter=int(self.var_iter.get()))
        # 先回滚，等用户点“应用最优”
        for c in self.app.project.network.components:
            if c.cid in self.snapshot:
                c.params = dict(self.snapshot[c.cid])
        self.best = res.params
        return {"ok": res.ok, "cost": res.cost, "metrics": res.metrics,
                "message": res.message, "history": res.history}

    def start(self):
        if self._busy:
            return
        self._busy = True
        self._say("优化中…")
        def work():
            try:
                out = self.run_sync()
                self.after(0, lambda: self._done(out))
            except Exception as e:  # noqa: BLE001
                self.after(0, lambda: self._fail(e))
        threading.Thread(target=work, daemon=True).start()

    def _done(self, out: dict):
        self._busy = False
        if not out.get("ok"):
            self._say(f"优化失败：{out.get('message')}")
            return
        m = out["metrics"]
        self._say(f"{out['message']}\n"
                  f"带内最大 |S11| = {m['s11_max_db']:.2f} dB\n"
                  f"带内最小 |S21| = {m['s21_min_db']:.2f} dB\n"
                  f"代价 = {out['cost']:.3f}（越小越好）\n"
                  f"点「应用最优」写回电路并重新仿真。")

    def _fail(self, e: Exception):
        self._busy = False
        self._say(f"出错：{e}")

    def apply(self):
        if not self.best:
            messagebox.showinfo("提示", "请先运行优化。", parent=self)
            return
        by_id = {c.cid: c for c in self.app.project.network.components}
        for p in self.best:
            c = by_id.get(p.cid)
            if c is not None:
                c.params[p.key] = float(p.value)
        for fn in ("_refresh_tree", "_refresh_ports", "_refresh_schematic"):
            try:
                getattr(self.app, fn)()
            except Exception:
                pass
        try:
            self.app.run_sim()
        except Exception as e:  # noqa: BLE001
            self.app.say(f"仿真失败：{e}")
        self.app.say("已应用优化结果")
        self.destroy()
