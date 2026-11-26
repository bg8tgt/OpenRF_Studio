# -*- coding: utf-8 -*-
"""从自然语言里抽取技能参数（纯本地正则，不依赖模型、不联网）。

设计取舍：参数解析必须离线可复现，否则"断网也能用"的承诺就破了。
解析不全时一律退回技能自己的默认值，绝不编造。
"""
from __future__ import annotations

import re

_NUM = r"([0-9]+(?:\.[0-9]+)?)"
_UNIT = r"(ghz|gz|g|mhz|m|khz|k)(?![a-z])"


def _num(s):
    try:
        return float(s)
    except Exception:
        return None


def freqs_ghz(text):
    """抽出文本里所有带单位的频率，换算成 GHz，按出现顺序返回。"""
    out = []
    for m in re.finditer(_NUM + r"\s*" + _UNIT, text or "", re.I):
        v = _num(m.group(1))
        if v is None:
            continue
        u = m.group(2).lower()
        if u in ("ghz", "gz", "g"):
            out.append(v)
        elif u in ("mhz", "m"):
            out.append(v * 1e-3)
        else:
            out.append(v * 1e-6)
    return out


def band_pair_ghz(text):
    """“2.0 到 2.5GHz”这类写法：单位只写在第二个数上也能解析。"""
    m = re.search(_NUM + r"\s*(?:到|至|-|~|—|–)\s*" + _NUM + r"\s*" + _UNIT,
                  text or "", re.I)
    if not m:
        return None
    a, b = _num(m.group(1)), _num(m.group(2))
    u = m.group(3).lower()
    if a is None or b is None:
        return None
    k = 1.0 if u in ("ghz", "gz", "g") else (1e-3 if u in ("mhz", "m") else 1e-6)
    a, b = a * k, b * k
    return (a, b) if a < b else (b, a)


def filter_kind(text):
    t = (text or "").lower()
    if "带阻" in t or "bandstop" in t or "陷波" in t:
        return "bandstop"
    if "带通" in t or "bandpass" in t:
        return "bandpass"
    if "高通" in t or "highpass" in t:
        return "highpass"
    if "低通" in t or "lowpass" in t:
        return "lowpass"
    return None


def order(text):
    t = text or ""
    for pat in (r"([0-9]+)\s*阶", r"阶数\s*[:：=]?\s*([0-9]+)",
                r"order\s*[:：=]?\s*([0-9]+)"):
        m = re.search(pat, t, re.I)
        if m:
            n = _num(m.group(1))
            if n and 1 <= n <= 12:
                return int(n)
    return None


def z0(text):
    t = text or ""
    for pat in (r"z0\s*[:：=]?\s*" + _NUM, r"阻抗\s*" + _NUM,
                _NUM + r"\s*(?:Ω|ohm|欧)"):
        m = re.search(pat, t, re.I)
        if m:
            v = _num(m.group(1))
            if v and 1 <= v <= 1000:
                return v
    return None


def pair_ohms(text):
    """“50 欧到 100 欧”这种 源->负载 写法，返回 (源, 负载)。"""
    m = re.search(_NUM + r"\s*(?:Ω|欧)\s*(?:到|至|->|→|~)\s*" + _NUM, text or "")
    if not m:
        return None, None
    a, b = _num(m.group(1)), _num(m.group(2))
    if a and b:
        return a, b
    return None, None


def source_z0(text):
    """只认明确指向“源/系统/匹配目标”的阻抗，避免把负载当成源。"""
    t = text or ""
    for pat in (r"(?:源阻抗|源电阻|源)\s*[:：=]?\s*" + _NUM,
                r"(?:匹配到|匹配至|匹配为|matching to)\s*" + _NUM,
                _NUM + r"\s*(?:Ω|欧|ohm)\s*(?:的)?(?:源|系统)"):
        m = re.search(pat, t, re.I)
        if m:
            v = _num(m.group(1))
            if v and 1 <= v <= 1000:
                return v
    return None


def load_rl(text):
    t = text or ""
    for pat in (r"负载\s*[:：=]?\s*" + _NUM, r"rl\s*[:：=]?\s*" + _NUM,
                _NUM + r"\s*(?:Ω|欧|ohm)\s*(?:的)?负载"):
        m = re.search(pat, t, re.I)
        if m:
            v = _num(m.group(1))
            if v and v > 0:
                return v
    return None


def load_xl(text):
    t = text or ""
    m = re.search(r"([+-]?[0-9]+(?:\.[0-9]+)?)\s*j", t, re.I)
    if m:
        v = _num(m.group(1))
        return v if v is not None else 0.0
    if "容性" in t:
        return -25.0
    if "感性" in t:
        return 25.0
    return None


def parse(text, skill_name):
    """按技能名抽取 kwargs；拿不到的键直接不出现，交给技能默认值。"""
    kw = {}
    if skill_name == "circuit.build":
        k = filter_kind(text)
        if k:
            kw["kind"] = k
        n = order(text)
        if n:
            kw["order"] = n
        z = z0(text)
        if z:
            kw["z0"] = z
        pair = band_pair_ghz(text)
        if pair and kw.get("kind") in ("bandpass", "bandstop"):
            kw["f1_ghz"], kw["f2_ghz"] = pair
            kw["fc_ghz"] = (pair[0] + pair[1]) / 2.0
        else:
            fs = freqs_ghz(text)
            if fs:
                if kw.get("kind") == "bandpass" and len(fs) >= 2:
                    kw["f1_ghz"], kw["f2_ghz"] = fs[0], fs[1]
                    kw["fc_ghz"] = (fs[0] + fs[1]) / 2.0
                else:
                    kw["fc_ghz"] = fs[0]
    elif skill_name == "match.design":
        a, b = pair_ohms(text)
        if a is not None:
            kw["z0"], kw["rl"] = a, b
        else:
            z = source_z0(text)
            if z:
                kw["z0"] = z
            rl = load_rl(text)
            if rl:
                kw["rl"] = rl
        xl = load_xl(text)
        if xl is not None:
            kw["xl"] = xl
        fs = freqs_ghz(text)
        if fs:
            kw["freq_ghz"] = fs[0]
    return kw
