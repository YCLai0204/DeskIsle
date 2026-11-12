"""設定介面的外觀:配色、字型、ttk 樣式,以及標題列與主題縮圖。

全部用 tkinter 內建的 ttk("clam" 為底)加上 Pillow 畫的圖,不需要額外套件。
"""
from __future__ import annotations

import math
import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from typing import Dict, Tuple

from PIL import Image, ImageDraw

from .render import render
from .themes import Theme

# ---- 配色(取自程式圖示:深海藍 → 淺灘 → 沙灘) ------------------------------
BG = "#eef3f7"            # 視窗底色
CARD = "#ffffff"          # 卡片
BORDER = "#d8e1e9"
TEXT = "#1c2a35"
MUTED = "#6a7b89"
ACCENT = "#1474b0"
ACCENT_DARK = "#0e5b8c"
ACCENT_SOFT = "#e2eff8"
WARN = "#b5650a"
OK = "#2f9e6a"
SCREEN = "#16212b"        # 預覽外框(像一台螢幕)

_FONT_CANDIDATES = {
    "win32": ("Microsoft JhengHei UI", "Microsoft JhengHei", "Segoe UI"),
    "darwin": ("PingFang TC", "Heiti TC", "Helvetica Neue"),
}


def pick_font(root: tk.Misc) -> str:
    families = set(tkfont.families(root))
    for name in _FONT_CANDIDATES.get(sys.platform, ()) + ("Noto Sans CJK TC", "Noto Sans TC"):
        if name in families:
            return name
    return tkfont.nametofont("TkDefaultFont").actual("family")


