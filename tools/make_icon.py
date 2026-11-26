"""生成软件图标：assets/openrf.ico（多尺寸）+ assets/openrf_256.png。

设计：深蓝圆角底 + 青色 Smith 圆环 + 白色正弦波 + 红/绿端口点。
纯 Pillow 绘制，4 倍超采样后缩放，保证小尺寸不糊。
"""
from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "assets")

BG_TOP = (18, 41, 66)
BG_BOT = (8, 22, 38)
RING = (56, 189, 248)
WAVE = (232, 244, 255)
PORT1 = (248, 113, 113)
PORT2 = (52, 211, 153)
TICK = (60, 120, 165)

SS = 4            # 超采样倍数
S = 256 * SS


def rounded_bg(img: Image.Image):
    grad = Image.new("RGB", (1, S), BG_BOT)
    d = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / max(S - 1, 1)
        c = tuple(int(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t) for i in range(3))
        d.point((0, y), fill=c)
    grad = grad.resize((S, S))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1],
                                           radius=int(0.22 * S), fill=255)
    img.paste(grad, (0, 0), mask)


def draw_icon() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    rounded_bg(img)
    d = ImageDraw.Draw(img)

    cx, cy, r = S * 0.5, S * 0.44, S * 0.255
    # Smith 圆环
    d.ellipse([cx - r, cy - r, cx + r, cy + r],
              outline=RING, width=int(S * 0.028))
    # 环上的刻度（8 个方向）
    for k in range(8):
        a = math.pi * 2 * k / 8
        r1, r2 = r * 0.86, r * 0.995
        d.line([cx + r1 * math.cos(a), cy + r1 * math.sin(a),
                cx + r2 * math.cos(a), cy + r2 * math.sin(a)],
               fill=TICK, width=max(2, int(S * 0.008)))
    # 正弦波
    pts = []
    x0, x1, ybase, amp = S * 0.17, S * 0.83, S * 0.70, S * 0.075
    for i in range(161):
        t = i / 160
        x = x0 + (x1 - x0) * t
        y = ybase - amp * math.sin(math.pi * 2 * 1.25 * t)
        pts.append((x, y))
    d.line(pts, fill=WAVE, width=int(S * 0.026), joint="curve")
    # 端口点
    def dot(p, color):
        rr = S * 0.036
        d.ellipse([p[0] - rr, p[1] - rr, p[0] + rr, p[1] + rr], fill=color)
    dot(pts[0], PORT1)
    dot(pts[-1], PORT2)
    return img


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    big = draw_icon()
    big = big.resize((256, 256), Image.LANCZOS)
    png = os.path.join(OUT_DIR, "openrf_256.png")
    big.save(png)

    ico = os.path.join(OUT_DIR, "openrf.ico")
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    big.save(ico, format="ICO", sizes=sizes)
    print("PNG:", png, os.path.getsize(png), "bytes")
    print("ICO:", ico, os.path.getsize(ico), "bytes")
    # 校验 ICO 内含尺寸
    with Image.open(ico) as im:
        print("ICO sizes:", sorted(im.info.get("sizes", [])))


if __name__ == "__main__":
    main()