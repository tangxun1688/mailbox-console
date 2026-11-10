# -*- coding: utf-8 -*-
"""生成 app.ico（纯标准库，不依赖 Pillow）。

用法：
    python tools/make_icon.py          # 输出到工程根目录 app.ico

图形是一个圆角蓝底 + 白色信封，用超采样 + 盒式降采样得到抗锯齿边缘。
只有打包时才需要跑；改图标就改这里再重新生成。
"""

import struct
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "app.ico"
SIZES = [16, 24, 32, 48, 64, 128, 256]
SS = 3  # 超采样倍数

BG_TOP = (72, 148, 255)
BG_BOTTOM = (26, 84, 196)
PAPER = (247, 250, 255)
FLAP = (198, 214, 242)


def _round_rect(x, y, x0, y0, x1, y1, r):
    if x < x0 or x > x1 or y < y0 or y > y1:
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def _in_triangle(px, py, a, b, c):
    def sign(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])

    d1, d2, d3 = sign((px, py), a, b), sign((px, py), b, c), sign((px, py), c, a)
    neg = d1 < 0 or d2 < 0 or d3 < 0
    pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (neg and pos)


def render(size: int) -> bytearray:
    """返回 size*size 的 RGBA 像素（自上而下）。"""
    s = size * SS
    px = bytearray(s * s * 4)

    body = (0.16 * s, 0.33 * s, 0.84 * s, 0.73 * s)
    radius = 0.035 * s
    flap = ((0.16 * s, 0.33 * s), (0.5 * s, 0.61 * s), (0.84 * s, 0.33 * s))

    for y in range(s):
        t = y / max(1, s - 1)
        bg = tuple(round(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3))
        for x in range(s):
            if not _round_rect(x, y, 0.02 * s, 0.02 * s, 0.98 * s, 0.98 * s, 0.22 * s):
                continue
            color = bg
            if _round_rect(x, y, *body, radius):
                color = PAPER
                if _in_triangle(x, y, *flap):
                    color = FLAP
            i = (y * s + x) * 4
            px[i:i + 4] = bytes((color[0], color[1], color[2], 255))

    # 盒式降采样
    out = bytearray(size * size * 4)
    n = SS * SS
    for y in range(size):
        for x in range(size):
            r = g = b = a = 0
            for dy in range(SS):
                row = (y * SS + dy) * s
                for dx in range(SS):
                    i = (row + x * SS + dx) * 4
                    r += px[i]
                    g += px[i + 1]
                    b += px[i + 2]
                    a += px[i + 3]
            o = (y * size + x) * 4
            out[o:o + 4] = bytes((r // n, g // n, b // n, a // n))
    return out


def _dib(size: int, rgba: bytearray) -> bytes:
    """ICO 内的 32 位 BMP：BITMAPINFOHEADER + 自下而上 BGRA + AND 掩码。"""
    header = struct.pack(
        "<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, size * size * 4, 0, 0, 0, 0
    )
    rows = bytearray()
    for y in range(size - 1, -1, -1):
        for x in range(size):
            i = (y * size + x) * 4
            rows += bytes((rgba[i + 2], rgba[i + 1], rgba[i], rgba[i + 3]))
    mask_row = (size + 31) // 32 * 4
    mask = bytes(mask_row * size)
    return header + bytes(rows) + mask


def write_ico(path: Path, sizes=SIZES) -> None:
    images = [(s, render(s)) for s in sizes]
    entries, blobs = b"", b""
    offset = 6 + 16 * len(images)
    for size, rgba in images:
        dib = _dib(size, rgba)
        entries += struct.pack(
            "<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(dib), offset + len(blobs)
        )
        blobs += dib
    path.write_bytes(struct.pack("<HHH", 0, 1, len(images)) + entries + blobs)


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT
    write_ico(target)
    print(f"wrote {target} ({target.stat().st_size} bytes, sizes={SIZES})")
