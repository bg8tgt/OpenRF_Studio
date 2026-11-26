"""匹配对话框与 Smith 图交互测试（无显示器环境下用 withdraw + update）。"""
from __future__ import annotations

import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAIL = []


def check(name, cond, detail=""):
    print(("  [OK]   " if cond else "  [FAIL] ") + name + ("   " + detail if detail else ""))
    if not cond:
        FAIL.append(name)


class Ev:
    def __init__(self, x, y):
        self.x, self.y = x, y


def main():
    from app.ui.app import App
    from app.ui.match_dialog import MatchDialog

    print("== 匹配对话框（并联短路枝节 → 应用到电路）")
    app = App(); app.withdraw()
    try:
        for _ in range(10):
            app.update(); time.sleep(0.05)
            if app.result is not None:
                break
        dlg = MatchDialog(app, app)
        dlg.withdraw()
        dlg.var_funit.set("GHz")
        dlg.var_r.set("100"); dlg.var_x.set("0"); dlg.var_f.set("2.4")
        dlg.var_z0.set("50"); dlg.var_mode.set("并联枝节（短路）")
        dlg.compute()
        check("计算输出含线长", "线长" in dlg.out.get("1.0", "end"))
        dlg.apply()
        nets = app.project.network
        check("应用中生成网络", len(nets.components) >= 4, str(len(nets.components)))
        s11 = nets.s_matrix(2.4e9)[0][0]
        check("回代 |S11| < -80 dB", abs(s11) < 1e-4, f"{20*math.log10(abs(s11)+1e-30):.1f} dB")
        if dlg.winfo_exists():
            dlg.destroy()
    finally:
        app.destroy()


    print("== 合并后的 Smith 页签 + 拖拽实时联动")
    app = App(); app.withdraw()
    try:
        for _ in range(10):
            app.update(); time.sleep(0.05)
            if app.result is not None:
                break
        texts = [app.nb.tab(i, "text").strip() for i in range(app.nb.index("end"))]
        # v2.8.0：圆图与直角图同页左右分栏，不再各自占一个页签
        dual_tabs = [x for x in texts if "圆图" in x]
        check("只有一个圆图/直角图页签", len(dual_tabs) == 1, str(dual_tabs))
        kids = [str(w) for w in app.dual_pane.winfo_children()]
        check("两图同页左右分栏",
              str(app.mag) in kids and str(app.smith_tool) in kids
              and str(app.dual_pane.cget("orient")) == "horizontal", str(kids))
        tool = app.smith_tool
        check("页签即工具页", app.smith is tool)
        check("默认开实时联动", bool(tool.var_live.get()))

        g = complex(0.2, 0.3)
        n_before = len(app.project.network.components)
        tool.var_f.set("2400"); tool.var_z0.set("50")
        tool._on_point(g)
        for _ in range(6):
            app.update(); time.sleep(0.05)
        zl = 50 * (1 + g) / (1 - g)
        check("拖拽后负载已更新",
              abs(float(tool.var_rl.get()) - zl.real) < 1e-3
              and abs(float(tool.var_xl.get()) - zl.imag) < 1e-3,
              f"RL={tool.var_rl.get()} XL={tool.var_xl.get()}")
        ids = [c.cid for c in app.project.network.components]
        check("电路已按拖拽重建", "LD_R" in ids and "LD_X" in ids, str(ids))
        check("已自动仿真", app.result is not None)
        mid = len(app.result.freqs) // 2
        g_sim = app.result.s_ij(1, 1)[mid]
        check("仿真 Γ 与拖拽点一致", abs(g_sim - g) < 1e-3,
              f"{g_sim:.4f} vs {g:.4f}")

        # 关闭联动后拖拽不改电路
        tool.var_live.set(False)
        ids2 = [c.cid for c in app.project.network.components]
        tool._on_point(complex(-0.3, 0.1))
        for _ in range(4):
            app.update(); time.sleep(0.05)
        ids3 = [c.cid for c in app.project.network.components]
        check("关闭联动后不改电路", ids2 == ids3)
    finally:
        app.destroy()
    print()
    if FAIL:
        print(f"失败 {len(FAIL)} 项：" + ", ".join(FAIL)); return 1
    print("匹配/交互测试全部通过 ✔"); return 0


if __name__ == "__main__":
    raise SystemExit(main())