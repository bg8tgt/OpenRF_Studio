# -*- coding: utf-8 -*-
"""技能派发：把一句自然语言变成一次技能调用。

约定（与 AI_SKILL_PLAN.md 一致）：
- 只读技能（read_only=True）直接出结论，不需要确认。
- 会改电路的技能只产出"提案"，必须由界面上的“应用”按钮确认。
- 解析不到参数就用技能默认值，绝不编造数字。
"""
from __future__ import annotations

from . import route
from . import params
from .base import SkillContext


def _ctx(app=None):
    return SkillContext(app=app)


def build_actions(skill, result):
    """把技能提案翻译成界面已有的动作格式（只有 circuit.build 有对应动作）。"""
    if not result.ok or getattr(skill, "name", "") != "circuit.build":
        return []
    info = result.data.get("info") or {}
    topo = info.get("kind")
    if topo not in ("lowpass", "highpass", "bandpass", "bandstop"):
        return []
    act = {"op": "build_filter", "topo": topo,
           "order": int(info.get("order") or 3)}
    if info.get("fc_ghz") is not None:
        act["fc_ghz"] = float(info["fc_ghz"])
    if info.get("f1_ghz") is not None and info.get("f2_ghz") is not None:
        act["f1_ghz"] = float(info["f1_ghz"])
        act["f2_ghz"] = float(info["f2_ghz"])
    return [act]


def run(text, app=None, ctx=None):
    """返回 None 表示没有技能接这句话；否则返回统一的回执 dict。"""
    text = str(text or "")
    skill = route(text)
    if skill is None:
        return None
    kw = params.parse(text, skill.name)
    c = ctx if ctx is not None else _ctx(app)
    try:
        res = skill.preview(c, **kw)
    except Exception as exc:  # 技能内部异常不该打断对话
        return {"skill": skill.name, "title": skill.title,
                "ok": False, "message": "技能执行出错：%s" % exc,
                "read_only": bool(skill.read_only),
                "needs_confirm": False, "actions": [], "kw": kw}
    return {
        "skill": skill.name,
        "title": skill.title,
        "ok": bool(res.ok),
        "message": res.message,
        "read_only": bool(skill.read_only),
        "needs_confirm": bool(res.needs_confirm),
        "kind": res.kind,
        "actions": build_actions(skill, res),
        "data": res.data,
        "kw": kw,
    }
