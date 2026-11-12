"""裝飾物:椰子樹、珊瑚、岩石、星球……全部用程式畫,不需要任何圖檔。

兩件事:
1. 畫圖(sprite):每種裝飾物是一個函式,以 4 倍大小繪製再縮小,邊緣才會平滑。
2. 擺放(place):螢幕切成固定的格子,每格有一個固定的候選位置與亂數。
   候選位置落在哪個地帶(離海岸線多遠)決定它能變成什麼。
   因為格子與亂數只跟螢幕位置有關,移動一個圖示只會影響它附近的裝飾物。
"""
from __future__ import annotations

import math
import random
import zlib
from dataclasses import dataclass
from typing import Callable, Dict, List, Sequence, Tuple

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

Color = Tuple[int, int, int]
Rect = Tuple[int, int, int, int]

SS = 4                 # 繪製時的放大倍數
CELL = 46              # 擺放格子的大小(100% 縮放下的像素)
VARIANTS = 4           # 每種裝飾物有幾種長相
_RES = getattr(Image, "Resampling", Image)


@dataclass(frozen=True)
class DecorRule:
    """在離海岸線 lo~hi 的地帶,每個候選位置有 chance 的機率放一個 kind。"""
    kind: str
    lo: float
    hi: float
    chance: float
    size: Tuple[int, int] = (24, 32)   # 大小範圍(像素)
    colors: Tuple[Color, ...] = ()     # 空 = 用該裝飾物的預設配色
    shadow: bool = True                # 是否有影子(水面下的東西沒有)
    spin: float = 1.0                  # 隨機旋轉的幅度:1 = 任意角度,0 = 不旋轉
    alpha: float = 1.0                 # 不透明度


@dataclass(frozen=True)
class Placement:
    rule: DecorRule
    x: int
    y: int
    size: int
    angle: float
    variant: int


# ---------------------------------------------------------------------------
# 繪圖小工具
# ---------------------------------------------------------------------------
def _canvas(size: int):
    image = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image), size * SS


def _done(image: Image.Image, size: int) -> Image.Image:
    return image.resize((size, size), _RES.LANCZOS)


def _a(color: Color, alpha: int = 255):
    return (color[0], color[1], color[2], alpha)


def _shade(color: Color, factor: float) -> Color:
    return tuple(max(0, min(255, int(c * factor))) for c in color)


def _circle(draw, x, y, r, fill):
    draw.ellipse((x - r, y - r, x + r, y + r), fill=fill)


def _blob(rng, cx, cy, radius, points=9, wobble=0.3, squash=1.0, phase=0.0):
    """不規則的多邊形(岩石、浮冰的輪廓)。"""
    out = []
    for i in range(points):
        ang = phase + i * 2 * math.pi / points
        r = radius * (1 - wobble + wobble * rng.random())
        out.append((cx + math.cos(ang) * r, cy + math.sin(ang) * r * squash))
    return out


def _scaled(points, cx, cy, factor, dx=0.0, dy=0.0):
    return [(cx + (x - cx) * factor + dx, cy + (y - cy) * factor + dy) for x, y in points]


def _star(cx, cy, outer, inner, points, phase=0.0):
    out = []
    for i in range(points * 2):
        r = outer if i % 2 == 0 else inner
        ang = phase + i * math.pi / points
        out.append((cx + math.cos(ang) * r, cy + math.sin(ang) * r))
    return out


def _leaf(cx, cy, angle, length, width, bend=0.0, steps=8):
    """一片葉子:從 (cx, cy) 朝 angle 伸出去,中段最寬。"""
    left, right = [], []
    for i in range(steps + 1):
        t = i / steps
        a = angle + bend * t * t
        px = cx + math.cos(a) * length * t
        py = cy + math.sin(a) * length * t
        w = width * math.sin(math.pi * min(1.0, t * 0.95 + 0.05)) ** 0.8
        nx, ny = -math.sin(a), math.cos(a)
        left.append((px + nx * w, py + ny * w))
        right.append((px - nx * w, py - ny * w))
    return left + right[::-1]