def _hex(color: str) -> Tuple[int, int, int]:
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def checkbox_image(size: int, gap: int, fill: str, border: str, check: str = "") -> Image.Image:
    """圓角方框的勾選框(右邊留 gap 的透明空白,當作與文字的間距)。"""
    big = size * 4
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2, 2, big - 3, big - 3), radius=big // 5, fill=_hex(fill) + (255,),
                           outline=_hex(border) + (255,), width=max(4, big // 12))
    if check:
        draw.line([(big * 0.26, big * 0.52), (big * 0.43, big * 0.69), (big * 0.75, big * 0.33)],
                  fill=_hex(check) + (255,), width=max(6, big // 8), joint="curve")
    small = image.resize((size, size), getattr(Image, "Resampling", Image).LANCZOS)
    canvas = Image.new("RGBA", (size + gap, size), (0, 0, 0, 0))
    canvas.paste(small, (0, 0))
    return canvas


def _photo(image: Image.Image) -> tk.PhotoImage:
    import base64
    import io
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return tk.PhotoImage(data=base64.b64encode(buffer.getvalue()))


def setup(root: tk.Tk, scale: float = 1.0) -> Dict[str, tuple]:
    """設定整個視窗的 ttk 樣式;回傳常用字型。"""
    family = pick_font(root)
    fonts = {
        "body": (family, 10),
        "small": (family, 9),
        "bold": (family, 10, "bold"),
        "section": (family, 11, "bold"),
        "title": (family, 17, "bold"),
        "subtitle": (family, 10),
    }
    root.configure(background=BG)
    root.option_add("*Font", fonts["body"])
    root.option_add("*TCombobox*Listbox.font", fonts["body"])

    style = ttk.Style(root)
    style.theme_use("clam")
    # 預設(分頁內容)是白色卡片
    style.configure(".", background=CARD, foreground=TEXT, font=fonts["body"], bordercolor=BORDER,
                    lightcolor=CARD, darkcolor=CARD, focuscolor=ACCENT, troughcolor=BORDER,
                    selectbackground=ACCENT, selectforeground="white")
    style.configure("App.TFrame", background=BG)
    style.configure("App.TLabel", background=BG, foreground=MUTED, font=fonts["small"])
    style.configure("Card.TFrame", background=CARD, relief="solid", borderwidth=1, bordercolor=BORDER)
    style.configure("Muted.TLabel", foreground=MUTED, font=fonts["small"])
    style.configure("Section.TLabel", foreground=TEXT, font=fonts["section"])
    style.configure("Value.TLabel", foreground=ACCENT, font=fonts["bold"])
    style.configure("Warn.TLabel", foreground=WARN, font=fonts["small"])
    style.configure("Screen.TLabel", background=SCREEN, foreground="#b9c7d3", anchor="center")
    style.configure("Screen.TFrame", background=SCREEN)

    # 分頁
    style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
    style.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(18, 8), borderwidth=0,
                    font=fonts["bold"], lightcolor=BG, bordercolor=BG)
    style.map("TNotebook.Tab",
              background=[("selected", CARD), ("active", ACCENT_SOFT)],
              foreground=[("selected", ACCENT)],
              lightcolor=[("selected", CARD)], bordercolor=[("selected", BORDER)])

    # 按鈕
    style.configure("TButton", background=CARD, foreground=TEXT, padding=(14, 7), borderwidth=1,
                    bordercolor=BORDER, lightcolor=CARD, darkcolor=CARD, focusthickness=0)
    style.map("TButton", background=[("pressed", ACCENT_SOFT), ("active", ACCENT_SOFT)],
              bordercolor=[("active", ACCENT)])
    style.configure("Accent.TButton", background=ACCENT, foreground="white", padding=(20, 9),
                    bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT, font=fonts["bold"])
    style.map("Accent.TButton",
              background=[("disabled", "#9dbfd6"), ("pressed", ACCENT_DARK), ("active", ACCENT_DARK)],
              foreground=[("disabled", "#eef5fa")],
              bordercolor=[("active", ACCENT_DARK)],
              lightcolor=[("active", ACCENT_DARK)], darkcolor=[("active", ACCENT_DARK)])
    style.configure("Ghost.TButton", background=CARD, foreground=MUTED, bordercolor=CARD,
                    lightcolor=CARD, darkcolor=CARD, padding=(10, 7))
    style.map("Ghost.TButton", foreground=[("active", "#b3261e")], background=[("active", CARD)],
              bordercolor=[("active", CARD)])
    style.configure("Small.TButton", padding=(10, 4))

    # 勾選框:自己畫的圓角方框與打勾
    size, gap = int(round(16 * scale)), int(round(8 * scale))
    images = {
        "off": checkbox_image(size, gap, CARD, "#a9b8c5"),
        "hover": checkbox_image(size, gap, ACCENT_SOFT, ACCENT),
        "on": checkbox_image(size, gap, ACCENT, ACCENT, "#ffffff"),
        "on_hover": checkbox_image(size, gap, ACCENT_DARK, ACCENT_DARK, "#ffffff"),
        "off_disabled": checkbox_image(size, gap, BG, BORDER),
        "on_disabled": checkbox_image(size, gap, "#9dbfd6", "#9dbfd6", "#ffffff"),
    }
    photos = {key: _photo(image) for key, image in images.items()}
    root._deskisle_style_images = photos   # 圖片要一直有人參考,不然會被回收
    if "Pretty.Checkbutton.indicator" not in style.element_names():
        style.element_create(
            "Pretty.Checkbutton.indicator", "image", photos["off"],
            ("disabled", "selected", photos["on_disabled"]), ("disabled", photos["off_disabled"]),
            ("active", "selected", photos["on_hover"]), ("selected", photos["on"]),
            ("active", photos["hover"]), sticky="w",
        )
    style.layout("TCheckbutton", [("Checkbutton.padding", {"sticky": "nswe", "children": [
        ("Pretty.Checkbutton.indicator", {"side": "left", "sticky": ""}),
        ("Checkbutton.label", {"side": "left", "sticky": "nswe"}),
    ]})])
    style.configure("TCheckbutton", background=CARD, padding=(0, 4))
    style.map("TCheckbutton", background=[("active", CARD), ("disabled", CARD)],
              foreground=[("disabled", MUTED), ("active", ACCENT)])

    # 滑桿、輸入框
    style.configure("Horizontal.TScale", background=ACCENT, troughcolor="#e4ebf1", bordercolor="#cfdae3",
                    lightcolor=ACCENT, darkcolor=ACCENT, gripcount=0, sliderthickness=14)
    style.map("Horizontal.TScale", background=[("active", ACCENT_DARK)])
    style.configure("TSpinbox", fieldbackground=CARD, arrowcolor=MUTED, padding=(6, 3), arrowsize=12)
    style.configure("TSeparator", background=BORDER)
    style.configure("TLabelframe", background=CARD, bordercolor=BORDER)
    style.configure("TLabelframe.Label", background=CARD, foreground=MUTED, font=fonts["bold"])
    return fonts


# ---------------------------------------------------------------------------
# 圖
# ---------------------------------------------------------------------------
def banner(width: int, height: int) -> Image.Image:
    """標題列背景:由深海藍漸層到淺海,底部一道沙色細線。"""
    left = (12, 70, 116)
    right = (24, 140, 172)
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for x in range(width):
        t = x / max(1, width - 1)
        draw.line((x, 0, x, height), fill=tuple(int(a + (b - a) * t) for a, b in zip(left, right)))
    # 兩道淡淡的浪
    for i, y in enumerate((0.62, 0.80)):
        points = [(x, height * y + 3 * math.sin(x / (38 + 9 * i))) for x in range(0, width + 4, 4)]
        draw.line(points, fill=(52, 148, 184), width=1)
    draw.rectangle((0, height - 3, width, height), fill=(232, 207, 150))
    return image


# 主題縮圖用的假圖示:左上一群、右下一個,看得出陸地與水
_SWATCH_RECTS = ((0.06, 0.08, 0.20, 0.32), (0.06, 0.38, 0.20, 0.62), (0.22, 0.08, 0.36, 0.32),
                 (0.66, 0.56, 0.80, 0.82))


def theme_swatch(theme: Theme, size: Tuple[int, int], scale: float) -> Image.Image:
    """一張很小的主題示意圖(用固定的假圖示排列畫)。"""
    width, height = size
    rects = [(int(l * width), int(t * height), int(r * width), int(b * height)) for l, t, r, b in _SWATCH_RECTS]
    image = render(width, height, rects, theme, margin=46, blend=26, roughness=22, seed=11,
                   scale=scale, decorations=1.0)
    return image
