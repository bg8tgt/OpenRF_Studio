"""AI 执行器：把 AI 的动作真正落到软件功能上。

覆盖的能力（全部可由 AI 调用）：
    电路：clear / add / update / delete / build_filter / set_z0 / set_analysis
    仿真：run                      → 立即按当前设置扫频
    计算器：calc（microstrip / stripline / coax / lc / retune / l_match / s11）
    界面：switch_tab（直角坐标图/史密斯圆图/原理图/数据表/日志/AI）
          open_tool（滤波器向导/传输线计算器/反向计算/关于/帮助）
    文件：save_project / export_touchstone
    报告：report                   → 当前仿真指标摘要

执行器只碰数据与文件，不直接操作 Tk 控件；界面提示（tab/tool）由 UI 在
主线程里读 Executor.tab_hint / tool_hint 后再执行，避免跨线程操作 Tk。
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

from .. import inverse, tline
from ..engine import SweepResult
from ..project import Project
from ..touchstone import write_touchstone
from .actions import apply_actions
from ..rfmath import fmt_vswr as _fv


class Executor:
    def __init__(self, project: Project, out_dir: Optional[str] = None):
        self.project = project
        self.result: Optional[SweepResult] = None
        self.out_dir = out_dir or os.getcwd()
        self.tab_hint: Optional[str] = None
        self.tool_hint: Optional[str] = None
        self.files: List[str] = []
        self.log: List[str] = []

    # ---------------------------------------------------------------- 执行
    def execute(self, actions: List[dict]) -> List[Dict]:
        results: List[Dict] = []
        for a in actions:
            op = a.get("op")
            try:
                if op == "run":
                    self.result = self.project.network.sweep(self.project.analysis)
                    text = self.metrics_text()
                    results.append({"op": op, "ok": True, "text": text})
                elif op == "report":
                    text = self.metrics_text() if self.result else "还没有仿真结果，先执行 run"
                    results.append({"op": op, "ok": True, "text": text})
                elif op == "calc":
                    text = self._calc(a)
                    results.append({"op": op, "ok": True, "text": text})
                elif op == "switch_tab":
                    self.tab_hint = a["tab"]
                    results.append({"op": op, "ok": True,
                                    "text": f"已切换到「{self._tab_cn(a['tab'])}」页签"})
                elif op == "open_tool":
                    self.tool_hint = a["name"]
                    results.append({"op": op, "ok": True,
                                    "text": f"已打开「{self._tool_cn(a['name'])}」"})
                elif op == "save_project":
                    path = a.get("path") or self.project.path or os.path.join(
                        self.out_dir, (self.project.name or "工程") + ".json")
                    self.project.save(path)
                    self.files.append(path)
                    results.append({"op": op, "ok": True, "text": f"已保存工程：{path}"})
                elif op == "export_touchstone":
                    if not self.result:
                        self.result = self.project.network.sweep(self.project.analysis)
                    n = self.result.n_ports()
                    path = a.get("path") or os.path.join(
                        self.out_dir, (self.project.name or "工程") + f".s{n}p")
                    write_touchstone(path, self.result.freqs, self.result.s,
                                     self.result.z0, comment=self.project.name)
                    self.files.append(path)
                    results.append({"op": op, "ok": True,
                                    "text": f"已导出 Touchstone（{n} 端口）：{path}"})
                else:
                    rep = apply_actions(self.project, [a])
                    results.append({"op": op, "ok": True,
                                    "text": "；".join(rep) if rep else "已执行"})
            except Exception as e:  # noqa: BLE001
                results.append({"op": op, "ok": False, "text": f"执行失败：{e}"})
        for r in results:
            self.log.append(f"{r['op']}: {r['text']}")
        return results

    # ---------------------------------------------------------------- 计算器
    def _calc(self, a: Dict) -> str:
        what = a["what"]
        f = float(a.get("f_ghz", 2.4)) * 1e9
        if what == "microstrip":
            d = tline.microstrip_design(float(a.get("z0", 50)), float(a.get("h", 1.6)),
                                        float(a.get("er", 4.4)), f)
            return (f"微带线：Z0={d['z0']:.3f} Ω，W={d['w_mm']:.4f} mm，"
                    f"εeff={d['eeff']:.4f}，λ/4={d['quarter_mm']:.4f} mm")
        if what == "stripline":
            d = tline.stripline_design(float(a.get("z0", 50)), float(a.get("b", 1.6)),
                                       float(a.get("er", 4.4)),
                                       float(a.get("t", 0.0)), f)
            return (f"带状线：Z0={d['z0']:.3f} Ω，W={d['w_mm']:.4f} mm，"
                    f"λ/4={d['quarter_mm']:.4f} mm")
        if what == "coax":
            d = tline.coax_design(float(a.get("z0", 50)), float(a.get("d_in", 0.91)),
                                  float(a.get("er", 2.1)), f)
            return (f"同轴：Z0={d['z0']:.3f} Ω，外导体内径 D={d['d_out_mm']:.4f} mm，"
                    f"λ/4={d['quarter_mm']:.4f} mm")
        if what == "lc":
            r = inverse.lc_resonance(float(a["f_ghz"]) * 1e9 if a.get("f_ghz") else None,
                                     a.get("l_nh"), a.get("c_pf"))
            return (f"LC 谐振：f0={r['f_hz']/1e9:.6g} GHz，L={r['l_nh']:.6g} nH，"
                    f"C={r['c_pf']:.6g} pF（{r['note']}）")
        if what == "retune":
            r = inverse.retune_lc(float(a.get("l_nh", 1.0)), float(a.get("c_pf", 1.0)),
                                  float(a["target_ghz"]) * 1e9, a.get("keep", "L"))
            return (f"改频：{r['f_now_hz']/1e9:.4g}→{r['f_target_hz']/1e9:.4g} GHz，"
                    f"新 L={r['l_nh']:.4g} nH，新 C={r['c_pf']:.4g} pF（{r['note']}）")
        if what == "l_match":
            m = inverse.l_network_match(float(a.get("rs", 50)), float(a.get("rl", 100)), f)
            if m.get("identity"):
                return "L 型匹配：源与负载相同，无需匹配"
            lines = [f"L 型匹配：Q={m['q']:.4f}，并联件接 {m['shunt_side']} 侧"]
            for i, s in enumerate(m["solutions"], 1):
                lines.append(f"  方案{i}：{s['shunt']['element']} "
                             f"{s['shunt']['value']:.4g} {s['shunt']['unit']}，"
                             f"{s['series']['element']} "
                             f"{s['series']['value']:.4g} {s['series']['unit']}")
            return "\n".join(lines)
        if what == "s11":
            import cmath
            g = cmath.rect(float(a.get("mag", 0.3)),
                           float(a.get("phase_deg", 0.0)) * 3.141592653589793 / 180.0)
            r = inverse.match_from_s11(g, f)
            parts = [f"S11 反算：Zin={r['zin'].real:.4f}{r['zin'].imag:+.4f}j Ω，"
                     f"VSWR={_fv(r['vswr'])}"]
            if r["series"]:
                parts.append(f"  串联：{r['series']['element']} "
                             f"{r['series']['value']:.4g} {r['series']['unit']}")
            if r["shunt"]:
                parts.append(f"  并联：{r['shunt']['element']} "
                             f"{r['shunt']['value']:.4g} {r['shunt']['unit']}")
            parts.extend("  · " + n for n in r["notes"])
            return "\n".join(parts)
        return f"未知计算类型：{what}"

    # ---------------------------------------------------------------- 指标
    def metrics_text(self) -> str:
        r = self.result
        if not r or not r.freqs:
            return "暂无仿真结果"
        mid = len(r.freqs) // 2
        n = r.n_ports()
        parts = [f"{len(r.freqs)} 点，{r.freqs[0]/1e9:g}–{r.freqs[-1]/1e9:g} GHz，"
                 f"{n} 端口，Z0={r.z0:g} Ω",
                 f"中频 {r.freqs[mid]/1e9:g} GHz：|S11|={r.db(1, 1)[mid]:.2f} dB"]
        if n >= 2:
            s21 = r.db(2, 1)
            parts.append(f"|S21|={s21[mid]:.2f} dB（范围 {min(s21):.2f}～{max(s21):.2f} dB）")
        parts.append(f"全带最差 |S11|={max(r.db(1, 1)):.2f} dB")
        return "；".join(parts)

    @staticmethod
    def _tab_cn(tab: str) -> str:
        return {"plot": "直角坐标图", "smith": "史密斯圆图",
                "smith_tool": "Smith 工具", "schematic": "原理图",
                "table": "数据表", "log": "日志", "ai": "AI 助手"}.get(tab, tab)

    @staticmethod
    def _tool_cn(name: str) -> str:
        return {"filter_wizard": "滤波器向导", "tline": "传输线计算器",
                "inverse": "反向计算", "smith_tool": "Smith 工具",
                "about": "关于", "help": "使用说明"}.get(name, name)
