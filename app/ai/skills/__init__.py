# -*- coding: utf-8 -*-
"""技能注册表：自动发现 app/ai/skills 下的所有技能模块。"""

from __future__ import annotations

import importlib
import pkgutil
import traceback

_PACKAGE = __name__
_BUILTIN = ("circuit_build", "plot_explain", "match_design")
_MIN_SCORE = 3
_MAX_KEYWORD_HITS = 4

_registry = {}
_order = []
_errors = {}
_loaded = False


def _iter_module_names():
    names = []
    try:
        for mod in pkgutil.iter_modules(__path__):
            if mod.name.startswith("_") or mod.name == "base":
                continue
            names.append(mod.name)
    except Exception:
        pass
    for nm in _BUILTIN:
        if nm not in names:
            names.append(nm)
    return names


def _collect(obj):
    from .base import Skill

    found = []
    for attr in dir(obj):
        if attr.startswith("_"):
            continue
        try:
            val = getattr(obj, attr)
        except Exception:
            continue
        if not isinstance(val, type) or not issubclass(val, Skill):
            continue
        if val is Skill or not getattr(val, "name", ""):
            continue
        try:
            found.append(val())
        except Exception:
            _errors.setdefault(getattr(val, "name", attr), "实例化失败: %s" % attr)
    return found


def _static_modules():
    """静态导入内置技能模块。

    PyInstaller 只收集静态 import 的模块；纯 importlib 的动态发现在打包后
    会静默失效（iter_modules 拿不到 PYZ 里的子模块），结果就是 exe 里
    一个技能都没有。这里给打包器留一条明确的依赖边。
    """
    mods = []
    # 这里必须是真正的 import 语句（不能是 import_module 字符串调用），
    # 打包器只认静态 import；逐个包 try 是为了缺模块时不影响其它技能。
    try:
        from . import circuit_build
        mods.append(circuit_build)
    except Exception:
        pass
    try:
        from . import plot_explain
        mods.append(plot_explain)
    except Exception:
        pass
    try:
        from . import match_design
        mods.append(match_design)
    except Exception:
        pass
    return mods


def discover(force=False):
    global _loaded
    if _loaded and not force:
        return dict(_registry)
    _registry.clear()
    _order.clear()
    _errors.clear()
    for nm in _iter_module_names():
        try:
            mod = importlib.import_module("." + nm, _PACKAGE)
        except Exception:
            _errors[nm] = traceback.format_exc(limit=2)
            continue
        for skill in _collect(mod):
            if skill.name in _registry:
                continue
            _registry[skill.name] = skill
            _order.append(skill.name)
    # 兜底：动态发现拿不到时（打包环境），用 _BUILTIN 再收一遍
    for mod in _static_modules():
        for skill in _collect(mod):
            if skill.name in _registry:
                continue
            _registry[skill.name] = skill
            _order.append(skill.name)
    _loaded = True
    return dict(_registry)


def catalog():
    discover()
    out = []
    for nm in _order:
        try:
            out.append(_registry[nm].describe())
        except Exception:
            continue
    return out


def get(name):
    discover()
    return _registry.get(name)


def errors():
    discover()
    return dict(_errors)


def _score(skill, text):
    low = text.lower()
    score = 0
    hits = 0
    for trig in getattr(skill, "triggers", ()) or ():
        t = str(trig).lower()
        if t and t in low:
            # 中文关键词往往只有两三个字，按字符数计权会让“带宽”“匹配”
            # 这类高区分度的词永远够不到阈值；给 CJK 加一档基础权重。
            score += len(t) if t.isascii() else max(3, len(t) + 1)
            hits += 1
            if hits >= _MAX_KEYWORD_HITS:
                break
    nm = getattr(skill, "name", "")
    if nm and nm.lower() in low:
        score += 20
    for part in nm.split("."):
        if part and part.lower() in low and len(part) >= 3:
            score += 3
    return score


def match_triggers(text, limit=3):
    discover()
    text = str(text or "")
    if not text.strip():
        return []
    scored = []
    for nm in _order:
        s = _score(_registry[nm], text)
        if s >= _MIN_SCORE:
            scored.append((nm, s))
    scored.sort(key=lambda p: -p[1])
    return scored[:max(1, int(limit))]


# 会改电路的技能要求更高的命中分：误触发只读分析无伤，
# 误触发“重建电路”会把用户已有的网络冲掉，必须更保守。
_MODIFY_MIN_SCORE = 6


def route(text):
    """挑一个技能；两个都够格时取分高的那个。"""
    for nm, score in match_triggers(text, limit=3):
        sk = get(nm)
        if sk is None:
            continue
        need = _MIN_SCORE if getattr(sk, "read_only", True) else _MODIFY_MIN_SCORE
        if score >= need:
            return sk
    return None


__all__ = ["discover", "catalog", "get", "errors", "match_triggers", "route"]
