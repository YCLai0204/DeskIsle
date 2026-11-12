"""把地形畫成圖片。只用 numpy 與 Pillow,不碰任何 Windows API。"""
from __future__ import annotations

from typing import Optional, Sequence

import numpy as np
from PIL import Image, ImageDraw

from . import decor
from .terrain import Rect, fbm, shore_field, smoothstep
from .themes import Theme

TWO_PI = np.float32(2.0 * np.pi)
_LUT_STEP = 0.25   # 色帶查表的精細度(像素)


def _color_lut(theme: Theme):
    """把色帶控制點展開成查表:(起點距離, 表)。"""
    xs = np.array([p for p, _ in theme.stops], dtype=np.float32)
    grid = np.arange(xs[0], xs[-1] + _LUT_STEP, _LUT_STEP, dtype=np.float32)
    lut = np.empty((grid.size, 3), dtype=np.float32)
    for channel in range(3):
        ys = np.array([c[channel] for _, c in theme.stops], dtype=np.float32)
        lut[:, channel] = np.interp(grid, xs, ys)
    return float(xs[0]), lut


def _add_sparkles(rgb: np.ndarray, s: np.ndarray, theme: Theme, seed: int, scale: float) -> None:
    """在水域撒上固定位置的光點(星星、發光浮游生物)。"""
    height, width = s.shape
    count = int(theme.sparkles * width * height / 1e4 / (scale * scale))
    if count <= 0:
        return
    rng = np.random.default_rng(seed + 808)
    xs = rng.integers(0, width, count)
    ys = rng.integers(0, height, count)
    brightness = rng.random(count).astype(np.float32) ** 3     # 多數暗、少數亮
    palette = np.array(theme.sparkle_colors, dtype=np.float32)
    colors = palette[rng.integers(0, len(palette), count)] * (0.22 + 0.78 * brightness)[:, None]
    keep = s[ys, xs] > 8.0
    xs, ys, colors, brightness = xs[keep], ys[keep], colors[keep], brightness[keep]
    rgb[ys, xs] = np.maximum(rgb[ys, xs], colors)
    # 較亮的再往四周暈開一格
    big = brightness > (0.5 if scale < 1.25 else 0.15)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        bx = np.clip(xs[big] + dx, 0, width - 1)
        by = np.clip(ys[big] + dy, 0, height - 1)
        rgb[by, bx] = np.maximum(rgb[by, bx], colors[big] * 0.45)


def object_rules(count: int, zone: str, amount: float, size: float) -> list:
    """小物件的擺放規則:每個小物件一條(放「都可以」時陸地、海上各一條),機率平分。"""
    zones = {"water": [(40.0, 1e9)], "land": [(-1e9, -16.0)], "both": [(-1e9, -16.0), (40.0, 1e9)]}[zone]
    chance = 0.012 * amount / max(1, count) / len(zones)
    size_range = (max(8, int(size * 0.75)), max(10, int(size * 1.25)))
    return [decor.DecorRule(f"user{i}", lo, hi, chance, size_range, spin=0.06)
            for i in range(count) for lo, hi in zones]


