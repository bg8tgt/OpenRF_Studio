"""原理图绘制：把 Network 拓扑自动排布成电路图（Canvas 手绘符号）。

排布策略（自动布局，不做拖拽编辑）：
  1. 从第一个端口节点做 BFS，给每个节点算"层号"（layer）；
  2. 同一层的节点在竖直方向均匀排开，层号决定横坐标；
  3. 串联元件画在两节点之间的连线上；并联元件从节点向下接到"地母线"；
  4. 端口画在它所属节点的外侧。

支持的符号：电阻（折线）、电容（双极板）、电感（半圆串）、
理想传输线（双线）、微带线（双线+剖面提示）、同轴线（圆环+内芯）、
端口、地。数值与编号标在符号旁。
"""
from __future__ import annotations

import math
import tkinter as tk
from collections import deque
from typing import Dict, List, Optional, Tuple

from ..components import Component, is_ground
from ..engine import Network

BG = "#ffffff"
FG = "#1f2937"
WIRE = "#374151"
SYM = "#1d4ed8"
LABEL = "#6b7280"
ACCENT = "#b91c1c"
FONT = ("Microsoft YaHei UI", 8)
FONT_S = ("Microsoft YaHei UI", 7)
FONT_B = ("Microsoft YaHei UI", 9, "bold")


