
# -*- coding: utf-8 -*-
"""导入完整性测试：所有模块都能导入，主窗口能构建，且没有重复 import。"""
from __future__ import annotations

import importlib
import os
import re
import sys

_ok = [0]
_fail = [0]


def check(name, cond, detail=""):
    if cond:
        _ok[0] += 1
        print("  [OK]   %-40s %s" % (name, detail))
    else:
        _fail[0] += 1
        print("  [FAIL] %-40s %s" % (name, detail))


def app_modules():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base = os.path.join(root, "app")
    out = []
    for d, dirs, fs in os.walk(base):
        dirs[:] = [x for x in dirs if x != "__pycache__"]
        for n in fs:
            if n.endswith(".py"):
                p = os.path.join(d, n)
                rel = os.path.relpath(p, root).replace("\\", "/")[:-3]
                out.append((rel.replace("/", "."), p))
    return sorted(out)


def main():
    mods = app_modules()
    bad = []
    for name, path in mods:
        try:
            importlib.import_module(name)
        except Exception as exc:
            bad.append((name, type(exc).__name__, str(exc)[:80]))
    check("所有模块可导入", not bad, "%d 个模块" % len(mods))
    for b in bad:
        print("        失败：%s %s %s" % b)

    # 重复 import（同一个 from X import ... 出现多次）
    dups = []
    for name, path in mods:
        with open(path, encoding="utf-8") as f:
            head = f.read().splitlines()[:60]
        seen = {}
        for i, line in enumerate(head):
            s = line.strip()
            m = re.match(r"from\s+([\w.]+)\s+import\s+(.+)$", s)
            if not m:
                continue
            mod = m.group(1)
            names = tuple(sorted(x.strip() for x in m.group(2).split(",")))
            key = (mod, names)
            if key in seen:
                dups.append("%s:%d 重复 import from %s import %s"
                            % (name, i + 1, mod, ", ".join(names)))
            seen[key] = i
    check("没有重复的 import 行", not dups, "%d 处" % len(dups))
    for d in dups[:8]:
        print("        " + d)

    # 主窗口能构建
    try:
        import tkinter as tk
        from app.ui.app import App
        app = App()
        app.withdraw()
        app.update()
        tabs = len(app.nb.tabs())
        check("主窗口可构建", tabs >= 6, "%d 个页签" % tabs)
        check("AI 面板已挂载", str(app.ai_panel) in app.nb.tabs())
        app.destroy()
    except Exception as exc:
        check("主窗口可构建", False, "%s: %s" % (type(exc).__name__, exc))

    print()
    if _fail[0]:
        print("导入完整性测试失败 %d 项 ✗" % _fail[0])
        return 1
    print("导入完整性测试全部通过 ✔（%d 项）" % _ok[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