def render(width: int, height: int, rects: Sequence[Rect], theme: Theme, *,
           margin: float = 46.0, blend: float = 26.0, roughness: float = 22.0,
           seed: int = 7, scale: float = 1.0, decorations: float = 1.0,
           debug: bool = False, land_photo: Optional[np.ndarray] = None,
           water_photo: Optional[np.ndarray] = None, tags: Sequence[str] = (),
           objects: Sequence[Image.Image] = (), objects_zone: str = "water", objects_amount: float = 1.0,
           objects_size: float = 64.0) -> Image.Image:
    """畫出一張 width×height 的 RGB 圖片。

    rects 是圖示矩形(圖片座標);scale 是縮放比例,像素類參數都會乘上它
    (畫縮小的預覽圖時,把矩形與 scale 一起縮小即可)。
    decorations 是裝飾物密度(0 = 不畫)。debug=True 會畫出圖示外框。
    land_photo / water_photo 是使用者的圖片(已經裁成 height×width×3,見 photo.cover),
    分別鋪在陸地上、海上(可以同時用)。
    objects 是使用者的小物件(RGBA),依 objects_zone(water / land / both)、
    objects_amount(數量倍率)、objects_size(100% 縮放下的像素)散落在桌布上。
    tags 與 rects 一一對應,是每個圖示的檔案類型(見 filetypes.py);有的話會在圖示旁邊
    放代表該類型的裝飾物(主題的 companions)。
    """
    sd = shore_field(
        width, height, rects,
        margin=margin * scale, blend=blend * scale, roughness=roughness * scale,
        seed=seed, noise_cell=150 * scale,
    )
    s = sd / np.float32(scale)  # 換回 100% 縮放下的像素,主題參數都以此為單位
    del sd

    # 平滑的紋理以較低解析度計算(縮放比例小的預覽圖就不必再降)
    coarse = 2 if scale >= 0.75 else 1

    land = smoothstep(1.5, -1.5, s)   # 1 = 陸地,0 = 水域,海岸線上平滑過渡
    water = 1.0 - land

    # ---- 色帶 --------------------------------------------------------------
    # 深水區的取色位置加一點低頻擾動,避免整片同色
    drift = fbm(width, height, seed + 101, cell=420 * scale, octaves=3, coarse=coarse * 2)
    s_color = s + drift * (theme.deep_variation * smoothstep(25.0, 220.0, s))
    x0, lut = _color_lut(theme)
    index = np.clip((s_color - x0) * (1.0 / _LUT_STEP), 0, lut.shape[0] - 1).astype(np.int32)
    rgb = lut[index]
    del drift, s_color, index

    # ---- 質感(乘在亮度上) -------------------------------------------------
    rng = np.random.default_rng(seed + 202)
    grain = rng.random((height, width), dtype=np.float32) - 0.5
    mottle = fbm(width, height, seed + 303, cell=95 * scale, octaves=3, coarse=coarse * 2)
    bumps = fbm(width, height, seed + 404, cell=46 * scale, octaves=3, coarse=coarse)
    # 簡易浮雕:高度與左上方鄰點的差 = 來自左上的光
    step = max(1, int(round(2 * scale)))
    relief = np.clip((bumps - np.roll(bumps, (step, step), axis=(0, 1))) * 6.0, -1.0, 1.0)
    del bumps

    land_tex = theme.land_grain * 2.0 * grain + theme.land_mottle * mottle + theme.land_relief * relief
    water_tex = theme.water_grain * 2.0 * grain + theme.water_relief * relief
    if theme.water_shimmer:
        water_tex += theme.water_shimmer * fbm(width, height, seed + 505, cell=64 * scale, octaves=3, coarse=coarse * 2)
    shade = 1.0 + land * land_tex + water * water_tex
    rgb *= shade[..., None]
    del grain, mottle, relief, land_tex, water_tex, shade

    # ---- 彩色雲霧(星雲) ---------------------------------------------------
    if theme.tint and theme.tint_strength:
        for i, color in enumerate(theme.tint):
            cloud = fbm(width, height, seed + 1100 + i * 37, cell=300 * scale, octaves=4, coarse=coarse * 2)
            cloud = np.maximum(cloud + 0.1, 0.0) ** 2 * (theme.tint_strength * water)
            rgb += cloud[..., None] * np.array(color, dtype=np.float32)
            del cloud

    # ---- 使用者的圖片 ------------------------------------------------------
    # 在浪花之前合成:海岸線上的沙灘、淺灘與浪花仍然是主題的,島的輪廓才看得清楚
    rules = theme.decor
    if land_photo is not None:
        weight = smoothstep(-7.0, -16.0, s)              # 海岸留一圈主題的沙灘
        rim = smoothstep(-48.0, -10.0, s)                # 靠近海岸稍微壓暗,島的邊緣才有立體感
        rgb += (land_photo * (1.0 - 0.24 * rim)[..., None] - rgb) * weight[..., None]
        rules = tuple(r for r in rules if r.lo >= -16)   # 不在圖片上放樹、花
        del weight, rim
    if water_photo is not None:
        weight = smoothstep(12.0, 34.0, s)               # 海岸邊留一圈主題的淺灘
        rim = 1.0 - smoothstep(12.0, 90.0, s)
        rgb += (water_photo * (1.0 - 0.24 * rim)[..., None] - rgb) * weight[..., None]
        rules = tuple(r for r in rules if r.hi <= 34)    # 不在圖片上放船、魚、星球
        del weight, rim

    # ---- 浪花 --------------------------------------------------------------
    lam = theme.wave_length
    edge = smoothstep(-1.0, 0.8, s) * (1.0 - smoothstep(2.5, 8.0, s)) * theme.shore_foam
    if theme.wave_strength:
        # 沿等高線的波紋;離岸後才扭曲,讓第一圈貼齊海岸線
        warp = fbm(width, height, seed + 606, cell=120 * scale, octaves=2, coarse=coarse * 2)
        phase = s / lam + warp * (0.55 * smoothstep(0.0, lam, s))
        band = 0.5 + 0.5 * np.cos(TWO_PI * phase)
        band *= band            # ^2
        band = band * band * band * band * band   # ^10:只留下細細的尖峰
        # 用雜訊把外圈波紋打斷成一段一段
        breakup = smoothstep(-0.2, 0.25, fbm(width, height, seed + 707, cell=80 * scale, octaves=2, coarse=coarse * 2))
        waves = band * breakup * np.exp(np.maximum(s, 0.0) * (-1.0 / theme.wave_fade))
        waves *= smoothstep(lam * 0.45, lam * 0.9, s) * theme.wave_strength
        alpha = np.maximum(waves, edge)[..., None]
        del warp, phase, band, breakup, waves
    else:
        alpha = edge[..., None]
    foam = np.array(theme.foam, dtype=np.float32)
    rgb += (foam - rgb) * alpha
    del alpha, edge

    if theme.sparkles:
        _add_sparkles(rgb, s, theme, seed, scale)

    np.clip(rgb, 0, 255, out=rgb)
    image = Image.fromarray(rgb.astype(np.uint8), "RGB")
    del rgb

    # 放的順序:檔案類型裝飾物 → 小物件 → 一般裝飾物;後放的會避開先放的
    companions = []
    if decorations > 0 and tags and theme.companions:
        companions = decor.place_companions(s, rects, tags, dict(theme.companions), seed=seed, scale=scale)
    custom = {}
    extras = []
    if objects and objects_amount > 0:
        custom = {f"user{i}": sprite for i, sprite in enumerate(objects)}
        extras = decor.place(s, list(rects) + decor.footprint(companions),
                             object_rules(len(objects), objects_zone, objects_amount, objects_size),
                             seed=seed + 5150, density=1.0, scale=scale)
    placements = []
    if decorations > 0 and rules:
        taken = list(rects) + decor.footprint(companions) + decor.footprint(extras)
        placements = decor.place(s, taken, rules, seed=seed, density=decorations, scale=scale)
    decor.draw(image, placements + companions + extras, scale, custom)

    if debug:
        draw = ImageDraw.Draw(image)
        for left, top, right, bottom in rects:
            draw.rectangle((left, top, right - 1, bottom - 1), outline=(255, 0, 80), width=1)
    return image
