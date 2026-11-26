# -*- coding: utf-8 -*-
"""OpenRF Studio 安装程序（单文件安装包）。

内置 payload.zip（主程序 + Python 运行时 + 文档 + 示例），不需要联网、
不需要用户另外装 Python。

用法：
    双击                        图形安装向导
    --silent --dir=DIR          静默安装到 DIR
    --uninstall [--silent]      卸载

设计约束：只用标准库；不写系统盘以外的东西；注册表只动 HKCU。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

APP_NAME = "OpenRF Studio"
APP_VERSION = "3.0.8"
APP_EXE = "OpenRF_Studio.exe"
PUBLISHER = "BG9LP"
REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\OpenRF_Studio"
SHORTCUT = "OpenRF Studio 射频工作台.lnk"

CREATE_NO_WINDOW = 0x08000000
DETACHED = 0x00000008


# ------------------------------------------------------------------ 基础
def resource(name: str) -> str:
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, name)


def payload_path() -> str:
    return resource("payload.zip")


def default_dir() -> str:
    la = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(la, "Programs", APP_NAME)


def log_line(msg: str):
    print(msg, flush=True)


def run_hidden(args, **kw):
    kw.setdefault("creationflags", CREATE_NO_WINDOW)
    kw.setdefault("stdout", subprocess.DEVNULL)
    kw.setdefault("stderr", subprocess.DEVNULL)
    return subprocess.run(args, **kw)


def ps_escape(s: str) -> str:
    return str(s).replace("'", "''")


def run_ps(script: str) -> int:
    """把脚本写成 UTF-8 BOM 文件再执行，避免中文路径在 ANSI 下变乱码。"""
    fd, path = tempfile.mkstemp(suffix=".ps1")
    os.close(fd)
    try:
        with open(path, "w", encoding="utf-8-sig") as f:
            f.write(script)
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-WindowStyle", "Hidden", "-File", path],
            creationflags=CREATE_NO_WINDOW,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return r.returncode
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def make_shortcut(lnk: str, target: str, workdir: str, icon: str) -> bool:
    script = (
        "$ErrorActionPreference='Stop'\n"
        "$W = New-Object -ComObject WScript.Shell\n"
        "$S = $W.CreateShortcut('%s')\n"
        "$S.TargetPath = '%s'\n"
        "$S.WorkingDirectory = '%s'\n"
        "$S.IconLocation = '%s'\n"
        "$S.Description = 'OpenRF Studio 射频/微波电路仿真工作台'\n"
        "$S.Save()\n") % (ps_escape(lnk), ps_escape(target),
                          ps_escape(workdir), ps_escape(icon))
    return run_ps(script) == 0 and os.path.exists(lnk)


def make_url_shortcut(lnk: str, target: str) -> bool:
    return make_shortcut(lnk, target, os.path.dirname(target), target)


# ------------------------------------------------------------------ 卸载
UNINST_PS = r"""$ErrorActionPreference = 'SilentlyContinue'
$dir = '__DIR__'
$lnk = '__LNK__'
Write-Host ''
Write-Host '  正在删除快捷方式 ...'
foreach ($p in @(
        (Join-Path ([Environment]::GetFolderPath('Desktop')) $lnk),
        (Join-Path ([Environment]::GetFolderPath('Programs')) $lnk),
        (Join-Path ([Environment]::GetFolderPath('CommonPrograms')) $lnk)
)) { Remove-Item -LiteralPath $p -Force }

Write-Host '  正在删除注册表项 ...'
Remove-Item -LiteralPath 'HKCU:\__REG__' -Recurse -Force

Write-Host '  正在删除程序文件 ...'
Get-ChildItem -LiteralPath $dir -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne 'uninstall.cmd' -and $_.Name -ne '_uninst.ps1' } |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }

