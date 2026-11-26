"""AI 助手页签：对话、动作预览与应用、模型设置。

线程模型：网络请求放到后台线程，结果用 after() 回到主线程刷新界面；
未配置模型时由本地规则引擎回答（source=offline）。
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Dict, List

from ..ai.assistant import Assistant
from ..ai.executor import Executor
from ..ai.client import AIClient, AIError
from ..ai.config import AIConfig, load_config, save_config
from ..ai.personas import all_personas, resolve
from ..ai.skills import dispatch as skill_dispatch
from .dialogs import ModalDialog, FONT, FONT_S

TAG_USER = ("#0b5394", ("Microsoft YaHei UI", 9, "bold"))
TAG_AI = ("#1f2937", ("Microsoft YaHei UI", 9))
TAG_SYS = ("#6b7280", ("Microsoft YaHei UI", 8, "italic"))


def _persona_hint(text: str, limit: int = 30) -> str:
    """角色摘要只留前半句，避免把顶栏撑得过宽。"""
    text = str(text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


class AISettingsDialog(ModalDialog):
    def __init__(self, master, cfg: AIConfig, on_saved=None):
        super().__init__(master, "AI 设置（自定义模型）", 760, 540)
        self.cfg = cfg
        self.on_saved = on_saved
        f = ttk.Frame(self, padding=14)
        f.pack(fill="both", expand=True)
        self.vars: Dict[str, tk.StringVar] = {}

        def field(row, key, label, value, show=None):
            ttk.Label(f, text=label).grid(row=row, column=0, sticky="w", pady=4)
            v = tk.StringVar(value=value)
            self.vars[key] = v
            ttk.Entry(f, textvariable=v, width=46, show=show).grid(
                row=row, column=1, sticky="w", padx=(6, 0))

        field(0, "base_url", "接口地址（base_url）", cfg.base_url)
        field(1, "model", "模型名（model）", cfg.model)
        field(2, "api_key", "接口密钥（API Key）", cfg.api_key, show=None)
        field(3, "temperature", "随机度（temperature）", f"{cfg.temperature:g}")
        field(4, "max_tokens", "最大词元数（max_tokens）", str(cfg.max_tokens))
        field(5, "timeout", "超时（timeout，秒）", f"{cfg.timeout:g}")

        ttk.Label(f, text="兼容任何 OpenAI 风格 /v1/chat/completions 接口：\n"
                          "OpenAI、DeepSeek、通义、Moonshot、智谱、本地 Ollama(/v1)、"
                          "LM Studio(/v1)、vLLM、one-api 等。密钥只保存在本机配置文件。",
                  foreground="#6b7280", font=FONT_S).grid(row=6, column=0, columnspan=2,
                                                         sticky="w", pady=(8, 4))
        self.out = tk.Text(f, height=6, width=62, font=FONT_S, relief="solid", borderwidth=1)
        self.out.grid(row=7, column=0, columnspan=2, sticky="ew", pady=6)
        self.out.insert("1.0", "填好后可先「获取模型列表」或「测试连接」。\n")
        bar = ttk.Frame(f)
        bar.grid(row=8, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Button(bar, text="获取模型列表", command=self.fetch_models).pack(side="left", padx=3)
        ttk.Button(bar, text="测试连接", command=self.test_conn).pack(side="left", padx=3)
        self._busy = False
        self._q = queue.Queue()
        self._alive = True
        self._after_id = None
        self.bind("<Destroy>", self._on_destroy)
        self.buttons("保存", self.save)
        self._after_id = self.after(60, self._pump)

    # ---------- 读取表单 ----------
    def _collect(self) -> AIConfig:
        c = AIConfig()
        c.base_url = self.vars["base_url"].get().strip()
        c.model = self.vars["model"].get().strip()
        c.api_key = self.vars["api_key"].get().strip()
        try:
            c.temperature = float(self.vars["temperature"].get())
        except ValueError:
            c.temperature = 0.3
        try:
            c.max_tokens = int(float(self.vars["max_tokens"].get()))
        except ValueError:
            c.max_tokens = 1200
        try:
            c.timeout = float(self.vars["timeout"].get())
        except ValueError:
            c.timeout = 60.0
        c.persona = self.cfg.persona
        return c

    def _say(self, text: str):
        self.out.delete("1.0", "end")
        self.out.insert("1.0", text)

    def _bg(self, fn, label):
        if self._busy:
            return
        self._busy = True
        self._say(label + "…")

        def work():
            try:
                msg = fn()
            except AIError as e:
                msg = f"失败：{e}"
            except Exception as e:  # noqa: BLE001
                msg = f"失败：{e}"
            self._q.put(("say", (msg,)))

        threading.Thread(target=work, daemon=True).start()

    def _on_destroy(self, event):
        if event.widget is self:
            self._alive = False

    def destroy(self):
        self._alive = False
        try:
            if self._after_id is not None:
                self.after_cancel(self._after_id)
        except Exception:  # noqa: BLE001
            pass
        self._after_id = None
        super().destroy()

    def _pump(self):
        while True:
            try:
                kind, payload = self._q.get_nowait()
            except queue.Empty:
                break
            if not self._alive:
                return
            try:
                if not self.winfo_exists():
                    return
            except tk.TclError:
                return
            if kind == "say":
                self._say(payload[0])
                self._busy = False
            elif kind == "model":
                self.vars["model"].set(payload[0])
        if self._alive:
            self._after_id = self.after(60, self._pump)

    def fetch_models(self):
        cfg = self._collect()

        def fn():
            models = AIClient(cfg).list_models()
            if not models:
                return "接口没有返回模型列表；请手动填写模型名。"
            self._q.put(("model", (models[0],)))
            return "可用模型：\n" + "\n".join(models[:30])

        self._bg(fn, "正在获取模型列表")

    def test_conn(self):
        cfg = self._collect()
        self._bg(lambda: AIClient(cfg).test(), "正在测试连接")

    def save(self):
        cfg = self._collect()
        try:
            path = save_config(cfg)
            self.cfg = cfg
            self._say(f"已保存到 {path}\n密钥显示：{(cfg.api_key or "（空）")}")
            if self.on_saved:
                self.on_saved(cfg)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("保存失败", str(e), parent=self)


class AIPanel(ttk.Frame):
    QUICK = ["分析当前结果", "设计 3 阶 2.4GHz 低通", "设计 2.3-2.7GHz 带通",
             "50Ω 微带线 FR4 1.6mm", "匹配 50 到 100 2.4GHz"]

    def __init__(self, master, app):
        super().__init__(master, padding=8)
        self.app = app
        self.cfg = load_config()
        self.assistant = Assistant(self.cfg)
        self.history: List[Dict[str, str]] = []
        self.pending: List[dict] = []
        self._busy = False
        self._q: "queue.Queue" = queue.Queue()
        self._alive = True
        self._gen = 0
        self._last = None
        self._after_id = None
        self.bind("<Destroy>", self._on_destroy)

        top = ttk.Frame(self)
        top.pack(fill="x")
        self.var_status = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.var_status, font=FONT_S).pack(side="left")
        ttk.Button(top, text="AI 设置…", command=self.open_settings).pack(side="right")
        ttk.Button(top, text="清空对话", command=self.clear_chat).pack(side="right", padx=4)
        ttk.Button(top, text="刷新状态", command=self.refresh_status).pack(side="right", padx=4)

        role = ttk.Frame(self)
        role.pack(fill="x", pady=(4, 0))
        ttk.Label(role, text="对话角色：", font=FONT_S).pack(side="left")
        self._personas = all_personas()
        self.var_persona_hint = tk.StringVar(value="")
        self.var_persona = tk.StringVar(value="")
        self.cmb_persona = ttk.Combobox(
            role, textvariable=self.var_persona, state="readonly", width=18,
            font=FONT_S, values=[p["name"] for p in self._personas])
        self.cmb_persona.pack(side="left", padx=(2, 8))
        self.cmb_persona.bind("<<ComboboxSelected>>", self._on_persona_changed)
        ttk.Label(role, textvariable=self.var_persona_hint, font=FONT_S,
                  foreground="#6b7280", width=42, anchor="w").pack(side="left")
        _p = resolve(self.cfg.persona)
        self.var_persona.set(_p["name"])
        self.var_persona_hint.set(_persona_hint(_p["summary"]))
        self.cfg.persona = _p["id"]
        self.assistant.persona = _p["id"]

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, pady=(6, 4))
        self.chat = tk.Text(mid, height=8, wrap="word", font=FONT, state="disabled",
                            relief="solid", borderwidth=1)
        vs = ttk.Scrollbar(mid, orient="vertical", command=self.chat.yview)
        self.chat.configure(yscrollcommand=vs.set)
        self.chat.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.chat.tag_configure("user", foreground=TAG_USER[0], font=TAG_USER[1])
        self.chat.tag_configure("ai", foreground=TAG_AI[0], font=TAG_AI[1])
        self.chat.tag_configure("sys", foreground=TAG_SYS[0], font=TAG_SYS[1])

        opt = ttk.Frame(self)
        opt.pack(fill="x")
        self.var_auto = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="自动执行（AI 可直接调用功能：改电路、跑仿真、开工具、切页签、保存导出）",
                        variable=self.var_auto).pack(side="left")
        quick = ttk.Frame(self)
        quick.pack(fill="x")
        for i, q in enumerate(self.QUICK):
            ttk.Button(quick, text=q, width=24,
                       command=lambda t=q: self.quick_send(t)).grid(
                row=i // 3, column=i % 3, padx=2, pady=2, sticky="w")

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", pady=(4, 0))
        self.input = tk.Text(bottom, height=3, font=FONT, relief="solid", borderwidth=1)
        self.input.pack(fill="x")
        self.input.bind("<Control-Return>", lambda e: (self.send(), "break"))
        btns = ttk.Frame(bottom)
        btns.pack(fill="x", pady=(4, 0))
        self.btn_send = ttk.Button(btns, text="发送 (Ctrl+Enter)",
                                   command=self.send, width=16)
        self.btn_send.pack(side="left")
        self.btn_stop = ttk.Button(btns, text="停止", command=self.stop, width=8)
        self.btn_stop.pack(side="left", padx=6)
        self.btn_retry = ttk.Button(btns, text="重试", command=self.retry,
                                    state="disabled", width=8)
        self.btn_retry.pack(side="left")

        self.pending_box = ttk.LabelFrame(self, text="待应用的建议（确认后才会改电路）", padding=6)
        self.pending_list = tk.Listbox(self.pending_box, height=4, font=FONT_S)
        self.pending_list.pack(side="left", fill="both", expand=True)
        pbar = ttk.Frame(self.pending_box)
        pbar.pack(side="left", padx=6)
        ttk.Button(pbar, text="应用", command=self.apply_pending).pack(fill="x")
        ttk.Button(pbar, text="丢弃", command=self.discard_pending).pack(fill="x", pady=4)
        self.pending_box.pack_forget()

        self.refresh_status()
        self._append("sys", "提示：未配置模型时使用本地规则（滤波器/微带/匹配/改频/结果分析）。"
                            "配置任意 OpenAI 兼容模型后可用自然语言对话。")
        self._after_id = self.after(60, self._pump)

    # ---------- 角色 ----------
    def _on_persona_changed(self, _evt=None):
        p = resolve(self.var_persona.get())
        self.cfg.persona = p["id"]
        self.assistant.persona = p["id"]
        self.var_persona_hint.set(_persona_hint(p["summary"]))
        try:
            save_config(self.cfg)
        except Exception:
            pass
        self._append("sys", f"对话角色切换为「{p['name']}」：{p['summary']}")

    # ---------- 状态 ----------
    def refresh_status(self):
        if self.cfg.enabled:
            self.var_status.set(f"模型：{self.cfg.model} @ {self.cfg.base_url}　密钥：{(self.cfg.api_key or "（空）")}")
        else:
            self.var_status.set("模型：未配置（使用本地规则引擎）")

    def open_settings(self):
        dlg = AISettingsDialog(self, self.cfg, on_saved=self._on_cfg_saved)
        self.wait_window(dlg)

    def _on_cfg_saved(self, cfg: AIConfig):
        self.cfg = cfg
        self.assistant = Assistant(cfg)
        _p = resolve(self.cfg.persona)
        self.var_persona.set(_p["name"])
        self.var_persona_hint.set(_persona_hint(_p["summary"]))
        self.refresh_status()
        self._append("sys", f"AI 配置已更新：{cfg.model or '（未命名）'}")

    # ---------- 对话 ----------
    def _append(self, role: str, text: str):
        tag = {"user": "user", "ai": "ai", "sys": "sys"}[role]
        prefix = {"user": "我：", "ai": "助手：", "sys": "· "}[role]
        self.chat.configure(state="normal")
        self.chat.insert("end", prefix + text + "\n\n", tag)
        self.chat.see("end")
        self.chat.configure(state="disabled")

    def clear_chat(self):
        self.chat.configure(state="normal")
        self.chat.delete("1.0", "end")
        self.chat.configure(state="disabled")
        self.history.clear()
        self.discard_pending()

    def quick_send(self, text: str):
        self.input.delete("1.0", "end")
        self.input.insert("1.0", text)
        self.send()

    def ask_sync(self, text: str) -> dict:
        """同步调用（供测试/批处理）；不经过线程。"""
        return self.assistant.ask(text, self.app.project, self.app.result, self.history)

    # ---------- 主线程队列：后台线程只允许用 _post，绝不碰 tkinter ----------
    def _post(self, kind: str, *payload):
        """后台线程唯一可用的回调出口（queue 线程安全，无 tkinter 调用）。"""
        self._q.put((kind, payload))

    def _pump(self):
        """主线程每 60ms 排空队列并刷新界面。"""
        while True:
            try:
                kind, payload = self._q.get_nowait()
            except queue.Empty:
                break
            if not self._alive:
                return
            try:
                if not self.winfo_exists():
                    return
            except tk.TclError:
                return
            if kind == "done":
                gen, text, res, auto = payload
                if gen == self._gen:          # 丢弃过期结果
                    self._render_done(text, res, auto)
            elif kind == "fail":
                gen, text, msg = payload
                if gen == self._gen:
                    self._render_fail(text, msg)
            elif kind == "skill":
                gen, text, hit = payload
                if gen == self._gen:
                    self._render_skill(text, hit)
            elif kind == "offline":
                gen, text, hint = payload
                if gen == self._gen:
                    self._render_offline(text, hint)
            elif kind == "status":
                self.var_status.set(payload[0])
        if self._alive:
            self._after_id = self.after(60, self._pump)

    def send(self):
        text = self.input.get("1.0", "end").strip()
        if not text:
            return
        if self._busy:
            return
        self.input.delete("1.0", "end")
        self._append("user", text)
        self._last = text
        self.btn_retry.configure(state="normal")
        self._gen += 1
        gen = self._gen
        self._busy = True
        self.btn_send.configure(state="disabled")
        auto = bool(self.var_auto.get())
        self.var_status.set("自动执行中…" if auto else "思考中…")
        history = list(self.history)

        def work():
            try:
                hit = skill_dispatch.run(text, app=self.app)
                if hit is not None and hit.get("ok"):
                    self._post("skill", gen, text, hit)
                    return
                if not self.cfg.enabled:
                    self._post("offline", gen, text,
                               (hit or {}).get("message") or "")
                    return
                if auto:
                    ex = Executor(self.app.project, out_dir=self.app.ai_out_dir())
                    res = self.assistant.run_agent(text, self.app.project,
                                                   self.app.result, executor=ex,
                                                   history=history)
                else:
                    res = self.assistant.ask(text, self.app.project, self.app.result,
                                             history)
            except Exception as e:  # noqa: BLE001
                self._post("fail", gen, text, str(e))
                return
            self._post("done", gen, text, res, auto)

        threading.Thread(target=work, daemon=True).start()

    def _set_idle(self):
        self._busy = False
        self.btn_send.configure(state="normal")

    def _render_fail(self, text: str, msg: str):
        self._set_idle()
        self._append("ai", f"故障：{msg}")
        if "→" not in msg:
            self._append("sys", "下一步：检查接口地址 / 密钥 / 网络后点「重试」。")
        self.history.append({"role": "user", "content": text})
        self.history.append({"role": "assistant", "content": f"故障：{msg}"})
        self.refresh_status()

    def _render_skill(self, text: str, hit: dict):
        """技能直接回执：只读技能到此结束，改电路的技能落到「待应用」区。"""
        self._set_idle()
        title = hit.get("title") or hit.get("skill") or ""
        self._append("ai", "【%s】\n%s" % (title, hit.get("message") or ""))
        acts = hit.get("actions") or []
        if acts:
            self._set_pending(acts)
            self._append("sys", "以上是提案，确认无误后点下方「应用」再写入电路。")
        elif not hit.get("read_only"):
            self._append("sys", "本软件的「生成滤波器」动作目前只支持低通/带通；"
                                "上表数值可照着逐节手工添加元件。")
        else:
            self.discard_pending()
        self.history.append({"role": "user", "content": text})
        self.history.append({"role": "assistant",
                             "content": hit.get("message") or ""})
        self.refresh_status()

    def _render_offline(self, text: str, hint: str):
        self._set_idle()
        if hint:
            self._append("sys", hint)
        self._append("sys", "模型未配置：当前只能用内置技能"
                            "（滤波器综合 / 曲线解读 / 匹配设计）。"
                            "到「AI 设置」填接口后可用自然语言对话。")
        self.var_status.set("模型未配置（可用内置技能）")

    def _render_done(self, text: str, res: dict, auto: bool):
        self._set_idle()
        source = "模型" if res.get("source") == "model" else "本地规则"
        self._append("ai", (res.get("reply") or "") + f"\n（来源：{source}）")
        for r in res.get("results") or []:
            mark = "✓" if r.get("ok") else "✗"
            self._append("sys", f"{mark} {r.get('text', '')}")
        if res.get("tab_hint") or res.get("tool_hint"):
            self._append("sys", f"界面动作：页签={res.get('tab_hint') or '-'}，"
                                f"工具={res.get('tool_hint') or '-'}")
        if auto:
            try:
                self.app.ai_finish_agent(res)
            except Exception as e:  # noqa: BLE001
                self._append("sys", f"界面同步失败：{e}")
        for e in res.get("errors") or []:
            self._append("sys", e)
        self.history.append({"role": "user", "content": text})
        self.history.append({"role": "assistant", "content": res.get("reply", "")})
        if not auto and res.get("actions"):
            self._set_pending(res["actions"])
        else:
            self.discard_pending()
        self.refresh_status()

    def stop(self):
        """放弃当前生成结果（守护线程无法真正终止，只丢弃它的回执）。"""
        self._gen += 1
        self._set_idle()
        self.refresh_status()

    def retry(self):
        if self._last is None or self._busy:
            return
        self.input.delete("1.0", "end")
        self.input.insert("1.0", self._last)
        self.send()

    def _on_destroy(self, event):
        if event.widget is self:
            self._alive = False

    def destroy(self):
        self._alive = False
        try:
            if self._after_id is not None:
                self.after_cancel(self._after_id)
        except Exception:  # noqa: BLE001
            pass
        self._after_id = None
        super().destroy()

    # ---------- 建议应用 ----------
    def _set_pending(self, actions: List[dict]):
        self.pending = list(actions)
        self.pending_list.delete(0, "end")
        if not actions:
            self.pending_box.pack_forget()
            return
        for i, a in enumerate(actions, 1):
            self.pending_list.insert("end", f"{i}. {self._describe(a)}")
        self.pending_box.pack(fill="x", pady=(6, 0))

    @staticmethod
    def _describe(a: dict) -> str:
        op = a.get("op")
        if op == "add":
            return f"新增 {a.get('id') or ''} {a.get('kind')} {'-'.join(a.get('nodes', []))} {a.get('params')}"
        if op == "update":
            return f"更新 {a.get('id')} → {a.get('params')}"
        if op == "delete":
            return f"删除 {a.get('id')}"
        if op == "build_filter":
            topo = a.get("topo")
            if topo in ("bandpass", "bandstop"):
                name = "带通" if topo == "bandpass" else "带阻"
                return (f"生成{name} {a.get('f1_ghz')}–{a.get('f2_ghz')} GHz，"
                        f"{a.get('order')} 阶")
            name = "高通" if topo == "highpass" else "低通"
            return f"生成{name} {a.get('fc_ghz')} GHz，{a.get('order')} 阶"
        if op == "set_z0":
            return f"Z0 → {a.get('value')} Ω"
        if op == "set_analysis":
            return f"分析设置 → {a}"
        if op == "clear":
            return "清空全部元件"
        if op == "run":
            return "运行仿真"
        return str(a)

    def apply_pending(self):
        if not self.pending:
            return
        try:
            report = self.app.ai_apply_actions(self.pending)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("应用失败", str(e), parent=self)
            return
        self._append("sys", "已应用：\n" + "\n".join("· " + r for r in report))
        self.pending = []
        self.pending_list.delete(0, "end")
        self.pending_box.pack_forget()

    def discard_pending(self):
        self.pending = []
        self.pending_list.delete(0, "end")
        self.pending_box.pack_forget()