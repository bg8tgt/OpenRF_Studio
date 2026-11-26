"""单位系统：长度（mm/mil/inch）、频率（Hz/kHz/MHz/GHz）、元件值。

* 长度：mm / mil / inch
* 频率：Hz / kHz / MHz / GHz
* 阻抗：Ω
* 元件值：nH / pF / Ω（工程常用量级）
"""
from __future__ import annotations

MM_PER_INCH = 25.4
MM_PER_MIL = 0.0254

LENGTH_UNITS = {"mm": 1.0, "mil": MM_PER_MIL, "inch": MM_PER_INCH, "cm": 10.0}
FREQ_UNITS = {"Hz": 1.0, "kHz": 1e3, "MHz": 1e6, "GHz": 1e9}
CAP_UNITS = {"pF": 1e-12, "nF": 1e-9, "uF": 1e-6, "fF": 1e-15}
IND_UNITS = {"nH": 1e-9, "uH": 1e-6, "mH": 1e-3, "pH": 1e-12}


def length_to_mm(value: float, unit: str) -> float:
    unit = unit.strip()
    if unit not in LENGTH_UNITS:
        raise ValueError(f"不支持的长度单位：{unit}（可选 {list(LENGTH_UNITS)}）")
    return value * LENGTH_UNITS[unit]


def length_from_mm(value_mm: float, unit: str) -> float:
    unit = unit.strip()
    if unit not in LENGTH_UNITS:
        raise ValueError(f"不支持的长度单位：{unit}")
    return value_mm / LENGTH_UNITS[unit]


def freq_to_hz(value: float, unit: str) -> float:
    unit = unit.strip()
    if unit not in FREQ_UNITS:
        raise ValueError(f"不支持的频率单位：{unit}")
    return value * FREQ_UNITS[unit]


def freq_from_hz(value_hz: float, unit: str) -> float:
    return value_hz / FREQ_UNITS[unit.strip()]


def freq_to_disp(value_hz: float, unit: str = "MHz") -> float:
    """频率（Hz）→ 显示单位下的数值。"""
    return freq_from_hz(value_hz, unit)


def disp_to_freq(value: float, unit: str = "MHz") -> float:
    """显示单位下的数值 → 频率（Hz）。"""
    return freq_to_hz(value, unit)


def fmt_freq(value_hz: float, unit: str = "MHz") -> str:
    return f"{freq_from_hz(value_hz, unit):.6g} {unit}"


def fmt_freq_smart(value_hz: float, unit: str = "MHz", digits: int = 4) -> str:
    """按当前单位显示；数值离该单位量级太远时补一个换算读数。

    选 MHz 时，1.7 kHz 会显示成 "0.001732 MHz（1.732 kHz）"：
    既尊重用户选的单位，也不会只剩一串零。
    """
    v = freq_from_hz(value_hz, unit)
    if v and (abs(v) < 0.01 or abs(v) >= 1e5):
        auto = shortest_freq_unit(value_hz)
        if auto != unit:
            return ("%.*g %s（%.*g %s）"
                    % (digits, v, unit, digits, freq_from_hz(value_hz, auto), auto))
    return "%.*g %s" % (digits, v, unit)


def shortest_freq_unit(value_hz: float) -> str:
    """自动挑一个读数好看的单位。"""
    a = abs(value_hz)
    if a >= 1e9:
        return "GHz"
    if a >= 1e6:
        return "MHz"
    if a >= 1e3:
        return "kHz"
    return "Hz"
