# -*- coding: utf-8 -*-
"""单位测试：所有含频率输入的对话框都默认 MHz，且单位可选可换算。"""
from __future__ import annotations

import sys


def main():
    import tkinter as tk
    from app.ui.dialogs import FilterWizard, TransmissionLineDialog, InverseDialog
    from app.ui.match_dialog import MatchDialog
    from app.ui.line_dialog import LineImpedanceDialog

    ok = [0]
    bad = []
    def check(name, cond, detail=""):
        if cond:
            ok[0] += 1
            print("  [OK]   %-36s %s" % (name, detail))
        else:
            bad.append(name)
            print("  [FAIL] %-36s %s" % (name, detail))

    root = tk.Tk()
    root.withdraw()

    w = FilterWizard(root)
    check("滤波器向导默认 MHz", w.var_funit.get() == "MHz", w.var_funit.get())
    w.var_n.set("3")
    w._ok()
    check("3000 MHz = 3 GHz（保持 MHz 显示）",
          "3000 MHz" in w.result["desc"], w.result["desc"])

    t = TransmissionLineDialog(root)
    check("传输线计算器默认 MHz", t.u_freq.get() == "MHz", t.u_freq.get())

    inv = InverseDialog(root)
    check("反向计算默认 MHz", inv.var_funit.get() == "MHz", inv.var_funit.get())
    inv.calc_lc()
    check("LC 谐振按 MHz 读入", "2400 MHz" in inv.out.get("1.0", "end"),
          inv.out.get("2.0", "2.end").strip())

    m = MatchDialog(root, None)
    check("匹配计算器默认 MHz", m.var_funit.get() == "MHz", m.var_funit.get())

    l = LineImpedanceDialog(root)
    check("线阻抗默认 MHz", l.v_funit.get() == "MHz", l.v_funit.get())

    root.destroy()
    print()
    if bad:
        print("单位测试失败 %d 项 ✗" % len(bad))
        return 1
    print("单位测试全部通过 ✔（%d 项）" % ok[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
