# -*- coding: utf-8 -*-
"""circuit.build — LC 集中参数滤波器综合（纯本地计算，断网可用）。

支持：低通 / 高通 / 带通 / 带阻，Butterworth（最大平坦）响应。
给出截止频率、阶数、端口阻抗，算出每个元件的电感(nH) / 电容(pF)。
"""

from __future__ import annotations

import math

from .base import ActionResult, Skill


def butterworth_g(n):
    """Butterworth 原型元件值 g1..gn（端接 g0 = g(n+1) = 1，等阻抗）。"""
    n = int(n)
    if n < 1:
        return []
    return [2.0 * math.sin((2.0 * k - 1.0) * math.pi / (2.0 * n))
            for k in range(1, n + 1)]


def _fmt(v):
    if v >= 1000.0:
        return "%.2f nH" % v if False else "%.2f" % v
    return "%.3f" % v


def build_lowpass(g, fc_ghz, z0):
    w = 2.0 * math.pi * fc_ghz * 1e9
    out = []
    for k, gk in enumerate(g, start=1):
        if k % 2 == 1:      # 串联电感
            out.append({"pos": "series", "kind": "L", "value": gk * z0 / w,
                        "unit": "nH", "scale": 1e9, "idx": k})
        else:               # 并联电容
            out.append({"pos": "shunt", "kind": "C", "value": gk / (z0 * w),
                        "unit": "pF", "scale": 1e12, "idx": k})
    return out


def build_highpass(g, fc_ghz, z0):
    w = 2.0 * math.pi * fc_ghz * 1e9
    out = []
    for k, gk in enumerate(g, start=1):
        if k % 2 == 1:      # 串联电容
            out.append({"pos": "series", "kind": "C", "value": 1.0 / (w * z0 * gk),
                        "unit": "pF", "scale": 1e12, "idx": k})
        else:               # 并联电感
            out.append({"pos": "shunt", "kind": "L", "value": z0 / (w * gk),
                        "unit": "nH", "scale": 1e9, "idx": k})
    return out


def _band_common(f1_ghz, f2_ghz):
    """带通/带阻共用的前导：中心频率、相对带宽、角频率。"""
    f0 = math.sqrt(f1_ghz * f2_ghz)
    fbw = (f2_ghz - f1_ghz) / f0
    if fbw <= 0:
        raise ValueError("带宽必须为正：f2 必须大于 f1")
    return f0, fbw, 2.0 * math.pi * f0 * 1e9


def build_bandpass(g, f1_ghz, f2_ghz, z0):
    f0, fbw, w0 = _band_common(f1_ghz, f2_ghz)
    out = []
    for k, gk in enumerate(g, start=1):
        if k % 2 == 1:      # 串联 LC
            out.append({"pos": "series", "kind": "L", "value": gk * z0 / (fbw * w0),
                        "unit": "nH", "scale": 1e9, "idx": k, "branch": "a"})
            out.append({"pos": "series", "kind": "C", "value": fbw / (w0 * gk * z0),
                        "unit": "pF", "scale": 1e12, "idx": k, "branch": "a"})
        else:               # 并联 LC
            out.append({"pos": "shunt", "kind": "C", "value": gk / (fbw * w0 * z0),
                        "unit": "pF", "scale": 1e12, "idx": k, "branch": "a"})
            out.append({"pos": "shunt", "kind": "L", "value": fbw * z0 / (w0 * gk),
                        "unit": "nH", "scale": 1e9, "idx": k, "branch": "a"})
    return out, f0, fbw


def build_bandstop(g, f1_ghz, f2_ghz, z0):
    f0, fbw, w0 = _band_common(f1_ghz, f2_ghz)
    out = []
    for k, gk in enumerate(g, start=1):
        if k % 2 == 1:      # 串联并联谐振（串联臂里的 L//C）
            out.append({"pos": "series", "kind": "L", "value": fbw * z0 / (w0 * gk),
                        "unit": "nH", "scale": 1e9, "idx": k, "branch": "p"})
            out.append({"pos": "series", "kind": "C", "value": 1.0 / (w0 * fbw * z0 * gk),
                        "unit": "pF", "scale": 1e12, "idx": k, "branch": "p"})
        else:               # 并联串联谐振
            out.append({"pos": "shunt", "kind": "L", "value": gk * z0 / (w0 * fbw),
                        "unit": "nH", "scale": 1e9, "idx": k, "branch": "s"})
            out.append({"pos": "shunt", "kind": "C", "value": fbw / (w0 * gk * z0),
                        "unit": "pF", "scale": 1e12, "idx": k, "branch": "s"})
    return out, f0, fbw


KINDS = ("lowpass", "highpass", "bandpass", "bandstop")
KIND_CN = {"lowpass": "低通", "highpass": "高通",
           "bandpass": "带通", "bandstop": "带阻"}


