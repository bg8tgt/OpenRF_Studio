# -*- coding: utf-8 -*-
"""曲线解读技能：从扫频结果里读出通带、带宽、插损与回波损耗。

纯数组处理，不依赖 numpy、不依赖 GUI，断网可用。
所有计算都在 analyze() 里完成，界面层只负责把结论念出来。
"""

from __future__ import annotations


from .base import ActionResult, Skill

# ---------------------------------------------------------------- 纯函数

def _floats(seq):
    out = []
    for v in seq or []:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(float("nan"))
    return out


def _bad(v):
    return v != v or v in (float("inf"), float("-inf"))


def _interp(x0, y0, x1, y1, yt):
    """在两点之间线性求 y=yt 对应的 x；退化时返回中点，永不抛异常。"""
    if _bad(y0) or _bad(y1) or _bad(x0) or _bad(x1) or y1 == y0:
        return 0.5 * (x0 + x1)
    t = (yt - y0) / (y1 - y0)
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    return x0 + t * (x1 - x0)


def _runs(mask):
    """返回 mask 中连续为 True 的闭区间 [(start, end), ...]。"""
    runs = []
    start = None
    for i, flag in enumerate(mask):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(mask) - 1))
    return runs


def _fmt(value, unit, nd=3):
    if value is None or _bad(value):
        return "无法确定"
    return ("%." + str(nd) + "f %s") % (value, unit)


