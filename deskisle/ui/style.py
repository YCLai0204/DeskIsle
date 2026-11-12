"""設定介面的外觀:配色(淺色/深色)、字型,以及用 Pillow 畫的圖。

tkinter 畫不出反鋸齒的圓角與圓形,所以圓角、開關、滑桿圓鈕、圖示都先用 Pillow
以 4 倍大小畫好再縮小,做成圖片貼到 Canvas 上(快取在 widgets.Kit,同樣的圖只畫一次)。
不需要額外套件。
"""
from __future__ import annotations

import sys
import tkinter as tk
from dataclasses import dataclass
from tkinter import font as tkfont
from typing import Dict, Optional, Tuple

from PIL import Image, ImageDraw

from ..engine.render import render
from ..engine.themes import Theme

SUPERSAMPLE = 4
_RES = getattr(Image, "Resampling", Image)


@dataclass(frozen=True)
class Palette:
    dark: bool
    bg: str             # 內容區底色
    sidebar: str        # 左側導覽列
    card: str           # 卡片
    card_hover: str
    field: str          # 輸入框底色
    border: str
    border_strong: str
    text: str
    muted: str          # 說明文字
    subtle: str         # 停用的文字
    accent: str
    accent_hover: str
    accent_press: str
    on_accent: str      # 強調色上的文字
    accent_soft: str    # 選取項目的底色
    nav_hover: str
    nav_selected: str
    track: str          # 滑桿軌道
    ok: str
    warn: str
    warn_soft: str
    danger: str
    preview_bg: str     # 預覽圖還沒出來時的底色


# 配色取自程式圖示:深海藍、淺灘、沙灘
LIGHT = Palette(
    dark=False, bg="#f3f5f8", sidebar="#e9edf2", card="#ffffff", card_hover="#f6f8fa", field="#f3f5f8",
    border="#e1e6ec", border_strong="#c3ccd6", text="#17202a", muted="#5d6a79", subtle="#9aa5b1",
    accent="#0f6fb5", accent_hover="#1b7cc2", accent_press="#0b5d98", on_accent="#ffffff",
    accent_soft="#e4f0fa", nav_hover="#e0e6ed", nav_selected="#d5e0eb", track="#d5dce4",
    ok="#1f9d68", warn="#a8650a", warn_soft="#fdf0d9", danger="#c4314b", preview_bg="#e8edf2",
)
DARK = Palette(
    dark=True, bg="#0f141a", sidebar="#0a0e13", card="#161c24", card_hover="#1b232d", field="#0f141a",
    border="#232c37", border_strong="#364250", text="#e6ecf2", muted="#8a97a6", subtle="#566170",
    accent="#4cb0e6", accent_hover="#67bfee", accent_press="#3a9bd0", on_accent="#04192a",
    accent_soft="#132b3c", nav_hover="#121820", nav_selected="#18212b", track="#2a3440",
    ok="#3ccf8e", warn="#f0b44a", warn_soft="#33290f", danger="#f07167", preview_bg="#0b0f14",
)


# ---------------------------------------------------------------------------
# 字型
# ---------------------------------------------------------------------------
_FONT_CANDIDATES = {
    "win32": ("Microsoft JhengHei UI", "Microsoft JhengHei", "Segoe UI"),
    "darwin": ("PingFang TC", "Heiti TC", "Helvetica Neue"),
}
_MONO_CANDIDATES = ("Cascadia Mono", "Consolas", "Menlo", "SF Mono", "Courier New")

# 名稱 → (點數, 粗細)
FONT_SPECS = {
    "title": (19, "bold"),      # 頁面標題
    "brand": (13, "bold"),      # 側邊欄的程式名稱
    "h2": (11, "bold"),         # 區塊標題
    "body": (10, "normal"),
    "bold": (10, "bold"),
    "caption": (9, "normal"),   # 說明文字
    "small": (8, "normal"),
}


def pick_font(root: tk.Misc) -> str:
    families = set(tkfont.families(root))
    for name in _FONT_CANDIDATES.get(sys.platform, ()) + ("Noto Sans CJK TC", "Noto Sans TC"):
        if name in families:
            return name
    return tkfont.nametofont("TkDefaultFont").actual("family")


def make_fonts(root: tk.Misc) -> Dict[str, tkfont.Font]:
    family = pick_font(root)
    bump = 3 if sys.platform == "darwin" else 0     # macOS 的點數換算比較小
    fonts = {name: tkfont.Font(root=root, family=family, size=size + bump, weight=weight)
             for name, (size, weight) in FONT_SPECS.items()}
    families = set(tkfont.families(root))
    mono = next((name for name in _MONO_CANDIDATES if name in families), "Courier")
    fonts["mono"] = tkfont.Font(root=root, family=mono, size=9 + bump)
    return fonts


# ---------------------------------------------------------------------------
# 圖
# ---------------------------------------------------------------------------
def rgba(color: str, alpha: int = 255) -> Tuple[int, int, int, int]:
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5)) + (alpha,)


def _big(width: int, height: int):
    image = Image.new("RGBA", (max(1, width) * SUPERSAMPLE, max(1, height) * SUPERSAMPLE), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image)


def _small(image: Image.Image, width: int, height: int) -> Image.Image:
    return image.resize((max(1, width), max(1, height)), _RES.LANCZOS)


