# -*- coding: utf-8 -*-
"""阻抗匹配技能：L 型（两元件）匹配网络综合。

只做 L 型。T 型 / Pi 型属于三元件方案，本版不实现，调用方不要当作已支持。
所有结果只在设计频率上严格成立——这是 L 型的物理限制，不是实现缺陷。
"""

from __future__ import annotations

import math

from .base import ActionResult, Skill


# ---------------------------------------------------------------- 纯函数

def zin(load, elements):
    """从负载侧向源侧逐级变换，返回输入端阻抗（复数）。

    elements[0] 最靠近源，elements[-1] 最靠近负载。
    每个元件：{"pos": "series"|"shunt", "x": 电抗 ohms}。
    """
    z = complex(float(load[0]), float(load[1]))
    for e in reversed(elements):
        x = float(e.get("x", 0.0))
        if abs(x) < 1e-15:
            continue
        if e.get("pos") == "series":
            z = z + complex(0.0, x)
        else:
            z = 1.0 / (1.0 / z + 1.0 / complex(0.0, x))
    return z


def _element(pos, x, omega, note=""):
    """把一个电抗值翻译成具体的 L 或 C。"""
    if abs(x) < 1e-12:
        return None
    if x > 0:
        value = x / omega          # 亨利
        kind, unit, scale = "L", "nH", 1e9
        label = "电感"
    else:
        value = -1.0 / (omega * x)  # 法拉
        kind, unit, scale = "C", "pF", 1e12
        label = "电容"
    return {
        "pos": pos,
        "kind": kind,
        "label": label,
        "x": x,
        "value": value,
        "unit": unit,
        "scale": scale,
        "note": note,
    }


def design(z0=50.0, rl=50.0, xl=0.0, freq_ghz=1.0):
    """算一个 L 型匹配网络。

    rl/xl 是负载阻抗的实部/虚部（ohms），z0 是源阻抗（默认 50）。
    返回 dict；失败时 ok=False 且带 reason。
    """
    z0 = float(z0)
    rl = float(rl)
    xl = float(xl)
    freq_ghz = float(freq_ghz)

    if z0 <= 0:
        return {"ok": False, "reason": "源阻抗必须为正数。"}
    if rl <= 0:
        return {"ok": False, "reason": "负载实部必须为正数（无源负载）。"}
    if freq_ghz <= 0:
        return {"ok": False, "reason": "设计频率必须为正数。"}

    omega = 2.0 * math.pi * freq_ghz * 1e9
    notes = []
    raw = []

    if abs(xl) > 1e-9:
        raw.append(("series", -xl, "抵消负载电抗"))
        notes.append("负载带 %.3f ohms 电抗，先用串联 %.3f ohms 抵消；"
                     "这是窄带做法，离开设计频率后补偿会失效。"
                     % (xl, -xl))

    if abs(rl - z0) <= 1e-9 * max(1.0, z0):
        shape = "already_matched"
        q = 0.0
    elif rl > z0:
        shape = "step_down"
        q = math.sqrt(rl / z0 - 1.0)
        # 串 C 在源侧，并 L 靠近负载
        raw.insert(0, ("series", -q * z0, "串联支路"))
        raw.insert(1, ("shunt", rl / q, "并联支路"))
    else:
        shape = "step_up"
        q = math.sqrt(z0 / rl - 1.0)
        # 并 C 在源侧，串 L 靠近负载
        raw.insert(0, ("shunt", -z0 / q, "并联支路"))
        raw.insert(1, ("series", q * rl, "串联支路"))

    elements = []
    for pos, x, note in raw:
        el = _element(pos, x, omega, note)
        if el is None:
            continue
        el["idx"] = len(elements)
        elements.append(el)

    peak_v = 0.0
    peak_i = 0.0
    if shape != "already_matched":
        # 并联臂上电压高、串联臂上电流大
        peak_v = math.sqrt(z0 * rl) if shape == "step_down" else math.sqrt(z0 * rl)
        peak_i = math.sqrt(z0 / rl) if shape == "step_down" else math.sqrt(rl / z0)

    z_in = zin((rl, xl), elements)
    gamma = 0.0
    denom = abs(complex(z0, 0.0) + z_in)
    if denom > 1e-15:
        gamma = abs((z_in - complex(z0, 0.0)) / (complex(z0, 0.0) + z_in))

    if shape == "already_matched":
        notes.append("负载已经等于源阻抗，不需要匹配网络。")
    else:
        notes.append("L 型匹配只在设计频率 %.4g GHz 上严格成立，"
                     "带宽约为 f/Q（Q = %.3f）。" % (freq_ghz, q))
        notes.append("若负载实部未知，先用万用表/网络分析仪测出再算。")

    return {
        "ok": True,
        "shape": shape,
        "q": q,
        "z0": z0,
        "rl": rl,
        "xl": xl,
        "freq_ghz": freq_ghz,
        "elements": elements,
        "zin": (z_in.real, z_in.imag),
        "gamma": gamma,
        "notes": notes,
    }