# ---------------------------------------------------------------------------
# 裝飾物
# ---------------------------------------------------------------------------
def palm(size, rng, colors):
    dark, light, trunk = colors or ((38, 110, 52), (86, 160, 66), (112, 78, 44))
    image, draw, s = _canvas(size)
    c = s / 2
    count = rng.randint(7, 9)
    base = rng.random() * math.tau
    for layer, (color, reach) in enumerate(((dark, 0.47), (light, 0.36))):
        for i in range(count):
            ang = base + (i + layer * 0.5) * math.tau / count + rng.uniform(-0.12, 0.12)
            length = s * reach * rng.uniform(0.82, 1.0)
            bend = rng.uniform(-0.35, 0.35)
            draw.polygon(_leaf(c, c, ang, length, s * 0.055, bend), fill=_a(color))
            tip_a = ang + bend
            draw.line(
                (c, c, c + math.cos(tip_a) * length * 0.85, c + math.sin(tip_a) * length * 0.85),
                fill=_a(_shade(color, 1.25 if layer == 0 else 0.8)), width=max(1, s // 90),
            )
    _circle(draw, c, c, s * 0.055, _a(trunk))
    for i in range(3):
        ang = base + i * math.tau / 3
        _circle(draw, c + math.cos(ang) * s * 0.06, c + math.sin(ang) * s * 0.06, s * 0.032,
                _a(_shade(trunk, 0.7)))
    return _done(image, size)


def rock(size, rng, colors):
    base, light, dark = colors or ((134, 128, 120), (176, 170, 160), (92, 88, 84))
    image, draw, s = _canvas(size)
    c = s / 2
    outline = _blob(rng, c, c, s * 0.44, points=9, wobble=0.32, squash=rng.uniform(0.75, 1.0),
                    phase=rng.random())
    draw.polygon(outline, fill=_a(dark))
    draw.polygon(_scaled(outline, c, c, 0.9, -s * 0.02, -s * 0.02), fill=_a(base))
    draw.polygon(_scaled(outline, c, c, 0.5, -s * 0.09, -s * 0.09), fill=_a(light))
    return _done(image, size)


def starfish(size, rng, colors):
    body, light = colors or ((232, 112, 62), (250, 170, 110))
    image, draw, s = _canvas(size)
    c = s / 2
    phase = rng.random() * math.tau
    draw.polygon(_star(c, c, s * 0.44, s * 0.17, 5, phase), fill=_a(body))
    for i in range(5):
        ang = phase + i * math.tau / 5
        _circle(draw, c + math.cos(ang) * s * 0.4, c + math.sin(ang) * s * 0.4, s * 0.05, _a(body))
        for t in (0.12, 0.24):
            _circle(draw, c + math.cos(ang) * s * t, c + math.sin(ang) * s * t, s * 0.025, _a(light))
    return _done(image, size)


def shell(size, rng, colors):
    body, line = colors or ((246, 226, 214), (206, 160, 150))
    image, draw, s = _canvas(size)
    cx, cy, r = s / 2, s * 0.72, s * 0.58
    draw.pieslice((cx - r, cy - r, cx + r, cy + r), 215, 325, fill=_a(body))
    for i in range(6):
        ang = math.radians(222 + i * 19.2)
        draw.line((cx, cy, cx + math.cos(ang) * r * 0.96, cy + math.sin(ang) * r * 0.96),
                  fill=_a(line), width=max(1, s // 40))
    _circle(draw, cx, cy - s * 0.02, s * 0.07, _a(line))
    return _done(image, size)


def coral(size, rng, colors):
    main, light = colors or ((236, 112, 132), (255, 190, 196))
    image, draw, s = _canvas(size)
    c = s / 2
    tips = []
    for i in range(rng.randint(5, 7)):
        ang = i * math.tau / 6 + rng.uniform(-0.4, 0.4)
        x, y, r = c, c, s * 0.085
        for _ in range(rng.randint(4, 6)):
            _circle(draw, x, y, r, _a(main))
            ang += rng.uniform(-0.55, 0.55)
            x += math.cos(ang) * r * 1.25
            y += math.sin(ang) * r * 1.25
            r *= 0.86
            if abs(x - c) > s * 0.42 or abs(y - c) > s * 0.42:
                break
        tips.append((x - math.cos(ang) * r, y - math.sin(ang) * r, r))
    _circle(draw, c, c, s * 0.11, _a(main))
    for x, y, r in tips:
        _circle(draw, x, y, r * 0.55, _a(light))
    return _done(image, size)


def fish(size, rng, colors):
    (body,) = colors or ((20, 60, 110),)
    image, draw, s = _canvas(size)
    heading = rng.random() * math.tau
    hx, hy = math.cos(heading), math.sin(heading)
    for _ in range(rng.randint(4, 6)):
        x = s * rng.uniform(0.22, 0.78)
        y = s * rng.uniform(0.22, 0.78)
        length = s * rng.uniform(0.11, 0.15)
        draw.polygon(_leaf(x - hx * length, y - hy * length, heading, length * 2, length * 0.42),
                     fill=_a(body))
        tx, ty = x - hx * length * 0.9, y - hy * length * 0.9
        draw.polygon([
            (tx, ty),
            (tx - hx * length * 0.7 - hy * length * 0.45, ty - hy * length * 0.7 + hx * length * 0.45),
            (tx - hx * length * 0.7 + hy * length * 0.45, ty - hy * length * 0.7 - hx * length * 0.45),
        ], fill=_a(body))
    return _done(image, size)


def boat(size, rng, colors):
    hull, deck, sail = colors or ((120, 78, 46), (214, 180, 132), (250, 250, 246))
    image, draw, s = _canvas(size)
    c = s / 2
    draw.polygon(_leaf(c - s * 0.42, c, 0.0, s * 0.84, s * 0.15), fill=_a(hull))
    draw.polygon(_leaf(c - s * 0.34, c, 0.0, s * 0.68, s * 0.1), fill=_a(deck))
    draw.polygon([(c + s * 0.22, c), (c - s * 0.2, c - s * 0.2), (c - s * 0.14, c)], fill=_a(sail))
    draw.polygon([(c + s * 0.22, c), (c - s * 0.2, c + s * 0.12), (c - s * 0.14, c)],
                 fill=_a(_shade(sail, 0.86)))
    return _done(image, size)


def tree(size, rng, colors):
    dark, mid, light = colors or ((40, 96, 44), (62, 128, 54), (104, 164, 72))
    image, draw, s = _canvas(size)
    c = s / 2
    lumps = [(rng.uniform(-0.17, 0.17), rng.uniform(-0.17, 0.17), rng.uniform(0.2, 0.27))
             for _ in range(rng.randint(6, 8))]
    for color, shift, shrink in ((dark, 0.0, 1.0), (mid, -0.045, 0.74), (light, -0.085, 0.42)):
        for x, y, r in lumps:
            _circle(draw, c + (x + shift) * s, c + (y + shift) * s, r * s * shrink, _a(color))
    return _done(image, size)


def flowers(size, rng, colors):
    palette = colors or ((250, 236, 120), (250, 250, 250), (240, 140, 170), (238, 190, 60))
    centre = palette[-1]
    image, draw, s = _canvas(size)
    for _ in range(rng.randint(3, 5)):
        x, y = s * rng.uniform(0.2, 0.8), s * rng.uniform(0.2, 0.8)
        petal = rng.choice(palette[:-1])
        r = s * rng.uniform(0.045, 0.06)
        for i in range(5):
            ang = i * math.tau / 5
            _circle(draw, x + math.cos(ang) * r * 1.2, y + math.sin(ang) * r * 1.2, r, _a(petal))
        _circle(draw, x, y, r * 0.75, _a(centre))
    return _done(image, size)


def lilypad(size, rng, colors):
    pad, pad_light, bloom = colors or ((52, 128, 62), (96, 168, 84), (246, 178, 204))
    image, draw, s = _canvas(size)
    c, r = s / 2, s * 0.43
    start = rng.uniform(0, 360)
    draw.pieslice((c - r, c - r, c + r, c + r), start, start + 325, fill=_a(pad))
    r2 = r * 0.8
    draw.pieslice((c - r2, c - r2, c + r2, c + r2), start + 4, start + 321, fill=_a(pad_light))
    for i in range(7):
        ang = math.radians(start + 20 + i * 47)
        draw.line((c, c, c + math.cos(ang) * r * 0.86, c + math.sin(ang) * r * 0.86),
                  fill=_a(pad), width=max(1, s // 60))
    if rng.random() < 0.5:
        fx, fy = c + rng.uniform(-0.1, 0.1) * s, c + rng.uniform(-0.1, 0.1) * s
        draw.polygon(_star(fx, fy, s * 0.15, s * 0.07, 7, rng.random()), fill=_a(bloom))
        _circle(draw, fx, fy, s * 0.045, _a((250, 226, 120)))
    return _done(image, size)


def crater(size, rng, colors):
    rim_light, floor, rim_dark = colors or ((196, 196, 204), (104, 104, 114), (70, 70, 80))
    image, draw, s = _canvas(size)
    c, r = s / 2, s * 0.4
    k = s * 0.035
    # 光從左上來:坑的外緣右下亮、左上暗;坑內相反
    _circle(draw, c + k, c + k, r, _a(rim_dark, 150))
    _circle(draw, c - k, c - k, r, _a(rim_light, 190))
    _circle(draw, c, c, r * 0.86, _a(floor, 235))
    _circle(draw, c + k * 1.2, c + k * 1.2, r * 0.7, _a(_shade(floor, 1.22), 235))
    return _done(image, size)


def planet(size, rng, colors):
    base, band, ring = colors or ((214, 150, 92), (176, 108, 70), (232, 214, 170))
    image, draw, s = _canvas(size)
    c = s / 2
    has_ring = rng.random() < 0.5
    r = s * (0.26 if has_ring else 0.42)

    body = Image.new("RGBA", image.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(body)
    _circle(bd, c, c, r, _a(base))
    for _ in range(rng.randint(2, 4)):
        y = c + rng.uniform(-0.8, 0.8) * r
        h = r * rng.uniform(0.08, 0.2)
        bd.rectangle((c - r, y - h, c + r, y + h), fill=_a(band))
    # 背光面:一個偏移的深色圓
    shade = Image.new("RGBA", image.size, (0, 0, 0, 0))
    _circle(ImageDraw.Draw(shade), c + r * 0.38, c + r * 0.38, r * 1.05, (0, 0, 16, 120))
    lit = Image.new("L", image.size, 0)
    _circle(ImageDraw.Draw(lit), c - r * 0.25, c - r * 0.25, r * 1.02, 255)
    shade.putalpha(ImageChops.subtract(shade.getchannel("A"), lit))
    body = Image.alpha_composite(body, shade)
    disc = Image.new("L", image.size, 0)
    _circle(ImageDraw.Draw(disc), c, c, r, 255)
    body.putalpha(ImageChops.multiply(body.getchannel("A"), disc))

    if has_ring:
        rings = Image.new("RGBA", image.size, (0, 0, 0, 0))
        rd = ImageDraw.Draw(rings)
        rx, ry = s * 0.47, s * 0.14
        rd.ellipse((c - rx, c - ry, c + rx, c + ry), outline=_a(ring, 230), width=max(2, int(s * 0.045)))
        rd.ellipse((c - rx * 0.8, c - ry * 0.8, c + rx * 0.8, c + ry * 0.8),
                   outline=_a(_shade(ring, 0.8), 170), width=max(1, int(s * 0.02)))
        image.alpha_composite(rings)                    # 環的後半
        image.alpha_composite(body)                     # 星球蓋住它
        front = rings.crop((0, int(c), s, s))           # 環的前半再蓋回來
        image.alpha_composite(front, (0, int(c)))
    else:
        image.alpha_composite(body)
    return _done(image, size)


def galaxy(size, rng, colors):
    core, arm = colors or ((255, 244, 220), (150, 170, 255))
    image, draw, s = _canvas(size)
    c = s / 2
    twist = rng.choice((-1, 1)) * rng.uniform(3.2, 4.2)
    for a in range(2):
        for i in range(70):
            t = i / 69
            ang = a * math.pi + t * twist
            rad = s * 0.46 * t
            x = c + math.cos(ang) * rad + rng.gauss(0, s * 0.012)
            y = c + math.sin(ang) * rad * 0.62 + rng.gauss(0, s * 0.012)
            _circle(draw, x, y, s * (0.05 - 0.035 * t), _a(arm, int(215 * (1 - t) ** 1.1) + 30))
    for rad, alpha in ((0.17, 70), (0.11, 130), (0.06, 240)):
        draw.ellipse((c - s * rad, c - s * rad * 0.7, c + s * rad, c + s * rad * 0.7), fill=_a(core, alpha))
    return _done(image, size)


def glint(size, rng, colors):
    (color,) = colors or ((255, 255, 255),)
    image, draw, s = _canvas(size)
    c = s / 2
    _circle(draw, c, c, s * 0.3, _a(color, 26))
    _circle(draw, c, c, s * 0.17, _a(color, 46))
    draw.polygon(_star(c, c, s * 0.48, s * 0.035, 4, 0.0), fill=_a(color, 235))
    draw.polygon(_star(c, c, s * 0.22, s * 0.03, 4, math.pi / 4), fill=_a(color, 200))
    _circle(draw, c, c, s * 0.075, _a((255, 255, 255)))
    return _done(image, size)


def cactus(size, rng, colors):
    body, rib, bloom = colors or ((74, 136, 78), (46, 100, 58), (244, 120, 150))
    image, draw, s = _canvas(size)
    c = s / 2
    lobes = [(c, c, s * 0.24)]
    start = rng.random() * math.tau
    for i in range(rng.randint(2, 3)):
        ang = start + i * math.tau / 3 + rng.uniform(-0.3, 0.3)
        lobes.append((c + math.cos(ang) * s * 0.27, c + math.sin(ang) * s * 0.27, s * 0.13))
    for x, y, r in lobes:
        _circle(draw, x, y, r, _a(rib))
        _circle(draw, x - r * 0.08, y - r * 0.08, r * 0.86, _a(body))
        for i in range(8):
            ang = i * math.tau / 8
            draw.line((x, y, x + math.cos(ang) * r * 0.9, y + math.sin(ang) * r * 0.9),
                      fill=_a(rib), width=max(1, s // 70))
        _circle(draw, x, y, r * 0.2, _a(_shade(body, 1.3)))
    if rng.random() < 0.6:
        x, y, r = lobes[0]
        _circle(draw, x, y, r * 0.3, _a(bloom))
    return _done(image, size)


def floe(size, rng, colors):
    top, edge = colors or ((244, 250, 255), (150, 208, 232))
    image, draw, s = _canvas(size)
    c = s / 2
    outline = _blob(rng, c, c, s * 0.45, points=7, wobble=0.3, squash=rng.uniform(0.6, 0.95),
                    phase=rng.random())
    draw.polygon(outline, fill=_a(edge, 110))
    draw.polygon(_scaled(outline, c, c, 0.86), fill=_a(edge, 235))
    draw.polygon(_scaled(outline, c, c, 0.76, -s * 0.015, -s * 0.02), fill=_a(top))
    return _done(image, size)


def pine(size, rng, colors):
    dark, mid, snow = colors or ((22, 70, 52), (40, 100, 70), (236, 244, 250))
    image, draw, s = _canvas(size)
    c = s / 2
    phase = rng.random()
    points = rng.randint(9, 11)
    draw.polygon(_star(c, c, s * 0.46, s * 0.28, points, phase), fill=_a(dark))
    draw.polygon(_star(c - s * 0.01, c - s * 0.01, s * 0.33, s * 0.19, points, phase + 0.3), fill=_a(mid))
    draw.polygon(_star(c - s * 0.02, c - s * 0.02, s * 0.19, s * 0.1, points, phase + 0.6), fill=_a(snow))
    return _done(image, size)


def crack(size, rng, colors):
    glow, core = colors or ((255, 110, 30), (255, 226, 130))
    image, draw, s = _canvas(size)

    def path(x, y, ang, steps):
        pts = [(x, y)]
        for _ in range(steps):
            ang += rng.uniform(-0.7, 0.7)
            x += math.cos(ang) * s * 0.13
            y += math.sin(ang) * s * 0.13
            pts.append((x, y))
        return pts

    main = path(s * 0.12, s * rng.uniform(0.35, 0.65), rng.uniform(-0.3, 0.3), 6)
    branch = path(*main[rng.randint(2, 4)], rng.choice((-1, 1)) * rng.uniform(0.8, 1.3), 3)
    for pts in (main, branch):
        draw.line(pts, fill=_a(glow, 110), width=int(s * 0.1), joint="curve")
    for pts in (main, branch):
        draw.line(pts, fill=_a(glow, 235), width=int(s * 0.05), joint="curve")
        draw.line(pts, fill=_a(core), width=max(1, int(s * 0.02)), joint="curve")
    return _done(image, size)


def orb(size, rng, colors):
    (glow,) = colors or ((120, 255, 236),)
    image, draw, s = _canvas(size)
    c = s / 2
    for rad, alpha in ((0.46, 18), (0.36, 34), (0.26, 70), (0.17, 130)):
        _circle(draw, c, c, s * rad, _a(glow, alpha))
    _circle(draw, c, c, s * 0.09, _a(_shade(glow, 1.4), 240))
    for i in range(rng.randint(4, 6)):
        ang = math.pi * 0.25 + i * 0.28 + rng.uniform(-0.1, 0.1)
        draw.line((c, c, c + math.cos(ang) * s * 0.4, c + math.sin(ang) * s * 0.4),
                  fill=_a(glow, 90), width=max(1, s // 50))
    return _done(image, size)


SPRITES: Dict[str, Callable] = {
    "palm": palm, "rock": rock, "starfish": starfish, "shell": shell, "coral": coral,
    "fish": fish, "boat": boat, "tree": tree, "flowers": flowers, "lilypad": lilypad,
    "crater": crater, "planet": planet, "galaxy": galaxy, "glint": glint, "cactus": cactus,
    "floe": floe, "pine": pine, "crack": crack, "orb": orb,
}

_cache: Dict[tuple, Image.Image] = {}
_CACHE_LIMIT = 400


def sprite(kind: str, size: int, variant: int, colors: Tuple[Color, ...] = ()) -> Image.Image:
    """取得一個裝飾物圖(有快取)。同樣的參數一定得到同樣的圖。"""
    key = (kind, size, variant, colors)
    image = _cache.get(key)
    if image is None:
        rng = random.Random(zlib.crc32(kind.encode()) * 31 + variant)
        image = SPRITES[kind](size, rng, colors)
        if len(_cache) >= _CACHE_LIMIT:
            _cache.clear()
        _cache[key] = image
    return image


def clear_cache() -> None:
    _cache.clear()


def _with_shadow(image: Image.Image, scale: float) -> Tuple[Image.Image, int]:
    """加上落在右下方的影子;回傳 (新圖, 四周多出的邊距)。"""
    pad = max(2, int(round(4 * scale)))
    offset = max(1, int(round(2.5 * scale)))
    w, h = image.size
    out = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    alpha = Image.new("L", out.size, 0)
    alpha.paste(image.getchannel("A"), (pad + offset, pad + offset))
    alpha = alpha.filter(ImageFilter.GaussianBlur(max(1.0, 1.6 * scale))).point(lambda v: int(v * 0.42))
    out.putalpha(alpha)
    out.alpha_composite(image, (pad, pad))
    return out, pad


# ---------------------------------------------------------------------------
# 擺放
# ---------------------------------------------------------------------------
def place(field: np.ndarray, rects: Sequence[Rect], rules: Sequence[DecorRule], *,
          seed: int, density: float = 1.0, scale: float = 1.0) -> List[Placement]:
    """決定每個裝飾物放哪裡。

    field 是海岸距離場(單位:100% 縮放下的像素;負 = 陸地)。
    裝飾物不會蓋到圖示,也不會彼此重疊。
    """
    if not rules or density <= 0:
        return []
    height, width = field.shape
    cell = CELL * scale
    cols = int(math.ceil(width / cell))
    rows = int(math.ceil(height / cell))
    rng = np.random.default_rng(seed + 909)
    jitter_x = rng.random((rows, cols))
    jitter_y = rng.random((rows, cols))
    pick = rng.random((rows, cols))
    size_u = rng.random((rows, cols))
    angle_u = rng.random((rows, cols))
    variant = rng.integers(0, VARIANTS, (rows, cols))

    if rects:
        r = np.asarray(rects, dtype=np.float32)
        left, top, right, bottom = r[:, 0] - 2, r[:, 1] - 2, r[:, 2] + 2, r[:, 3] + 2
    placed_x: List[float] = []
    placed_y: List[float] = []
    placed_r: List[float] = []
    out: List[Placement] = []

    for row in range(rows):
        for col in range(cols):
            x = int((col + 0.12 + 0.76 * jitter_x[row, col]) * cell)
            y = int((row + 0.12 + 0.76 * jitter_y[row, col]) * cell)
            if x >= width or y >= height:
                continue
            s = float(field[y, x])
            chosen = None
            acc = 0.0
            u = pick[row, col]
            for rule in rules:
                if rule.lo <= s < rule.hi:
                    acc += rule.chance * density
                    if u < acc:
                        chosen = rule
                        break
            if chosen is None:
                continue
            lo, hi = chosen.size
            size = int(round((lo + (hi - lo) * size_u[row, col]) * scale / 2)) * 2
            if size < 6:
                continue
            half = size / 2
            if rects and bool(np.any((x + half > left) & (x - half < right)
                                     & (y + half > top) & (y - half < bottom))):
                continue
            if placed_x:
                px = np.asarray(placed_x)
                py = np.asarray(placed_y)
                reach = np.asarray(placed_r) + half * 0.8
                if bool(np.any((px - x) ** 2 + (py - y) ** 2 < reach ** 2)):
                    continue
            placed_x.append(x)
            placed_y.append(y)
            placed_r.append(half * 0.8)
            out.append(Placement(chosen, x, y, size, (angle_u[row, col] - 0.5) * 360.0 * chosen.spin,
                                 int(variant[row, col])))
    return out


def place_companions(field: np.ndarray, rects: Sequence[Rect], tags: Sequence[str],
                     table: Dict[str, DecorRule], *, seed: int, scale: float = 1.0) -> List[Placement]:
    """每個圖示旁邊放一個代表它檔案類型的裝飾物(例如資料夾旁邊一棵椰子樹)。

    tags 與 rects 一一對應(檔案類型);table 是 檔案類型 → 規則。
    從圖示外緣開始一圈一圈往外找,取第一個落在規則地帶(lo~hi)、
    不蓋到任何圖示、也不跟其他裝飾物重疊的位置;找不到就不放。
    起始方向只由種子與這個圖示的位置決定,所以移動別的圖示不會讓它換位置。
    """
    if not rects or not table:
        return []
    height, width = field.shape
    boxes = np.asarray(rects, dtype=np.float32)
    left, top, right, bottom = boxes[:, 0] - 2, boxes[:, 1] - 2, boxes[:, 2] + 2, boxes[:, 3] + 2
    placed: List[Tuple[float, float, float]] = []
    out: List[Placement] = []
    for rect, tag in zip(rects, tags):
        rule = table.get(tag)
        if rule is None:
            continue
        rng = random.Random(f"{seed}:{rect[0]}:{rect[1]}")
        lo, hi = rule.size
        size = int(round((lo + (hi - lo) * rng.random()) * scale / 2)) * 2
        if size < 6:
            continue
        half = size / 2
        cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
        rx, ry = (rect[2] - rect[0]) / 2, (rect[3] - rect[1]) / 2
        start = rng.random() * math.tau
        found = None
        for ring in range(12):
            gap = (3 + ring * 8) * scale + half
            for step in range(16):
                angle = start + step * math.tau / 16
                x, y = cx + math.cos(angle) * (rx + gap), cy + math.sin(angle) * (ry + gap)
                if not (half <= x < width - half and half <= y < height - half):
                    continue
                if not rule.lo <= float(field[int(y), int(x)]) < rule.hi:
                    continue
                if bool(np.any((x + half > left) & (x - half < right) & (y + half > top) & (y - half < bottom))):
                    continue
                if any((px - x) ** 2 + (py - y) ** 2 < (pr + half * 0.8) ** 2 for px, py, pr in placed):
                    continue
                found = (x, y)
                break
            if found:
                break
        if found is None:
            continue
        x, y = found
        placed.append((x, y, half * 0.8))
        out.append(Placement(rule, int(x), int(y), size, (rng.random() - 0.5) * 360.0 * rule.spin,
                             rng.randrange(VARIANTS)))
    return out


def footprint(placements: Sequence[Placement]) -> List[Rect]:
    """裝飾物佔的方框;交給 place() 當成要避開的區域。"""
    return [(p.x - p.size // 2, p.y - p.size // 2, p.x + p.size // 2, p.y + p.size // 2) for p in placements]


def draw(image: Image.Image, placements: Sequence[Placement], scale: float = 1.0) -> None:
    """把裝飾物畫到圖上(直接修改 image)。"""
    for p in sorted(placements, key=lambda q: (q.y, q.x)):
        rule = p.rule
        art = sprite(rule.kind, p.size, p.variant, rule.colors)
        if rule.spin and abs(p.angle) > 0.5:
            art = art.rotate(p.angle, resample=_RES.BICUBIC, expand=True)
        if rule.alpha < 1.0:
            art = art.copy()
            art.putalpha(art.getchannel("A").point(lambda v, a=rule.alpha: int(v * a)))
        pad = 0
        if rule.shadow:
            art, pad = _with_shadow(art, scale)
        image.paste(art, (p.x - art.width // 2, p.y - art.height // 2), art)
