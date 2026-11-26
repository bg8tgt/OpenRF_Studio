# -*- coding: utf-8 -*-
"""PyInstaller 打包入口（与 run.py 等价，供 exe 构建使用）。"""
import os
import sys

if getattr(sys, "frozen", False):
    base = sys._MEIPASS  # type: ignore[attr-defined]
else:
    base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)


def _ensure_streams() -> None:
    """窗口程序打包后 sys.stdout / sys.stderr 是 None。

    此时任何 print() 或异常回溯都会抛 AttributeError，把 Tk 的事件循环
    带崩——表现就是"点了按钮没反应、界面卡死"。这里把它们接到日志文件。
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    log_dir = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                           "OpenRF_Studio")
    try:
        os.makedirs(log_dir, exist_ok=True)
        f = open(os.path.join(log_dir, "runtime.log"), "a", encoding="utf-8", buffering=1)
    except Exception:
        return
    if sys.stdout is None:
        sys.stdout = f
    if sys.stderr is None:
        sys.stderr = f


_ensure_streams()

from app.ui.app import main, selftest

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    main()
