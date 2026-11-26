"""复数矩阵运算（纯 Python，无第三方依赖）。

只实现电路求解需要的几件事：矩阵乘法、加减、单位阵、高斯-约当求逆/解方程。
规模很小（节点数通常 < 200），O(n^3) 足够。
"""
from __future__ import annotations

import cmath
from typing import List

Complex = complex
Matrix = List[List[complex]]


def zeros(n: int, m: int | None = None) -> Matrix:
    m = n if m is None else m
    return [[0j] * m for _ in range(n)]


def identity(n: int) -> Matrix:
    out = zeros(n)
    for i in range(n):
        out[i][i] = 1 + 0j
    return out


def add(a: Matrix, b: Matrix) -> Matrix:
    return [[a[i][j] + b[i][j] for j in range(len(a[0]))] for i in range(len(a))]


def sub(a: Matrix, b: Matrix) -> Matrix:
    return [[a[i][j] - b[i][j] for j in range(len(a[0]))] for i in range(len(a))]


def scale(a: Matrix, k: complex) -> Matrix:
    return [[x * k for x in row] for row in a]


def matmul(a: Matrix, b: Matrix) -> Matrix:
    n, m, p = len(a), len(b), len(b[0])
    out = zeros(n, p)
    for i in range(n):
        ai = a[i]
        oi = out[i]
        for k in range(m):
            aik = ai[k]
            if aik == 0:
                continue
            bk = b[k]
            for j in range(p):
                oi[j] += aik * bk[j]
    return out


def inverse(a: Matrix) -> Matrix:
    n = len(a)
    m = [list(row) + [1.0 + 0j if i == j else 0j for j in range(n)]
         for i, row in enumerate(a)]
    scale = max([abs(v) for row in a for v in row] + [1.0])
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-14 * scale:
            raise ZeroDivisionError(f"矩阵奇异（第 {col} 列，主元 {abs(m[piv][col]):.3e}）")
        if piv != col:
            m[col], m[piv] = m[piv], m[col]
        pv = m[col][col]
        for c in range(col, 2 * n):
            m[col][c] /= pv
        for r in range(n):
            if r == col:
                continue
            f = m[r][col]
            if f == 0:
                continue
            for c in range(col, 2 * n):
                m[r][c] -= f * m[col][c]
    return [row[n:] for row in m]


def db(x: complex, floor_db: float = -300.0) -> float:
    mag = abs(x)
    if mag <= 0:
        return floor_db
    v = 20.0 * cmath.log10(mag).real
    return max(v, floor_db)


def phase_deg(x: complex) -> float:
    return cmath.phase(x) * 180.0 / cmath.pi