Write-Host ''
Write-Host '  OpenRF Studio 已卸载。'
Start-Sleep -Milliseconds 600
Start-Process -WindowStyle Hidden -FilePath 'cmd.exe' -ArgumentList '/c', ('timeout /t 2 >nul & rd /s /q "' + $dir + '"')
"""

UNINST_CMD = r"""@echo off
chcp 65001 >nul
title 卸载 OpenRF Studio
echo.
echo   ======================================
echo      OpenRF Studio 卸载程序
echo   ======================================
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0_uninst.ps1"
exit /b 0
"""


def write_uninstaller(target: str) -> None:
    ps = (UNINST_PS
          .replace("__DIR__", ps_escape(target))
          .replace("__LNK__", ps_escape(SHORTCUT))
          .replace("__REG__", ps_escape(REG_PATH.replace("\\", "\\"))))
    with open(os.path.join(target, "_uninst.ps1"), "w", encoding="utf-8-sig") as f:
        f.write(ps)
    with open(os.path.join(target, "uninstall.cmd"), "w", encoding="utf-8-sig") as f:
        f.write(UNINST_CMD)


def remove_registry() -> None:
    try:
        import winreg
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REG_PATH)
    except OSError:
        pass


def write_registry(target: str) -> None:
    import winreg
    exe = os.path.join(target, APP_EXE)
    uninst = os.path.join(target, "uninstall.cmd")
    size_kb = 0
    for root, _dirs, files in os.walk(target):
        for n in files:
            try:
                size_kb += os.path.getsize(os.path.join(root, n)) // 1024
            except OSError:
                pass
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_PATH) as k:
        for name, val in (
            ("DisplayName", APP_NAME + " 射频工作台"),
            ("DisplayVersion", APP_VERSION),
            ("Publisher", PUBLISHER),
            ("InstallLocation", target),
            ("DisplayIcon", exe + ",0"),
            ("UninstallString", 'cmd /c start "" /min "%s"' % uninst),
            ("QuietUninstallString", 'cmd /c "%s"' % uninst),
            ("HelpLink", "https://github.com/"),
        ):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
        winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, int(size_kb))
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)


def uninstall() -> int:
    import winreg
    target = None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH) as k:
            target = winreg.QueryValueEx(k, "InstallLocation")[0]
    except OSError:
        base = os.path.dirname(os.path.abspath(sys.executable))
        target = base if os.path.exists(os.path.join(base, APP_EXE)) else None
    if not target or not os.path.isdir(target):
        log_line("找不到安装位置，可能已经卸载过了。")
        return 1
    script = (UNINST_PS
              .replace("__DIR__", ps_escape(target))
              .replace("__LNK__", ps_escape(SHORTCUT))
              .replace("__REG__", ps_escape(REG_PATH.replace("\\", "\\"))))
    return run_ps(script)


# ------------------------------------------------------------------ 安装
def install(target: str, desktop: bool, startmenu: bool,
            progress=None, status=None) -> None:
    src = payload_path()
    if not os.path.exists(src):
        raise RuntimeError("安装包损坏：找不到内置的 payload.zip")

    def note(msg):
        log_line(msg)
        if status:
            status(msg)

    note("正在创建安装目录 …")
    os.makedirs(target, exist_ok=True)

    with zipfile.ZipFile(src) as z:
        items = z.infolist()
        total = max(1, len(items))
        for i, item in enumerate(items, 1):
            z.extract(item, target)
            if progress and (i % 25 == 0 or i == total):
                progress(i * 100.0 / total)
    note("程序文件已解压 …")

    if progress:
        progress(93)
    note("正在写入卸载信息 …")
    write_uninstaller(target)
    try:
        write_registry(target)
    except Exception as exc:                      # 注册表失败不该阻断安装
        log_line("注册表写入失败（不影响使用）：%s" % exc)

    if progress:
        progress(96)
    exe = os.path.join(target, APP_EXE)
    if startmenu:
        note("正在创建开始菜单快捷方式 …")
        programs = os.path.join(os.environ.get("APPDATA", ""), "Microsoft",
                                "Windows", "Start Menu", "Programs")
        make_shortcut(os.path.join(programs, SHORTCUT), exe, target, exe)
    if desktop:
        note("正在创建桌面快捷方式 …")
        desk = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
        make_shortcut(os.path.join(desk, SHORTCUT), exe, target, exe)

    if progress:
        progress(100)
    note("安装完成。")


def launch(target: str) -> None:
    exe = os.path.join(target, APP_EXE)
    if os.path.exists(exe):
        subprocess.Popen([exe], cwd=target, creationflags=DETACHED,
                         close_fds=True)


# ------------------------------------------------------------------ 图形界面
def gui() -> int:
    import tkinter as tk
    from tkinter import filedialog, ttk

    root = tk.Tk()
    root.title("%s v%s 安装程序" % (APP_NAME, APP_VERSION))
    root.geometry("620x430")
    root.resizable(False, False)
    try:
        for _n in ("setup.ico", "openrf.ico"):
            ico = resource(_n)
            if os.path.exists(ico):
                root.iconbitmap(ico)
                break
    except Exception:
        pass

    state = {"busy": False, "done": False}

    top = tk.Frame(root, bg="#0b5394", height=78)
    top.pack(fill="x")
    tk.Label(top, text="OpenRF Studio 射频工作台", bg="#0b5394", fg="white",
             font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w", padx=18, pady=(14, 0))
    tk.Label(top, text="版本 %s    ·    干净室实现    ·    纯 Python 标准库"
             % APP_VERSION, bg="#0b5394", fg="#cfe2f3",
             font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=18, pady=(2, 12))

    body = ttk.Frame(root, padding=(18, 14))
    body.pack(fill="both", expand=True)

    ttk.Label(body, text="安装到：", font=("Microsoft YaHei UI", 9)).grid(
        row=0, column=0, sticky="w")
    var_dir = tk.StringVar(value=default_dir())
    ent = ttk.Entry(body, textvariable=var_dir, width=56)
    ent.grid(row=0, column=1, sticky="we", padx=(6, 6))

    def browse():
        d = filedialog.askdirectory(title="选择安装目录", initialdir=var_dir.get())
        if d:
            var_dir.set(os.path.normpath(d))

    ttk.Button(body, text="浏览…", command=browse, width=8).grid(row=0, column=2)
    body.columnconfigure(1, weight=1)

    var_desk = tk.BooleanVar(value=True)
    var_menu = tk.BooleanVar(value=True)
    var_run = tk.BooleanVar(value=True)
    ttk.Checkbutton(body, text="创建桌面快捷方式", variable=var_desk).grid(
        row=1, column=1, sticky="w", pady=(10, 0))
    ttk.Checkbutton(body, text="创建开始菜单快捷方式", variable=var_menu).grid(
        row=2, column=1, sticky="w")
    ttk.Checkbutton(body, text="安装完成后立即运行", variable=var_run).grid(
        row=3, column=1, sticky="w")

    ttk.Separator(body, orient="horizontal").grid(
        row=4, column=0, columnspan=3, sticky="we", pady=14)

    ttk.Label(body, text="包含内容：主程序与运行时、AI 助手（角色前置 + 三个内置技能）、"
                         "用户手册与架构文档、5 组示例工程",
              wraplength=560, foreground="#555555",
              font=("Microsoft YaHei UI", 8)).grid(
        row=5, column=0, columnspan=3, sticky="w")

    bar = ttk.Progressbar(body, mode="determinate", maximum=100)
    bar.grid(row=6, column=0, columnspan=3, sticky="we", pady=(16, 6))
    var_status = tk.StringVar(value="准备就绪。点「开始安装」继续。")
    ttk.Label(body, textvariable=var_status,
              font=("Microsoft YaHei UI", 9)).grid(
        row=7, column=0, columnspan=3, sticky="w")

    btns = ttk.Frame(body)
    btns.grid(row=8, column=0, columnspan=3, sticky="e", pady=(16, 0))
    btn_install = ttk.Button(btns, text="开始安装", width=14)
    btn_install.pack(side="right", padx=(8, 0))
    btn_close = ttk.Button(btns, text="退出", width=10, command=root.destroy)
    btn_close.pack(side="right")

    def set_progress(v):
        bar["value"] = v

    def set_status(s):
        var_status.set(s)

    def worker(target):
        try:
            install(target, bool(var_desk.get()), bool(var_menu.get()),
                    progress=lambda v: root.after(0, set_progress, v),
                    status=lambda s: root.after(0, set_status, s))
            state["done"] = True
            root.after(0, finish_ok)
        except Exception as exc:
            msg = "%s: %s" % (type(exc).__name__, exc)
            state["busy"] = False
            root.after(0, finish_err, msg)

    def finish_ok():
        state["busy"] = False
        btn_install.configure(text="完成", command=root.destroy, state="normal")
        btn_close.configure(state="normal")
        ent.configure(state="disabled")
        set_status("安装完成，可以点「完成」关闭。")
        if var_run.get():
            launch(var_dir.get())

    def finish_err(msg):
        btn_install.configure(state="normal", text="重试")
        btn_close.configure(state="normal")
        set_status("安装失败：" + msg)
        bar["value"] = 0

    def start():
        target = var_dir.get().strip().strip('"')
        if not target:
            set_status("请先选择安装目录。")
            return
        if state["done"]:
            root.destroy()
            return
        if state["busy"]:
            return
        state["busy"] = True
        btn_install.configure(state="disabled")
        btn_close.configure(state="disabled")
        threading.Thread(target=worker, args=(target,), daemon=True).start()

    btn_install.configure(command=start)
    root.mainloop()
    return 0


# ------------------------------------------------------------------ 入口
def main(argv) -> int:
    args = [a for a in argv[1:]]
    if "--uninstall" in args:
        silent = "--silent" in args
        if silent:
            return uninstall()
        cand = [a for a in args if a.startswith("--dir=")]
        return uninstall()
    if "--silent" in args:
        target = None
        for a in args:
            if a.startswith("--dir="):
                target = a.split("=", 1)[1]
        target = target or default_dir()
        try:
            install(target, desktop="--nodesktop" not in args,
                    startmenu="--nomenu" not in args)
        except Exception as exc:
            log_line("安装失败：%s" % exc)
            return 2
        if "--run" in args:
            launch(target)
        return 0
    try:
        return gui()
    except Exception:
        import traceback
        traceback.print_exc()
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv))
