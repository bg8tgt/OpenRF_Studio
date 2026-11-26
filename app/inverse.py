"""反向计算：由目标指标反求（或微调）元件参数。

四类问题：
  1. LC 谐振反算：给定谐振频率 f0 与现有 L（或 C），求另一个；
  2. 改频微调：现有 L、C 已定，目标频率变了，求需要替换的元件值与调整量；
  3. L 型阻抗匹配：给定源/负载电阻与频率，求串/并元件（低通、高通两套解）；
  4. 由 S11 反算：把反射系数换成输入阻抗，再求需要串/并的电抗。

符号约定（容易搞错，写清楚）：
  * 串联元件用电抗 X（Ω）：Z = jX；电感 X=+ωL，电容 X=−1/(ωC)
  * 并联元件用电纳 B（S）：Y = jB；电容 B=+ωC，电感 B=−1/(ωL)
  * 二者关系：X = −1/B
单位：频率 Hz、电感 nH、电容 pF、阻抗 Ω。
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

C0 = 299_792_458.0


# ---------------------------------------------------------------- 元件换算
def element_from_series_x(x_ohm: float, f_hz: float) -> Dict:
    """串联电抗 → L 或 C。Z = jX。"""
    if f_hz <= 0:
        raise ValueError("频率必须 > 0")
    w = 2 * math.pi * f_hz
    if x_ohm >= 0:
        l = x_ohm / w * 1e9
        return {"kind": "L", "value": l, "unit": "nH", "element": "串联电感",
                "x_ohm": x_ohm, "text": f"串联 L = {l:.4g} nH（X=+{x_ohm:.4g} Ω）"}
    c = -1.0 / (w * x_ohm) * 1e12
    return {"kind": "C", "value": c, "unit": "pF", "element": "串联电容",
            "x_ohm": x_ohm, "text": f"串联 C = {c:.4g} pF（X={x_ohm:.4g} Ω）"}


def element_from_shunt_b(b_siemens: float, f_hz: float) -> Dict:
    """并联电纳 → L 或 C。Y = jB。"""
    if f_hz <= 0:
        raise ValueError("频率必须 > 0")
    w = 2 * math.pi * f_hz
    if b_siemens >= 0:
        c = b_siemens / w * 1e12
        return {"kind": "C", "value": c, "unit": "pF", "element": "并联电容",
                "b_siemens": b_siemens, "text": f"并联 C = {c:.4g} pF（B=+{b_siemens:.4g} S）"}
    l = -1.0 / (w * b_siemens) * 1e9
    return {"kind": "L", "value": l, "unit": "nH", "element": "并联电感",
            "b_siemens": b_siemens, "text": f"并联 L = {l:.4g} nH（B={b_siemens:.4g} S）"}


# ---------------------------------------------------------------- 1. LC 谐振
def lc_resonance(f_hz: Optional[float] = None,
                 l_nh: Optional[float] = None,
                 c_pf: Optional[float] = None) -> Dict:
    """f0 = 1/(2π√(LC))；三选二求第三个。"""
    if sum(x is not None for x in (f_hz, l_nh, c_pf)) < 2:
        raise ValueError("至少给出两个量（频率 / 电感 / 电容）")
    for name, v in (("频率", f_hz), ("电感", l_nh), ("电容", c_pf)):
        if v is not None and v <= 0:
            raise ValueError(f"{name}必须 > 0")
    w0 = 2 * math.pi * f_hz if f_hz else None
    if f_hz and l_nh and c_pf:
        f_actual = 1.0 / (2 * math.pi * math.sqrt(l_nh * 1e-9 * c_pf * 1e-12))
        return {"f_hz": f_actual, "l_nh": l_nh, "c_pf": c_pf,
                "note": f"三个量都给：实际谐振 {f_actual/1e9:.6g} GHz"
                        f"（与给定频率偏差 {100*(f_actual-f_hz)/f_hz:+.3f}%）"}
    if l_nh and c_pf:
        f_actual = 1.0 / (2 * math.pi * math.sqrt(l_nh * 1e-9 * c_pf * 1e-12))
        return {"f_hz": f_actual, "l_nh": l_nh, "c_pf": c_pf,
                "note": "由 L、C 求谐振频率"}
    if f_hz and l_nh:
        c = 1.0 / (w0 * w0 * l_nh * 1e-9) * 1e12
        return {"f_hz": f_hz, "l_nh": l_nh, "c_pf": c,
                "note": "给定 f0 与 L，求所需 C"}
    l = 1.0 / (w0 * w0 * c_pf * 1e-12) * 1e9
    return {"f_hz": f_hz, "l_nh": l, "c_pf": c_pf,
            "note": "给定 f0 与 C，求所需 L"}


# ---------------------------------------------------------------- 2. 改频微调
def retune_lc(current_l_nh: float, current_c_pf: float, target_f_hz: float,
              keep: str = "L") -> Dict:
    """现有 LC 谐振在 f_now，要调到 target_f：保留一个、求另一个新值。"""
    if current_l_nh <= 0 or current_c_pf <= 0:
        raise ValueError("现有 L、C 必须 > 0")
    if target_f_hz <= 0:
        raise ValueError("目标频率必须 > 0")
    keep = keep.upper()
    if keep not in ("L", "C"):
        raise ValueError("keep 只能是 'L' 或 'C'")
    f_now = 1.0 / (2 * math.pi * math.sqrt(current_l_nh * 1e-9 * current_c_pf * 1e-12))
    ratio = (f_now / target_f_hz) ** 2      # 需要的新旧 LC 乘积比
    out = {"f_now_hz": f_now, "f_target_hz": target_f_hz, "keep": keep}
    if keep == "L":
        c_new = current_c_pf * ratio
        out.update({"l_nh": current_l_nh, "c_pf": c_new,
                    "delta_pf": c_new - current_c_pf, "ratio": ratio,
                    "note": f"保留 L={current_l_nh:g} nH：C 由 {current_c_pf:.4g} pF "
                            f"改为 {c_new:.4g} pF（{'+' if c_new>=current_c_pf else ''}"
                            f"{c_new-current_c_pf:.4g} pF）"})
    else:
        l_new = current_l_nh * ratio
        out.update({"l_nh": l_new, "c_pf": current_c_pf,
                    "delta_nh": l_new - current_l_nh, "ratio": ratio,
                    "note": f"保留 C={current_c_pf:g} pF：L 由 {current_l_nh:.4g} nH "
                            f"改为 {l_new:.4g} nH"})
    f_check = 1.0 / (2 * math.pi * math.sqrt(out["l_nh"] * 1e-9 * out["c_pf"] * 1e-12))
    out["f_check_hz"] = f_check
    out["error_hz"] = f_check - target_f_hz
    return out


# ---------------------------------------------------------------- 3. L 型匹配
def l_network_match(rs: float, rl: float, f_hz: float) -> Dict:
    """源阻 rs → 负载 rl 的 L 型匹配（并联元件接 R_high 侧，串联元件接 R_low 侧）。

        Q = √(R_high/R_low − 1)
        并联电抗幅值 |Xp| = R_high/Q     → 并联电纳 Bp = ±1/|Xp|
        串联电抗幅值 |Xs| = Q·R_low
    低通：并联 C（B=+1/|Xp|）+ 串联 L（X=+|Xs|）
    高通：并联 L（B=−1/|Xp|）+ 串联 C（X=−|Xs|）
    """
    if rs <= 0 or rl <= 0:
        raise ValueError("电阻必须 > 0")
    if f_hz <= 0:
        raise ValueError("频率必须 > 0")
    if abs(rs - rl) < 1e-12:
        return {"identity": True, "q": 0.0, "solutions": [],
                "note": "源与负载相等，无需匹配"}
    r_high, r_low = max(rs, rl), min(rs, rl)
    q = math.sqrt(r_high / r_low - 1.0)
    xp = r_high / q
    xs = q * r_low
    bp = 1.0 / xp
    low = {"name": "低通型（并联 C + 串联 L）",
           "shunt": element_from_shunt_b(+bp, f_hz),
           "series": element_from_series_x(+xs, f_hz)}
    high = {"name": "高通型（并联 L + 串联 C）",
            "shunt": element_from_shunt_b(-bp, f_hz),
            "series": element_from_series_x(-xs, f_hz)}
    # 并联元件接在"高阻那一侧"：rl > rs 时在负载端，rs > rl 时在源端（端口节点）
    shunt_side = "load" if rl > rs else "source"
    side_cn = "负载端" if shunt_side == "load" else "源端（端口节点）"
    return {"identity": False, "q": q, "r_high": r_high, "r_low": r_low,
            "xp_ohm": xp, "xs_ohm": xs, "solutions": [low, high],
            "shunt_side": shunt_side,
            "note": f"Q={q:.4f}；并联元件接在 {r_high:g} Ω 侧（{side_cn}），"
                    f"串联元件接在 {r_low:g} Ω 侧"}


# ---------------------------------------------------------------- 4. 由 S11 反算
def impedance_from_s11(s11: complex, z0: float = 50.0) -> complex:
    if abs(1 - s11) < 1e-15:
        raise ValueError("Γ=1（全反射），输入阻抗无定义")
    return z0 * (1 + s11) / (1 - s11)


def match_from_s11(s11: complex, f_hz: float, z0: float = 50.0) -> Dict:
    """由 S11 反算：单串联或单并联元件能否把输入拉回 Z0。"""
    zin = impedance_from_s11(s11, z0)
    yin = 1.0 / zin if zin != 0 else complex(1e12, 0)
    out = {"zin": zin, "zin_norm": zin / z0, "yin": yin,
           "vswr": ((1 + abs(s11)) / (1 - abs(s11))) if abs(s11) < 1 else float("inf"),
           "series": None, "shunt": None, "notes": []}
    if abs(zin.real - z0) / z0 < 0.2 and abs(zin.imag) > 1e-9:
        out["series"] = element_from_series_x(-zin.imag, f_hz)
        out["notes"].append("串联方案：实部接近 Z0，串一个反向电抗即可抵消虚部")
    else:
        out["notes"].append("串联方案不适用：输入阻抗实部偏离 Z0 较多")
    if abs(yin.real - 1.0 / z0) / (1.0 / z0) < 0.2 and abs(yin.imag) > 1e-15:
        out["shunt"] = element_from_shunt_b(-yin.imag, f_hz)
        out["notes"].append("并联方案：导纳实部接近 1/Z0，并一个反向电纳即可抵消")
    else:
        out["notes"].append("并联方案不适用：输入导纳实部偏离 1/Z0 较多")
    if not out["series"] and not out["shunt"]:
        out["notes"].append("两种单元件方案都不适用，建议用 L 型匹配网络（见「阻抗匹配」页）")
    return out


# ---------------------------------------------------------------- 5. 滤波器改频
def scale_filter_values(items: List[Dict], f_old_hz: float, f_new_hz: float) -> List[Dict]:
    """把低通/带通综合结果整体改频：L、C 同比例缩放 k = f_old/f_new。"""
    if f_old_hz <= 0 or f_new_hz <= 0:
        raise ValueError("频率必须 > 0")
    k = f_old_hz / f_new_hz
    out = []
    for it in items:
        d = dict(it)
        d["value_old"] = float(it["value"])
        d["value"] = float(it["value"]) * k
        out.append(d)
    return out