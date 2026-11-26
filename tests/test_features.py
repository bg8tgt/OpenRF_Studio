"""新功能测试：归一化、线阻抗、回损曲线、增益表、CSV 导出。"""
from __future__ import annotations

import math
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAIL = []


def check(name, cond, detail=""):
    print(("  [OK]   " if cond else "  [FAIL] ") + name + ("   " + detail if detail else ""))
    if not cond:
        FAIL.append(name)


def main():
    from app import rfmath as R
    print("== 线阻抗数学")
    line = R.Line(50, 100 + 0j, 0.25)
    check("λ/4 变换 100→25 Ω", abs(line.zin - 25) < 1e-6, f"{line.zin:.4f}")
    line2 = R.Line(50, 50 + 0j, 0.3)
    check("50 Ω 负载沿线不变", abs(line2.zin - 50) < 1e-6, f"{line2.zin:.4f}")

    from app.ui.app import App
    from app.ui.line_dialog import LineImpedanceDialog
    app = App(); app.withdraw()
    try:
        for _ in range(10):
            app.update(); time.sleep(0.05)
            if app.result is not None:
                break
        print("== 归一化显示")
        tool = app.smith_tool
        tool.var_norm.set(False); tool.refresh_readouts()
        abs_zin = tool.vars["zin"].get()
        tool.var_norm.set(True); tool.refresh_readouts()
        norm_zin = tool.vars["zin"].get()
        check("归一化读数改变", abs_zin != norm_zin, f"{abs_zin} -> {norm_zin}")
        tool.var_norm.set(False); tool.refresh_readouts()

        print("== 回损曲线 / 增益表")
        check("回损图模式", app.rl_plot.mode == "rl")
        vals = app.rl_plot._values(app.result, 1, 1)
        check("回损为正 dB", vals and vals[0] > 0, f"{vals[0]:.2f}")
        rows = app.gain_tree.get_children()
        check("增益表有行", len(rows) > 10, str(len(rows)))
        first = app.gain_tree.item(rows[0], "values")
        check("增益表列数 5", len(first) == 5, str(first))

        print("== 线阻抗对话框")
        dlg = LineImpedanceDialog(app)
        dlg.withdraw()
        dlg.v_z0.set("50"); dlg.v_rl.set("100"); dlg.v_xl.set("0")
        dlg.v_d.set("0.25"); dlg.v_f.set("1000"); dlg.v_vf.set("1.0")
        dlg.compute()
        txt = dlg.out.get("1.0", "end")
        check("输出含输入阻抗", "输入 Zin" in txt and "25" in txt, txt.splitlines()[1] if len(txt.splitlines()) > 1 else "")
        dlg.destroy()

        print("== 动态播放（运动模式）")
        app.stop_play()
        app.var_anim.set(True)
        app.run_and_play()
        check("运行后自动播放", app.playing)
        k0 = app.play_idx
        for _ in range(3):
            app._play_tick(); app.update()
        check("播放索引前进", app.play_idx != k0, f"{k0} -> {app.play_idx}")
        check("幅度图有播放光标", getattr(app.mag, "cursor", -1) >= 0,
              str(getattr(app.mag, "cursor", -1)))
        check("圆图有播放光标", app.smith_tool.canvas.play_idx >= 0,
              str(app.smith_tool.canvas.play_idx))
        app.stop_play()
        check("停止后光标清除", app.mag.cursor == -1
              and app.smith_tool.canvas.play_idx == -1)
        check("停止后不再播放", not app.playing)

        print("== 直角坐标图鼠标定位")
        text = app.mag.mark_at_freq(3.0)
        check("定位文本含频率", ("MHz" in text or "GHz" in text or "kHz" in text) and "S11" in text, text[:60])
        idx = app.mag.pinned_idx
        check("钉住标记", idx >= 0, str(idx))
        app.mag.clear_marker()
        check("清除标记", app.mag.pinned_idx == -1)

        print("== 反算结果应用")
        from app.ui.dialogs import InverseDialog
        dlg2 = InverseDialog(app)
        dlg2.withdraw()
        dlg2.calc_match()
        dlg2.apply_last()
        for _ in range(6):
            app.update(); time.sleep(0.05)
        ids = [c.cid for c in app.project.network.components]
        check("已建匹配网络", "XS" in ids and "XP" in ids, str(ids))
        check("应用后有仿真结果", app.result is not None)
        s11 = min(app.result.db(1, 1))
        check("匹配后 |S11| 明显下降", s11 < -20, f"{s11:.2f} dB")

        print("== CSV 导出")
        import tkinter.filedialog as fd
        tmp = os.path.join(tempfile.mkdtemp(), "sweep.csv")
        orig = fd.asksaveasfilename
        fd.asksaveasfilename = lambda **kw: tmp
        try:
            app.export_csv()
        finally:
            fd.asksaveasfilename = orig
        check("CSV 已生成", os.path.exists(tmp))
        head = open(tmp, encoding="utf-8-sig").readline().strip()
        check("CSV 表头正确", head.startswith("freq_ghz,s11_db,s21_db"), head)
        n = len(open(tmp, encoding="utf-8-sig").readlines())
        check("CSV 行数与频点一致", n == len(app.result.freqs) + 1, f"{n}")

        print("== 频点级同步（直角图 -> 圆图）")
        net_before = [c.cid for c in app.project.network.components]
        calls = {"n": 0}
        orig_sim = app.run_sim

        def _counting_sim(*a, **kw):
            calls["n"] += 1
            return orig_sim(*a, **kw)

        app.run_sim = _counting_sim
        try:
            app._mag_freq_pick(3.0)
            app.update()
        finally:
            app.run_sim = orig_sim
        sf = str(app.smith_tool.var_f.get()).strip()
        check("圆图频率同步为 3000 MHz", sf == "3000", sf)
        net_after = [c.cid for c in app.project.network.components]
        check("电路元件未被改动", net_before == net_after, f"{net_before} -> {net_after}")
        check("同步不触发整体仿真", calls["n"] == 0, f"run_sim x{calls['n']}")
        check("同步后状态栏提示", "圆图同步" in app.status.get(), app.status.get())
        check("防回环标志已复位", getattr(app, "_syncing", None) is False)
    finally:
        app.destroy()

    print()
    if FAIL:
        print(f"失败 {len(FAIL)} 项：" + ", ".join(FAIL)); return 1
    print("新功能测试全部通过 ✔"); return 0


if __name__ == "__main__":
    raise SystemExit(main())