def round_rect(width: int, height: int, radius: float, fill: Optional[str] = None,
               outline: Optional[str] = None, line: int = 1) -> Image.Image:
    """反鋸齒的圓角矩形(外面透明)。outline 的線寬 line 往內畫。"""
    image, draw = _big(width, height)
    k = SUPERSAMPLE
    radius = max(0.0, min(radius, width / 2, height / 2))
    draw.rounded_rectangle((0, 0, width * k - 1, height * k - 1), radius=radius * k,
                           fill=rgba(fill) if fill else None,
                           outline=rgba(outline) if outline else None, width=line * k if outline else 0)
    return _small(image, width, height)


def rounded(image: Image.Image, radius: int) -> Image.Image:
    """把圖片切成圓角(角落變透明)。"""
    width, height = image.size
    k = SUPERSAMPLE
    mask = Image.new("L", (width * k, height * k), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width * k - 1, height * k - 1), radius=radius * k, fill=255)
    out = image.convert("RGBA")
    out.putalpha(_small(mask, width, height))
    return out


def icon(name: str, size: int, color: str) -> Image.Image:
    """線條圖示(以 24×24 的格子設計)。"""
    image, draw = _big(size, size)
    k = size * SUPERSAMPLE / 24
    c = rgba(color)
    w = max(SUPERSAMPLE, int(round(1.8 * k)))

    def pts(*points):
        return [(x * k, y * k) for x, y in points]

    def box(x0, y0, x1, y1):
        return (x0 * k, y0 * k, x1 * k, y1 * k)

    if name == "look":            # 一張風景圖:外框、山、太陽
        draw.rounded_rectangle(box(3, 4, 21, 20), radius=3 * k, outline=c, width=w)
        draw.line(pts((4, 17), (9, 11.5), (13, 15.5), (16, 12.5), (20.5, 17)), fill=c, width=w, joint="curve")
        draw.ellipse(box(14, 6.5, 17.6, 10.1), fill=c)
    elif name == "screens":       # 螢幕
        draw.rounded_rectangle(box(2.5, 4, 21.5, 16.5), radius=2.5 * k, outline=c, width=w)
        draw.line(pts((12, 16.5), (12, 20)), fill=c, width=w)
        draw.line(pts((8, 20.5), (16, 20.5)), fill=c, width=w)
    elif name == "behavior":      # 三條滑桿
        for y, x in ((6.5, 15), (12, 8), (17.5, 13)):
            draw.line(pts((3, y), (21, y)), fill=c, width=w)
            draw.ellipse(box(x - 2.6, y - 2.6, x + 2.6, y + 2.6), fill=c)
    elif name == "test":          # 燒杯
        draw.line(pts((9, 3.5), (9, 9.5), (4.5, 19), (5.6, 20.5), (18.4, 20.5), (19.5, 19), (15, 9.5), (15, 3.5)),
                  fill=c, width=w, joint="curve")
        draw.line(pts((7.5, 3.5), (16.5, 3.5)), fill=c, width=w)
        draw.line(pts((6.6, 15), (17.4, 15)), fill=c, width=w)
    elif name == "refresh":       # 繞一圈的箭頭
        draw.arc(box(4, 4, 20, 20), 330, 630, fill=c, width=w)
        draw.polygon(pts((10.6, 1.2), (15.6, 4), (10.6, 6.8)), fill=c)
    elif name == "restore":       # 回上一步
        draw.line(pts((4.5, 9), (14, 9)), fill=c, width=w)
        draw.arc(box(8.5, 9, 19.5, 20), 270, 450, fill=c, width=w)
        draw.line(pts((14, 20), (9, 20)), fill=c, width=w)
        draw.line(pts((8.5, 4.8), (4.3, 9), (8.5, 13.2)), fill=c, width=w, joint="curve")
    elif name == "power":         # 電源
        draw.arc(box(4.5, 5, 19.5, 20), 300, 600, fill=c, width=w)
        draw.line(pts((12, 3), (12, 11.5)), fill=c, width=w)
    elif name == "chevron":       # 往下的箭頭(下拉選單)
        draw.line(pts((6.5, 9.5), (12, 15), (17.5, 9.5)), fill=c, width=w, joint="curve")
    elif name == "download":      # 匯出:往下的箭頭 + 托盤
        draw.line(pts((12, 3.5), (12, 14.5)), fill=c, width=w)
        draw.line(pts((7.5, 10.5), (12, 15), (16.5, 10.5)), fill=c, width=w, joint="curve")
        draw.line(pts((4, 15.5), (4, 19.5), (20, 19.5), (20, 15.5)), fill=c, width=w, joint="curve")
    elif name == "check":
        draw.line(pts((5, 12.5), (10, 17.5), (19.5, 7)), fill=c, width=int(w * 1.15), joint="curve")
    elif name == "brush":         # 套用:畫筆
        draw.line(pts((19.5, 4.5), (10.5, 13.5)), fill=c, width=w)
        draw.ellipse(box(4, 13, 11.5, 20.5), fill=c)
    else:
        raise ValueError(name)
    return _small(image, size, size)


# 主題縮圖用的假圖示:左上一群、右下一個,看得出陸地與水
_SWATCH_RECTS = ((0.06, 0.08, 0.20, 0.32), (0.06, 0.38, 0.20, 0.62), (0.22, 0.08, 0.36, 0.32),
                 (0.66, 0.56, 0.80, 0.82))


def theme_swatch(theme: Theme, size: Tuple[int, int], scale: float) -> Image.Image:
    """一張很小的主題示意圖(用固定的假圖示排列畫)。"""
    width, height = size
    rects = [(int(l * width), int(t * height), int(r * width), int(b * height)) for l, t, r, b in _SWATCH_RECTS]
    return render(width, height, rects, theme, margin=46, blend=26, roughness=22, seed=11,
                  scale=scale, decorations=1.0)