def compute(kind="lowpass", fc_ghz=1.0, order=3, z0=50.0,
            f1_ghz=None, f2_ghz=None):
    """综合入口，返回 dict。不依赖任何界面对象。"""
    kind = str(kind or "lowpass").lower()
    if kind in ("lp", "低通"):
        kind = "lowpass"
    elif kind in ("hp", "高通"):
        kind = "highpass"
    elif kind in ("bp", "带通"):
        kind = "bandpass"
    elif kind in ("bs", "带阻"):
        kind = "bandstop"
    if kind not in KINDS:
        raise ValueError("不支持的响应类型：%s（可选 %s）" % (kind, "/".join(KINDS)))

    order = int(order)
    if order < 1 or order > 9:
        raise ValueError("阶数必须在 1..9 之间（当前 %s）" % order)
    z0 = float(z0)
    if z0 <= 0:
        raise ValueError("端口阻抗必须为正")

    g = butterworth_g(order)
    info = {"kind": kind, "kind_cn": KIND_CN[kind], "order": order,
            "z0": z0, "g": g, "elements": [], "notes": []}

    if kind in ("lowpass", "highpass"):
        fc = float(fc_ghz or 1.0)
        if fc <= 0:
            raise ValueError("截止频率必须为正")
        info["fc_ghz"] = fc
        if kind == "lowpass":
            info["elements"] = build_lowpass(g, fc, z0)
        else:
            info["elements"] = build_highpass(g, fc, z0)
        info["band"] = "fc = %.4g GHz" % fc
    else:
        if f1_ghz is None or f2_ghz is None:
            fc = float(fc_ghz or 1.0)
            raise ValueError("带通/带阻需要同时给出 f1_ghz 与 f2_ghz，"
                             "例如 2.3 / 2.5；只给中心频率 %g 无法确定带宽" % fc)
        f1, f2 = float(f1_ghz), float(f2_ghz)
        if not (0 < f1 < f2):
            raise ValueError("需要 0 < f1 < f2（当前 f1=%g f2=%g）" % (f1, f2))
        if kind == "bandpass":
            els, f0, fbw = build_bandpass(g, f1, f2, z0)
        else:
            els, f0, fbw = build_bandstop(g, f1, f2, z0)
        info["elements"] = els
        info["f1_ghz"] = f1
        info["f2_ghz"] = f2
        info["f0_ghz"] = f0
        info["fbw"] = fbw
        info["band"] = "%.4g - %.4g GHz (f0 = %.4g, FBW = %.1f%%)" % (
            f1, f2, f0, fbw * 100.0)
        if fbw > 0.5:
            info["notes"].append("相对带宽 %.0f%% 偏宽，集中参数近似误差会变大。"
                                 % (fbw * 100.0))

    info["count"] = len(info["elements"])
    if order >= 7:
        info["notes"].append("%d 阶元件对容差敏感，实际 PCB 上建议降到 5 阶或改用分布参数。"
                             % order)
    return info


def format_table(info):
    """把元件表排成给人看的文本。"""
    lines = []
    branch = "\u0000"
    for e in info.get("elements", []):
        key = (e.get("idx"), e.get("branch"))
        if key != branch:
            branch = key
            tag = "第 %d 节" % e.get("idx", 0)
            if e.get("branch") == "p":
                tag += "（串臂并联谐振）"
            elif e.get("branch") == "s":
                tag += "（并臂串联谐振）"
            lines.append("  -- %s --" % tag)
        pos = "串联" if e.get("pos") == "series" else "并联"
        nm = "电感" if e.get("kind") == "L" else "电容"
        unit = e.get("unit", "")
        v = e.get("value", 0.0) * e.get("scale", 1.0)
        lines.append("     %s%s  %10.4f %s" % (pos, nm, v, unit))
    return "\n".join(lines)


class CircuitBuildSkill(Skill):
    name = "circuit.build"
    title = "LC 滤波器综合"
    summary = ("按截止频率、阶数、端口阻抗算出低通/高通/带通/带阻的 LC 元件值。"
               "纯本地计算，断网可用。")
    triggers = ("低通", "高通", "带通", "带阻", "滤波器", "综合",
                "阶", "lc", "filter", "butterworth", "元件值")
    read_only = False
    params = {
        "kind": {"type": "enum", "values": list(KINDS), "default": "lowpass"},
        "fc_ghz": {"type": "number", "default": 1.0},
        "f1_ghz": {"type": "number", "optional": True},
        "f2_ghz": {"type": "number", "optional": True},
        "order": {"type": "int", "default": 3, "min": 1, "max": 9},
        "z0": {"type": "number", "default": 50.0},
    }

    def preview(self, ctx=None, **kw):
        try:
            info = compute(
                kind=kw.get("kind", "lowpass"),
                fc_ghz=kw.get("fc_ghz", 1.0),
                order=kw.get("order", 3),
                z0=kw.get("z0", 50.0),
                f1_ghz=kw.get("f1_ghz"),
                f2_ghz=kw.get("f2_ghz"),
            )
        except Exception as exc:
            return ActionResult(ok=False, kind="error",
                                message="综合失败：%s" % exc)

        head = "%s滤波器  阶数 %d  端口 %.0f ohms  %s" % (
            info["kind_cn"], info["order"], info["z0"], info["band"])
        body = format_table(info)
        msg = head + "\n" + body
        if info["notes"]:
            msg += "\n注意：\n" + "\n".join("  - " + n for n in info["notes"])
        msg += "\n\n点“应用”把参数写入电路后再仿真验证。"

        patch = {"filter_kind": info["kind"], "order": info["order"],
                 "z0": info["z0"]}
        if "fc_ghz" in info:
            patch["fc_ghz"] = info["fc_ghz"]
        if "f0_ghz" in info:
            patch["f1_ghz"] = info["f1_ghz"]
            patch["f2_ghz"] = info["f2_ghz"]

        return ActionResult(ok=True, message=msg, patch=patch,
                            data={"info": info},
                            needs_confirm=True, kind="proposal")

    def apply(self, ctx, **kw):
        res = self.preview(ctx, **kw)
        if not res.ok:
            return res
        applied = []
        failed = []
        for k, v in res.patch.items():
            if ctx is not None and ctx.set_param(k, v):
                applied.append(k)
            else:
                failed.append(k)
        res.needs_confirm = False
        res.kind = "info"
        if applied:
            res.message += "\n已写入参数：%s" % ", ".join(applied)
        if failed:
            res.message += "\n未能写入：%s（界面未提供对应接入点）" % ", ".join(failed)
        return res
