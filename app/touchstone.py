"""Touchstone v1.0 读写（公开标准，与任何商业实现无关）。

支持：
  * 1..N 端口 .sNp
  * 频率单位 Hz/kHz/MHz/GHz
  * 数据格式 MA（线性幅度+角度）、DB（dB+角度）、RI（实部+虚部）
  * 参考阻抗 R
不支持（明确报错，不静默丢弃）：噪声参数块、混合模 S 参数。
"""
from __future__ import annotations

import cmath
import math
import os
import re
from typing import List, Sequence, Tuple

Complex = complex

_OPT = re.compile(r"^\s*#\s*(.*)$", re.IGNORECASE)


class TouchstoneError(ValueError):
    pass


class TouchstoneData(tuple):
    """read_touchstone 返回值：可像旧版 4 元组一样解包，另带 warning 字段。"""

    def __new__(cls, freqs, data, z0, nport, warning: str = ""):
        obj = super().__new__(cls, (freqs, data, z0, nport))
        obj.warning = warning
        return obj


def _unit_scale(unit: str) -> float:
    unit = unit.upper()
    return {"HZ": 1.0, "KHZ": 1e3, "MHZ": 1e6, "GHZ": 1e9}[unit]


def write_touchstone(path: str, freqs_hz: Sequence[float],
                     s: Sequence[Sequence[Sequence[Complex]]],
                     z0: float = 50.0, fmt: str = "MA",
                     comment: str = "") -> None:
    """把 S 参数写成 Touchstone 文件。s[k][i][j]，k=频点。"""
    n = len(s[0]) if s else 0
    if n == 0:
        raise ValueError("空的 S 参数矩阵")
    if len(s) != len(freqs_hz):
        raise TouchstoneError(
            f"频点数不一致：S 参数有 {len(s)} 个频点，频率列表有 {len(freqs_hz)} 个")
    for k, mat in enumerate(s):
        if len(mat) != n or any(len(row) != n for row in mat):
            raise TouchstoneError(f"第 {k} 个频点的 S 矩阵不是 {n}×{n}")
    fmt = fmt.upper()
    if fmt not in ("MA", "DB", "RI"):
        raise ValueError("fmt 只能是 MA/DB/RI")
    lines: List[str] = []
    if comment:
        for ln in comment.splitlines():
            lines.append("! " + ln)
    lines.append("! 由 OpenRF Studio 生成")
    lines.append(f"# Hz S {fmt} R {z0:g}")
    for k, f in enumerate(freqs_hz):
        pairs: List[str] = []
        for j in range(n):
            for i in range(n):
                v = s[k][i][j]
                if fmt == "MA":
                    pairs.append(f"{abs(v):.10e} {math.degrees(cmath.phase(v)):.6f}")
                elif fmt == "DB":
                    mag = 20 * math.log10(abs(v)) if abs(v) > 0 else -300.0
                    pairs.append(f"{mag:.10e} {math.degrees(cmath.phase(v)):.6f}")
                else:
                    pairs.append(f"{v.real:.10e} {v.imag:.10e}")
        lines.append(f"{f:.10e} " + " ".join(pairs))
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def read_touchstone(path: str) -> Tuple[List[float], List[List[List[Complex]]], float, int]:
    """读 Touchstone：返回 (频率Hz列表, S[频点][i][j], Z0, 端口数)。"""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    fmt, unit, z0, nport = "MA", "GHZ", 50.0, 0
    explicit_freq_unit = False
    freqs: List[float] = []
    data: List[List[List[Complex]]] = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("!"):
                continue
            m = _OPT.match(line)
            if m:
                toks = m.group(1).upper().split()
                if toks and toks[0] in ("HZ", "KHZ", "MHZ", "GHZ"):
                    unit = toks[0]
                    explicit_freq_unit = True
                if "S" in toks:
                    si = toks.index("S")
                    if si + 1 >= len(toks):
                        raise TouchstoneError("选项行缺少 S 参数格式（MA/DB/RI）")
                    nf = toks[si + 1]
                    if nf not in ("MA", "DB", "RI"):
                        raise TouchstoneError(f"未知 S 参数格式 {nf!r}（只支持 MA/DB/RI）")
                    fmt = nf
                if "R" in toks:
                    try:
                        z0 = float(toks[toks.index("R") + 1])
                    except (ValueError, IndexError) as exc:
                        raise TouchstoneError(f"选项行 R 参考阻抗解析失败：{m.group(1)!r}") from exc
                continue
            if nport == 0:
                nport = _guess_nport(path)
                if nport == 0:
                    raise TouchstoneError("无法推断端口数（文件名需形如 xxx.s2p）")
            try:
                nums = [float(x) for x in line.replace(",", " ").split()]
            except ValueError as exc:
                raise TouchstoneError(f"数据行含非法数值：{line!r}") from exc
            if not nums:
                continue
            if len(nums) < 1 + 2 * nport ** 2:
                raise TouchstoneError(f"数据行字段不足：需要 {1 + 2 * nport ** 2} 个")
            f = nums[0] * _unit_scale(unit)
            mat = [[0j] * nport for _ in range(nport)]
            p = 1
            for j in range(nport):          # Touchstone 顺序：列优先
                for i in range(nport):
                    a, b = nums[p], nums[p + 1]
                    p += 2
                    if fmt == "MA":
                        mat[i][j] = cmath.rect(a, math.radians(b))
                    elif fmt == "DB":
                        mat[i][j] = cmath.rect(10 ** (a / 20), math.radians(b))
                    else:
                        mat[i][j] = complex(a, b)
            freqs.append(f)
            data.append(mat)
    if not freqs:
        raise TouchstoneError("文件中没有数据")
    warning = ""
    if not explicit_freq_unit:
        warning = ("文件缺少 # 频率单位选项行，已按默认 GHz 解析；"
                   "若数据实为 Hz/kHz/MHz，结果会相差 10^9/10^6/10^3 倍，请补 “# Hz” 等选项行")
    return TouchstoneData(freqs, data, z0, nport, warning)


def _guess_nport(path: str) -> int:
    m = re.search(r"\.s(\d+)p$", os.path.basename(path), re.IGNORECASE)
    return int(m.group(1)) if m else 0
