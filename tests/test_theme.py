"""主题与合并界面的完整性测试。"""
from __future__ import annotations

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
    from app.ui import theme
    from app.ui.app import App
    print("== 主题")
    app = App(); app.withdraw()
    try:
        for _ in range(10):
            app.update(); time.sleep(0.05)
        light_bg = theme.palette()["canvas"]
        app._apply_theme("dark")
        for _ in range(4):
            app.update(); time.sleep(0.05)
        dark = theme.palette()
        check("切到深色", theme.current_name() == "dark")
        check("配色变化", dark["canvas"] != light_bg, f"{light_bg} -> {dark['canvas']}")
        check("窗口题目深色", theme.current_name() == "dark")
        check("圆图画布深色", app.smith_tool.canvas.cget("background") == dark["canvas"],
              str(app.smith_tool.canvas.cget("background")))
        app._apply_theme("light")
        check("切回浅色", theme.current_name() == "light")
        # 只有 6 个页签且包含合并后的圆图
        texts = [app.nb.tab(i, "text").strip() for i in range(app.nb.index("end"))]
        check("页签 7 个", len(texts) == 7, str(texts))
        check("含圆图/直角图合并页",
              any("圆图" in x and "直角" in x for x in texts), str(texts))
        check("含回损曲线/增益表", "回损曲线" in texts and "增益表" in texts, str(texts))
        check("无重复 Smith 页", len([x for x in texts if "Smith" in x]) <= 0, str(texts))
        # Q 圆开关
        before = len(app.smith_tool.canvas.find_all())
        app.smith_tool.opt_vars["q"].set(True)
        app.smith_tool._apply_opts()
        app.update()
        after = len(app.smith_tool.canvas.find_all())
        check("Q 圆可打开", after > before, f"{before} -> {after}")
        app.smith_tool.opt_vars["q"].set(False)
        app.smith_tool._apply_opts()
        # 拖拽联动仍可用
        app.smith_tool.var_live.set(True)
        app.smith_tool.var_f.set("2400")
        app.smith_tool._on_point(complex(0.2, 0.3))
        for _ in range(6):
            app.update(); time.sleep(0.05)
        ids = [c.cid for c in app.project.network.components]
        check("拖拽重建电路", "LD_R" in ids and "LD_X" in ids, str(ids))
    finally:
        app.destroy()
    print()
    if FAIL:
        print(f"失败 {len(FAIL)} 项：" + ", ".join(FAIL)); return 1
    print("主题/界面完整性测试通过 ✔"); return 0


if __name__ == "__main__":
    raise SystemExit(main())