"""浅色/深色主题（界面统一配色）。

apply(root, name) 会配置 ttk 样式、窗口背景，并把配色推给绘图模块。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

LIGHT = {
    "name": "light", "bg": "#f3f4f6", "panel": "#ffffff", "fg": "#111827",
    "muted": "#6b7280", "border": "#d1d5db", "accent": "#2563eb",
    "accent_fg": "#ffffff", "canvas": "#ffffff", "grid": "#e5e7eb",
    "axis": "#9ca3af", "curve": ["#2563eb", "#dc2626", "#16a34a", "#d97706"],
    "sel": "#bfdbfe", "header": "#1f2937", "header_fg": "#f9fafb",
}
DARK = {
    "name": "dark", "bg": "#0f172a", "panel": "#1e293b", "fg": "#e2e8f0",
    "muted": "#94a3b8", "border": "#334155", "accent": "#3b82f6",
    "accent_fg": "#ffffff", "canvas": "#0f172a", "grid": "#334155",
    "axis": "#64748b", "curve": ["#60a5fa", "#f87171", "#34d399", "#fbbf24"],
    "sel": "#1d4ed8", "header": "#0b1220", "header_fg": "#e2e8f0",
}

_current = LIGHT
_name = "light"


def palette(name: str | None = None) -> dict:
    global _current, _name
    if name is not None:
        _name = "dark" if str(name).lower().startswith("dark") else "light"
        _current = DARK if _name == "dark" else LIGHT
    return _current


def current_name() -> str:
    return _name


def apply(root: tk.Misc, name: str) -> dict:
    pal = palette(name)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    base = ("Microsoft YaHei UI", 9)
    style.configure(".", font=base, background=pal["bg"], foreground=pal["fg"])
    style.configure("TFrame", background=pal["bg"])
    style.configure("TLabel", background=pal["bg"], foreground=pal["fg"])
    style.configure("Muted.TLabel", foreground=pal["muted"])
    style.configure("Title.TLabel", font=("Microsoft YaHei UI", 11, "bold"),
                    foreground=pal["fg"], background=pal["bg"])
    style.configure("Header.TFrame", background=pal["header"])
    style.configure("Header.TLabel", background=pal["header"], foreground=pal["header_fg"],
                    font=("Microsoft YaHei UI", 12, "bold"))
    style.configure("TLabelframe", background=pal["bg"], bordercolor=pal["border"])
    style.configure("TLabelframe.Label", background=pal["bg"], foreground=pal["fg"])
    style.configure("TButton", background=pal["panel"], foreground=pal["fg"],
                    bordercolor=pal["border"], padding=(12, 5), relief="flat")
    style.map("TButton", background=[("active", pal["sel"])],
              foreground=[("active", pal["fg"])])
    style.configure("Accent.TButton", background=pal["accent"],
                    foreground=pal["accent_fg"], font=("Microsoft YaHei UI", 9, "bold"),
                    padding=(14, 6))
    style.map("Accent.TButton", background=[("active", pal["accent"])])
    style.configure("TNotebook", background=pal["bg"], borderwidth=0)
    style.configure("TNotebook.Tab", background=pal["panel"], foreground=pal["fg"],
                    padding=(14, 6), bordercolor=pal["border"])
    style.map("TNotebook.Tab",
              background=[("selected", pal["bg"])],
              foreground=[("selected", pal["accent"])])
    style.configure("Treeview", background=pal["panel"], fieldbackground=pal["panel"],
                    foreground=pal["fg"], rowheight=24, bordercolor=pal["border"])
    style.configure("Treeview.Heading", background=pal["panel"], foreground=pal["fg"],
                    font=("Microsoft YaHei UI", 9, "bold"))
    style.map("Treeview", background=[("selected", pal["sel"])])
    style.configure("TEntry", fieldbackground=pal["panel"], foreground=pal["fg"],
                    insertcolor=pal["fg"])
    style.configure("TCombobox", fieldbackground=pal["panel"], foreground=pal["fg"],
                    background=pal["panel"], arrowcolor=pal["fg"])
    style.map("TCombobox",
              fieldbackground=[("readonly", pal["panel"]), ("!readonly", pal["panel"])],
              foreground=[("readonly", pal["fg"]), ("!readonly", pal["fg"])],
              selectbackground=[("readonly", pal["panel"])],
              selectforeground=[("readonly", pal["fg"])])
    style.configure("TCheckbutton", background=pal["bg"], foreground=pal["fg"])
    style.configure("TRadiobutton", background=pal["bg"], foreground=pal["fg"])
    style.configure("Horizontal.TSeparator", background=pal["border"])
    try:
        root.configure(bg=pal["bg"])
    except tk.TclError:
        pass
    # 通知绘图模块换色
    try:
        from . import plots
        plots.set_theme(pal)
    except Exception:
        pass
    return pal