def analyze(freq_ghz, s21_db, s11_db=None, drop_db=3.0):
    """读出一条 S21 曲线。

    返回 dict；失败时 ok=False 且带 reason。
    约定：s21_db 是传输系数幅度 dB（通带内接近 0，阻带为负）。
    """
    f = _floats(freq_ghz)
    s21 = _floats(s21_db)
    n = min(len(f), len(s21))
    if n < 3:
        return {"ok": False, "reason": "数据点不足（至少需要 3 个频点）。"}

    f = f[:n]
    s21 = s21[:n]
    s11 = _floats(s11_db)[:n] if s11_db else []

    # 只保留两侧都有效的点
    keep = [i for i in range(n) if not _bad(f[i]) and not _bad(s21[i])]
    if len(keep) < 3:
        return {"ok": False, "reason": "有效频点不足（大量 NaN/Inf）。"}
    f = [f[i] for i in keep]
    s21 = [s21[i] for i in keep]
    if s11:
        s11 = [s11[i] for i in keep]
    n = len(f)

    peak = max(s21)
    thr = peak - abs(float(drop_db))
    runs = _runs([v >= thr for v in s21])
    if not runs:
        return {"ok": False, "reason": "整段扫描都没有达到 -%.0f dB 判据。" % abs(drop_db),
                "peak_db": round(peak, 4)}

    # 取最宽的一段作为通带
    i0, i1 = max(runs, key=lambda r: (r[1] - r[0], -r[0]))
    closed_low = i0 > 0
    closed_high = i1 < n - 1

    if closed_low:
        f_lo = _interp(f[i0 - 1], s21[i0 - 1], f[i0], s21[i0], thr)
    else:
        f_lo = f[0]
    if closed_high:
        f_hi = _interp(f[i1], s21[i1], f[i1 + 1], s21[i1 + 1], thr)
    else:
        f_hi = f[n - 1]

    band_vals = s21[i0:i1 + 1]
    ripple = max(band_vals) - min(band_vals)

    if closed_low and not closed_high:
        shape, shape_cn = "highpass", "高通"
    elif not closed_low and closed_high:
        shape, shape_cn = "lowpass", "低通"
    elif closed_low and closed_high:
        shape, shape_cn = "bandpass", "带通"
    else:
        shape, shape_cn = "allpass", "全通（通带覆盖整段扫描）"

    notes = []
    if not closed_low:
        notes.append("低频边界落在扫描起始点 %.4g GHz 之外，"
                     "真实截止频率比这个值更低。" % f[0])
    if not closed_high:
        notes.append("高频边界落在扫描终止点 %.4g GHz 之外，"
                     "真实截止频率比这个值更高。" % f[n - 1])
    if len(runs) > 1:
        notes.append("曲线有 %d 段超过判据，已取最宽的一段（%.4g~%.4g GHz）。"
                     % (len(runs), f_lo, f_hi))

    # ---- S11 ----
    rl_worst = rl_best = None
    s11_mode = None
    if s11 and len(s11) >= n:
        seg = [v for v in s11[i0:i1 + 1] if not _bad(v)]
        if seg:
            srt = sorted(seg)
            med = srt[len(srt) // 2]
            # 负值 = S 参数 dB 约定；正值 = 回波损耗约定
            s11_mode = "sparam_db" if med < 0 else "return_loss_db"
            if s11_mode == "sparam_db":
                rl_best = -min(seg)
                rl_worst = -max(seg)
            else:
                rl_best = max(seg)
                rl_worst = min(seg)

    return {
        "ok": True,
        "shape": shape,
        "shape_cn": shape_cn,
        "n_points": n,
        "peak_db": peak,
        "insertion_loss_db": -peak,
        "threshold_db": thr,
        "f_low_ghz": f_lo,
        "f_high_ghz": f_hi,
        "closed_low": closed_low,
        "closed_high": closed_high,
        "f_center_ghz": (0.5 * (f_lo + f_hi)) if (closed_low and closed_high) else None,
        "bandwidth_ghz": (f_hi - f_lo) if (closed_low and closed_high) else None,
        "ripple_db": ripple,
        "return_loss_best_db": rl_best,
        "return_loss_worst_db": rl_worst,
        "s11_convention": s11_mode,
        "notes": notes,
    }


def format_report(info):
    if not info.get("ok"):
        return "曲线解读失败：" + str(info.get("reason", "未知原因"))

    lines = []
    lines.append("响应类型：%s" % info["shape_cn"])
    lines.append("通带内最高增益：%.3f dB（插损 %.3f dB）"
                 % (info["peak_db"], info["insertion_loss_db"]))
    lines.append("判据：%.3f dB（相对峰值 -%.0f dB）"
                 % (info["threshold_db"], info["peak_db"] - info["threshold_db"]))

    if info["closed_low"]:
        lines.append("下限频率：%.4f GHz" % info["f_low_ghz"])
    else:
        lines.append("下限频率：开区间（落在扫描起点之外，实际更低）")
    if info["closed_high"]:
        lines.append("上限频率：%.4f GHz" % info["f_high_ghz"])
    else:
        lines.append("上限频率：开区间（落在扫描终点之外，实际更高）")

    if info["bandwidth_ghz"] is not None:
        lines.append("中心频率：%.4f GHz" % info["f_center_ghz"])
        lines.append("带宽（-%.0f dB）：%.4f GHz"
                     % (info["peak_db"] - info["threshold_db"],
                        info["bandwidth_ghz"]))
    else:
        lines.append("带宽：两端未同时落在扫描范围内，无法给出中心频率与带宽")

    lines.append("通带起伏：%.3f dB" % info["ripple_db"])

    if info["return_loss_worst_db"] is not None:
        conv = "S11(dB)" if info["s11_convention"] == "sparam_db" else "回波损耗"
        lines.append("回波损耗（%s）：最好 %.2f dB / 最差 %.2f dB"
                     % (conv, info["return_loss_best_db"],
                        info["return_loss_worst_db"]))
    else:
        lines.append("回波损耗：未提供 S11 数据")

    if info["notes"]:
        lines.append("注意：")
        for nt in info["notes"]:
            lines.append("  - " + nt)
    return chr(10).join(lines)


# ---------------------------------------------------------------- 技能

class PlotExplainSkill(Skill):
    name = "plot.explain"
    title = "曲线解读"
    summary = ("读取当前 S21/S11 扫频结果，给出通带类型、-3 dB 带宽、"
               "中心频率、通带起伏与回波损耗。只读，不改电路。")
    triggers = ("解读", "分析曲线", "带宽", "3db", "通带", "阻带",
                "插入损耗", "插损", "回波损耗", "驻波", "看曲线",
                "bandwidth", "cutoff", "怎么读", "结果如何", "性能怎么样")
    read_only = True
    params = {
        "drop_db": {"type": "number", "default": 3.0},
    }

    def _sweep_from_ctx(self, ctx):
        if ctx is None:
            return None
        try:
            return ctx.sweep_result()
        except Exception:
            return None

    def preview(self, ctx=None, **kw):
        sweep = kw.get("sweep") or self._sweep_from_ctx(ctx)
        if not sweep:
            return ActionResult(
                ok=False, kind="error",
                message=("还没有可解读的数据。请先在“矩形图”页跑一次频率扫描"
                         "（或先让我设计并仿真一个电路），再问我曲线怎么样。"))

        f = sweep.get("freq_ghz") or []
        s21 = sweep.get("s21_db") or []
        s11 = sweep.get("s11_db") or None
        if not f or not s21:
            return ActionResult(ok=False, kind="error",
                                message="扫描结果里没有 S21 数组，无法解读。")

        try:
            info = analyze(f, s21, s11, drop_db=float(kw.get("drop_db", 3.0)))
        except Exception as exc:
            return ActionResult(ok=False, kind="error",
                                message="解读过程出错：%s" % exc)

        if not info.get("ok"):
            return ActionResult(ok=False, kind="error",
                                message="曲线解读失败：" + str(info.get("reason")),
                                data={"info": info})

        return ActionResult(ok=True, message=format_report(info),
                            data={"info": info}, kind="info")

    def apply(self, ctx, **kw):
        return ActionResult(ok=True, kind="info",
                            message="曲线解读是只读分析，不需要应用到电路。")