def format_table(info):
    if not info.get("ok"):
        return "匹配网络综合失败：" + str(info.get("reason", "未知原因"))
    if info["shape"] == "already_matched":
        return "负载 %.3f ohms 已等于源阻抗，无需匹配。" % info["rl"]

    lines = []
    lines.append("负载 %.4f %+.4f j ohms  ->  源 %.3g ohms，Q = %.4f"
                 % (info["rl"], info["xl"], info["z0"], info["q"]))
    lines.append("元件（由上到下 = 由源到负载）：")
    for e in info["elements"]:
        pos = "串联" if e["pos"] == "series" else "并联"
        v = e.get("value", 0.0) * e.get("scale", 1.0)
        lines.append("  %d. %s%-4s %10.4f %-3s   (%.4f ohms)"
                     % (e["idx"] + 1, pos, e["label"], v, e["unit"], e["x"]))
    zr, zi = info["zin"]
    lines.append("校验：Zin = %.4f %+.4f j ohms，|Gamma| = %.2e"
                 % (zr, zi, info["gamma"]))
    if info["notes"]:
        lines.append("注意：")
        for nt in info["notes"]:
            lines.append("  - " + nt)
    return chr(10).join(lines)


# ---------------------------------------------------------------- 技能

class MatchDesignSkill(Skill):
    name = "match.design"
    title = "L 型阻抗匹配"
    summary = ("给定负载阻抗与工作频率，算出两元件 L 型匹配网络的电容/电感值。"
               "支持复数负载（先用串联电抗抵消虚部）。纯本地计算。")
    triggers = ("匹配", "阻抗匹配", "l型", "l 型", "l-match", "match",
                "50欧", "50 欧", "负载阻抗", "调匹配", "smith", "史密斯")
    read_only = False
    params = {
        "rl": {"type": "number", "default": 100.0},
        "xl": {"type": "number", "default": 0.0},
        "z0": {"type": "number", "default": 50.0},
        "freq_ghz": {"type": "number", "default": 1.0},
    }

    def _resolve(self, ctx, kw):
        def pick(key, default):
            if kw.get(key) is not None:
                try:
                    return float(kw[key])
                except (TypeError, ValueError):
                    pass
            if ctx is not None:
                try:
                    v = ctx.get_param(key)
                    if v is not None:
                        return float(v)
                except Exception:
                    pass
            return default

        return (pick("z0", 50.0), pick("rl", 100.0), pick("xl", 0.0),
                pick("freq_ghz", 1.0))

    def preview(self, ctx=None, **kw):
        try:
            z0, rl, xl, fg = self._resolve(ctx, kw)
        except Exception as exc:
            return ActionResult(ok=False, kind="error",
                                message="参数读取失败：%s" % exc)
        try:
            info = design(z0=z0, rl=rl, xl=xl, freq_ghz=fg)
        except Exception as exc:
            return ActionResult(ok=False, kind="error",
                                message="匹配综合失败：%s" % exc)

        if not info.get("ok"):
            return ActionResult(ok=False, kind="error",
                                message="匹配综合失败：" + str(info.get("reason")),
                                data={"info": info})

        msg = format_table(info)
        if info["shape"] != "already_matched":
            msg += chr(10) + chr(10) + "点“应用”把这些值写进电路后再仿真验证。"
        return ActionResult(ok=True, message=msg,
                            patch={"z0": z0, "rl": rl, "xl": xl,
                                   "freq_ghz": fg} if info["shape"] !=
                                  "already_matched" else {},
                            data={"info": info},
                            needs_confirm=(info["shape"] != "already_matched"),
                            kind="proposal" if info["shape"] != "already_matched"
                            else "info")

    def apply(self, ctx, **kw):
        res = self.preview(ctx, **kw)
        if not res.ok or not res.patch:
            return res
        applied, failed = [], []
        for k, v in res.patch.items():
            if ctx is not None and ctx.set_param(k, v):
                applied.append(k)
            else:
                failed.append(k)
        res.needs_confirm = False
        res.kind = "info"
        if applied:
            res.message += chr(10) + "已写入参数：%s" % ", ".join(applied)
        if failed:
            res.message += (chr(10) + "未能写入：%s（界面未提供对应接入点）"
                            % ", ".join(failed))
        return res
