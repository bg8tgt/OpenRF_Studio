# -*- coding: utf-8 -*-
"""技能基类与运行时上下文。

设计原则（见项目根 AI_SKILL_PLAN.md）：
1. 模型永不直接改电路。技能只产出 ActionResult（含 patch 建议），
   由界面或用户确认后才调用 apply()。
2. apply() 只允许调用应用已有的公开 API，不允许 eval、不写文件、不发网络请求。
3. preview() 必须能在没有 GUI、没有网络的环境下完成全部计算，
   这样断网也能用（纯计算类技能）。
"""

from __future__ import annotations


def _as_sweep_dict(v):
    """把 SweepResult 之类的对象规整成 {"freq_ghz","s21_db","s11_db"}。

    只认引擎已有的公开方法（freqs / insertion_loss_db / return_loss_db），
    不猜索引，也不重算 dB——曲线解读必须和界面看到的是同一条曲线。
    """
    if isinstance(v, dict):
        return v if "freq_ghz" in v else None
    if v is None:
        return None
    freqs = getattr(v, "freqs", None)
    if not freqs:
        return None
    try:
        out = {"freq_ghz": [float(x) / 1e9 for x in freqs]}
    except Exception:
        return None
    try:
        if hasattr(v, "insertion_loss_db"):
            out["s21_db"] = list(v.insertion_loss_db())
        if hasattr(v, "return_loss_db"):
            out["s11_db"] = list(v.return_loss_db())
    except Exception:
        pass
    return out if "s21_db" in out else None


class ActionResult(object):
    """技能的返回值。

    ok          : 计算是否成功
    message     : 给人看的一段话（可多行）
    patch       : 建议写入的参数 dict，例如 {"fc_ghz": 2.0}
    data        : 结构化结果（元件表、指标数值等），给界面或测试用
    needs_confirm: True 表示这是提案，必须先经人确认才能 apply
    kind        : info / proposal / error，界面据此决定图标与按钮
    """

    __slots__ = ("ok", "message", "patch", "data", "needs_confirm", "kind")

    def __init__(self, ok=True, message="", patch=None, data=None,
                 needs_confirm=False, kind="info"):
        self.ok = bool(ok)
        self.message = str(message)
        self.patch = dict(patch or {})
        self.data = dict(data or {})
        self.needs_confirm = bool(needs_confirm)
        self.kind = kind

    def as_dict(self):
        return {
            "ok": self.ok,
            "message": self.message,
            "patch": self.patch,
            "data": self.data,
            "needs_confirm": self.needs_confirm,
            "kind": self.kind,
        }

    def __repr__(self):
        return "<ActionResult ok=%s kind=%s msg=%r>" % (
            self.ok, self.kind, self.message[:40])


class SkillContext(object):
    """技能能碰到的一切外部东西都从这里拿。

    刻意做成弱耦合：真实应用对象通过 app/controller/sim 注入，
    取不到就返回 None，技能自己降级，绝不抛异常打断对话。

    只读侧：sweep_result / params / frequency_ghz
    只写侧：set_param / run_sim（仅 apply 阶段使用）
    """

    def __init__(self, app=None, controller=None, sim=None, extra=None):
        self.app = app
        self.controller = controller
        self.sim = sim
        self.extra = dict(extra or {})

    # ---------------- 只读采集 ----------------

    def params(self):
        """当前电路参数（元件值、拓扑等）的浅拷贝。"""
        for holder in (self.controller, self.sim, self.app):
            if holder is None:
                continue
            for attr in ("params", "get_params", "state"):
                try:
                    v = getattr(holder, attr, None)
                except Exception:
                    continue
                if callable(v):
                    try:
                        v = v()
                    except Exception:
                        continue
                if isinstance(v, dict):
                    return dict(v)
        return {}

    def get_param(self, name, default=None):
        return self.params().get(name, default)

    def frequency_ghz(self):
        """当前扫描中心频率（GHz）。"""
        for holder in (self.controller, self.sim, self.app):
            if holder is None:
                continue
            for attr in ("var_f", "freq_ghz", "frequency_ghz"):
                try:
                    v = getattr(holder, attr, None)
                except Exception:
                    continue
                if isinstance(v, (int, float)):
                    return float(v)
        return None

    def sweep_result(self):
        """最近一次扫描的原始数组。

        统一格式：{"freq_ghz": [...], "s21_db": [...], "s11_db": [...]}
        取不到返回 None。
        """
        cached = self.extra.get("sweep")
        if _as_sweep_dict(cached) is not None:
            return _as_sweep_dict(cached)
        for holder in (self.controller, self.sim, self.app):
            if holder is None:
                continue
            for attr in ("sweep_result", "last_sweep", "result"):
                try:
                    v = getattr(holder, attr, None)
                except Exception:
                    continue
                if callable(v):
                    try:
                        v = v()
                    except Exception:
                        continue
                norm = _as_sweep_dict(v)
                if norm is not None:
                    return norm
        return None

    # ---------------- 只写入口（apply 阶段） ----------------

    def set_param(self, name, value):
        """写一个标量参数；成功返回 True。"""
        for holder in (self.controller, self.sim):
            if holder is None:
                continue
            setter = getattr(holder, "set_param", None)
            if callable(setter):
                try:
                    setter(name, value)
                    return True
                except Exception:
                    pass
            try:
                if hasattr(holder, name):
                    setattr(holder, name, value)
                    return True
            except Exception:
                pass
        return False

    def run_sim(self):
        """触发一次仿真；没有仿真器返回 False。"""
        for holder in (self.controller, self.sim, self.app):
            if holder is None:
                continue
            fn = getattr(holder, "compute", None) or getattr(holder, "run_sim", None)
            if callable(fn):
                try:
                    fn()
                    return True
                except Exception:
                    return False
        return False

    def __repr__(self):
        return "<SkillContext app=%s ctrl=%s sim=%s>" % (
            type(self.app).__name__, type(self.controller).__name__,
            type(self.sim).__name__)


class Skill(object):
    """一个技能 = 一段能力。

    子类只需覆写 name/title/summary/triggers 和 preview()。
    纯计算类（read_only = True）不需要 apply()，系统会直接展示结果。
    会改电路的技能必须实现 apply()，且只能在用户确认后调用。
    """

    name = ""
    title = ""
    summary = ""
    triggers = ()
    params = {}
    read_only = True

    # ---- 对外 ----

    def preview(self, ctx, **kwargs):
        raise NotImplementedError("技能 %s 未实现 preview()" % self.name)

    def apply(self, ctx, **kwargs):
        return ActionResult(
            ok=False,
            message="该技能只提供分析结果，不需要应用到电路。",
            kind="info",
        )

    def describe(self):
        return {
            "name": self.name,
            "title": self.title,
            "summary": self.summary,
            "read_only": bool(self.read_only),
            "params": dict(self.params),
            "triggers": list(self.triggers),
        }

    def __repr__(self):
        return "<Skill %s>" % self.name