class SchematicView(tk.Canvas):
    def __init__(self, master, **kw):
        super().__init__(master, background=BG, highlightthickness=0, **kw)
        self._cw = int(kw.get("width", 720))
        self._ch = int(kw.get("height", 420))
        self.network: Optional[Network] = None
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, ev):
        self._cw, self._ch = max(ev.width, 200), max(ev.height, 160)
        self.redraw()

    def set_network(self, net: Optional[Network]):
        self.network = net
        self.redraw()

    # ------------------------------------------------------------------ 布局
    def _layout(self) -> Tuple[Dict[str, Tuple[float, float]], int]:
        net = self.network
        assert net is not None
        adj: Dict[str, List[str]] = {}
        for c in net.components:
            a, b = c.nodes[0], c.nodes[1]
            if is_ground(a) or is_ground(b):
                continue
            adj.setdefault(a, []).append(b)
            adj.setdefault(b, []).append(a)
        starts = [p.node for p in net.ports if not is_ground(p.node)]
        for c in net.components:
            for n in c.nodes:
                if not is_ground(n):
                    adj.setdefault(n, [])
        depth: Dict[str, int] = {}
        for s in starts:
            if s in depth:
                continue
            depth[s] = 0
            dq = deque([s])
            while dq:
                u = dq.popleft()
                for v in adj.get(u, []):
                    if v not in depth:
                        depth[v] = depth[u] + 1
                        dq.append(v)
        for n in adj:
            depth.setdefault(n, 0)
        nlayer = max(depth.values(), default=0) + 1
        # 每层收集节点
        layers: Dict[int, List[str]] = {}
        for n, d in depth.items():
            layers.setdefault(d, []).append(n)
        for d in layers:
            layers[d].sort()
        W, H = self._cw, self._ch
        margin_x, top, bottom = 70, 56, 96
        usable_w = max(W - 2 * margin_x, 120)
        usable_h = max(H - top - bottom, 100)
        dx = usable_w / max(nlayer - 1, 1)
        pos: Dict[str, Tuple[float, float]] = {}
        for d, nodes in layers.items():
            n = len(nodes)
            for i, name in enumerate(nodes):
                x = margin_x + d * dx
                if n == 1:
                    y = top + usable_h * 0.36
                else:
                    y = top + usable_h * (0.18 + 0.46 * i / (n - 1))
                pos[name] = (x, y)
        return pos, nlayer

    # ------------------------------------------------------------------ 绘制
    def redraw(self):
        self.delete("all")
        W, H = self._cw, self._ch
        self.create_text(W / 2, 16, text="原理图（自动布局）", fill=FG, font=FONT_B)
        net = self.network
        if not net or not net.components:
            self.create_text(W / 2, H / 2, text="尚无电路 —— 添加元件或使用滤波器向导",
                             fill="#9ca3af", font=("Microsoft YaHei UI", 11))
            return
        pos, nlayer = self._layout()
        ground_y = H - 58
        # 地母线
        self.create_line(60, ground_y, W - 40, ground_y, fill=WIRE, width=1)
        self.create_text(W - 34, ground_y, text="⏚", fill=LABEL, font=FONT)

        # 先画导线
        for c in net.components:
            a, b = c.nodes[0], c.nodes[1]
            if is_ground(a) or is_ground(b):
                continue
            if a in pos and b in pos:
                self.create_line(*pos[a], *pos[b], fill=WIRE, width=1.4)
        # 再画元件符号
        for c in net.components:
            a, b = c.nodes[0], c.nodes[1]
            if is_ground(a) or is_ground(b):
                node = a if is_ground(b) else b
                if node in pos:
                    x, y = pos[node]
                    self._draw_symbol(c, (x, y), (x, ground_y), vertical=True)
                    self._ground_symbol(x, ground_y)
            elif a in pos and b in pos:
                p1, p2 = pos[a], pos[b]
                vertical = abs(p2[1] - p1[1]) > abs(p2[0] - p1[0])
                self._draw_symbol(c, p1, p2, vertical=vertical)
        # 端口
        for i, p in enumerate(net.ports, 1):
            if p.node in pos:
                x, y = pos[p.node]
                self._draw_port(x, y, p.pid, i)
        # 节点小圆点
        for name, (x, y) in pos.items():
            self.create_oval(x - 2.5, y - 2.5, x + 2.5, y + 2.5, fill=WIRE, outline="")
        # 图注
        self.create_text(70, H - 26, anchor="w",
                         text=f"元件 {len(net.components)} 个 · 节点 {len(pos)} 个 · "
                              f"端口 {len(net.ports)} 个 · Z0={net.z0:g} Ω",
                         fill=LABEL, font=FONT_S)

    # ---------- 符号 ----------
    def _draw_symbol(self, c: Component, p1: Tuple[float, float],
                     p2: Tuple[float, float], vertical: bool):
        x1, y1 = p1
        x2, y2 = p2
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        length = math.hypot(x2 - x1, y2 - y1)
        # 符号占中间固定长度，两侧补导线
        sym_len = 34
        if length > sym_len + 8:
            ux, uy = (x2 - x1) / length, (y2 - y1) / length
            ax, ay = mx - ux * sym_len / 2, my - uy * sym_len / 2
            bx, by = mx + ux * sym_len / 2, my + uy * sym_len / 2
        else:
            ax, ay, bx, by = x1, y1, x2, y2
        # 两端引线（并联元件的引线常被漏掉，导致符号"悬空"）
        self.create_line(x1, y1, ax, ay, fill=WIRE, width=1.4)
        self.create_line(bx, by, x2, y2, fill=WIRE, width=1.4)
        kind = c.kind
        if kind == "R":
            self._zigzag(ax, ay, bx, by)
        elif kind == "L":
            self._coils(ax, ay, bx, by)
        elif kind == "C":
            self._plates(ax, ay, bx, by)
        elif kind in ("TL", "MS"):
            self._twin_line(ax, ay, bx, by)
        elif kind == "COAX":
            self._coax(ax, ay, bx, by)
        else:
            self.create_line(ax, ay, bx, by, fill=SYM, width=1.6)
        # 标签
        if vertical:
            tx, ty = mx + 22, my
        else:
            dx, dy = (-uy, ux) if length else (0, -1)
            tx, ty = mx + dx * 16, my + dy * 16
        self.create_text(tx, ty - 7, text=c.cid, fill=ACCENT, font=FONT_B)
        self.create_text(tx, ty + 7, text=self._value_text(c), fill=LABEL, font=FONT_S)

    @staticmethod
    def _value_text(c: Component) -> str:
        p = c.params
        if c.kind == "R":
            return f"{p.get('r', 50):g}Ω"
        if c.kind == "L":
            return f"{p.get('l', 1):g}nH"
        if c.kind == "C":
            return f"{p.get('c', 1):g}pF"
        if c.kind == "TL":
            return f"Z0={p.get('z0', 50):g}Ω"
        if c.kind == "MS":
            return f"W={p.get('w', 1):g}mm"
        if c.kind == "COAX":
            return f"D/d={p.get('d_out', 3):g}/{p.get('d_in', 0.91):g}"
        return ""

    def _zigzag(self, x1, y1, x2, y2):
        n = 6
        amp = 5.0
        length = math.hypot(x2 - x1, y2 - y1)
        if not length:
            return
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        px, py = -uy, ux
        pts = [(x1, y1)]
        for i in range(1, n):
            t = i / n
            s = amp if i % 2 else -amp
            pts.append((x1 + ux * length * t + px * s,
                        y1 + uy * length * t + py * s))
        pts.append((x2, y2))
        self.create_line(*[v for pt in pts for v in pt], fill=SYM, width=1.8)

    def _coils(self, x1, y1, x2, y2):
        n = 3
        length = math.hypot(x2 - x1, y2 - y1)
        if not length:
            return
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        r = length / (2 * n)
        for k in range(n):
            cx = x1 + ux * (2 * k + 1) * r
            cy = y1 + uy * (2 * k + 1) * r
            self.create_oval(cx - r, cy - r, cx + r, cy + r, outline=SYM, width=1.4)

    def _plates(self, x1, y1, x2, y2):
        length = math.hypot(x2 - x1, y2 - y1)
        if not length:
            return
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        px, py = -uy, ux
        gap = 5
        for s in (-gap, gap):
            cx, cy = (x1 + x2) / 2 + ux * s, (y1 + y2) / 2 + uy * s
            self.create_line(cx - px * 9, cy - py * 9, cx + px * 9, cy + py * 9,
                             fill=SYM, width=2.0)
        self.create_line(x1, y1, (x1 + x2) / 2 - ux * gap, (y1 + y2) / 2 - uy * gap,
                         fill=WIRE, width=1.2)
        self.create_line((x1 + x2) / 2 + ux * gap, (y1 + y2) / 2 + uy * gap, x2, y2,
                         fill=WIRE, width=1.2)

    def _twin_line(self, x1, y1, x2, y2):
        length = math.hypot(x2 - x1, y2 - y1)
        if not length:
            return
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        px, py = -uy, ux
        for s in (-3, 3):
            self.create_line(x1 + px * s, y1 + py * s, x2 + px * s, y2 + py * s,
                             fill=SYM, width=1.5)

    def _coax(self, x1, y1, x2, y2):
        length = math.hypot(x2 - x1, y2 - y1)
        if not length:
            return
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        px, py = -uy, ux
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        self.create_oval(cx - 11, cy - 11, cx + 11, cy + 11, outline=SYM, width=1.6)
        self.create_oval(cx - 2.5, cy - 2.5, cx + 2.5, cy + 2.5, fill=SYM, outline="")
        self.create_line(x1, y1, cx - ux * 11, cy - uy * 11, fill=WIRE, width=1.2)
        self.create_line(cx + ux * 11, cy + uy * 11, x2, y2, fill=WIRE, width=1.2)

    def _ground_symbol(self, x: float, y: float):
        for i, w in enumerate((11, 7, 3)):
            yy = y + i * 4
            self.create_line(x - w, yy, x + w, yy, fill=WIRE, width=1.3)

    def _draw_port(self, x: float, y: float, pid: str, index: int):
        r = 9
        self.create_oval(x - r, y - r, x + r, y + r, outline=ACCENT, width=1.8, fill="#fef2f2")
        self.create_text(x, y, text=str(index), fill=ACCENT, font=FONT_S)
        self.create_text(x, y - 16, text=pid, fill=ACCENT, font=FONT_S)