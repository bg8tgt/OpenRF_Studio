"""优化器测试：指标改善、边界、对话框应用。"""
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


def main():
    from app.engine import Analysis
    from app.optimize import Spec, collect_parameters, measure, optimize
    from app.project import new_demo_project

    print("== 优化器（低通带内匹配）")
    proj = new_demo_project()
    net = proj.network
    spec = Spec(kind="s11", f1_ghz=0.001, f2_ghz=0.02, target_db=-20)
    ana = Analysis(0.001, 0.02, 201)
    before = measure(net, spec, ana)["s11_max_db"]
    params = collect_parameters(net)
    res = optimize(net, params, spec, ana, max_iter=200)
    after = res.metrics["s11_max_db"]
    check("优化成功", res.ok)
    check("指标显著改善", after < before - 10, f"{before:.1f} → {after:.1f} dB")
    check("参数在边界内",
          all(p.lo - 1e-9 <= p.value <= p.hi + 1e-9 for p in params),
          str([(p.cid, round(p.value, 3)) for p in params]))

    print("== 优化器对话框")
    from app.ui.app import App
    from app.ui.optimize_dialog import OptimizeDialog
    app = App(); app.withdraw()
    try:
        for _ in range(10):
            app.update(); time.sleep(0.05)
            if app.result is not None:
                break
        dlg = OptimizeDialog(app, app)
        dlg.withdraw()
        dlg.var_kind.set("带内最大 |S11|（dB）")
        dlg.var_f1.set("0.001"); dlg.var_f2.set("0.02"); dlg.var_target.set("-25")
        dlg.var_iter.set("120")
        dlg.lst.select_set(0, "end")
        out = dlg.run_sync()
        check("对话框优化成功", out.get("ok"), str(out.get("message")))
        check("对话框给出指标", "s11_max_db" in (out.get("metrics") or {}))
        before_vals = {c.cid: dict(c.params) for c in app.project.network.components}
        dlg.apply()
        for _ in range(6):
            app.update(); time.sleep(0.05)
        after_vals = {c.cid: dict(c.params) for c in app.project.network.components}
        check("应用后参数已改变", before_vals != after_vals)
        check("应用后已重新仿真", app.result is not None)
        if dlg.winfo_exists():
            dlg.destroy()
    finally:
        app.destroy()

    print()
    if FAIL:
        print(f"失败 {len(FAIL)} 项：" + ", ".join(FAIL)); return 1
    print("优化器测试全部通过 ✔"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
