"""設定視窗右邊的即時預覽:把目前的圖示排列畫成縮小版。

多螢幕時每個螢幕左上角標上編號(對應「螢幕」頁的「螢幕 N」);
沒有選要更新的螢幕畫成灰色斜線。
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

from .. import system
from ..config import Config
from ..engine.layout import DesktopLayout
from ..watcher import render_screen

PREVIEW_GAP = (30, 34, 42)        # 螢幕之間的空隙
PREVIEW_SKIPPED = (62, 68, 80)    # 「不更新」的螢幕


def _badge_font(size: int):
    for name in ("segoeuib.ttf", "arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:   # Pillow 10.1 以前
        return ImageFont.load_default()


def fit_width(layout: DesktopLayout, box_width: int, box_height: int) -> int:
    """預覽要放進 box_width × box_height 的框裡,寬度最多可以是多少(保持長寬比)。"""
    return max(16, min(box_width, int(box_height * layout.width / max(1, layout.height))))


def render_preview_image(layout: DesktopLayout, config: Config, width: int, debug: bool = False) -> Image.Image:
    """把一個排列畫成寬 width 的縮小版。"""
    ratio = width / layout.width
    height = max(1, int(round(layout.height * ratio)))
    screens = layout.screen_list()
    if len(screens) == 1:
        return render_screen(layout, config, 0, ratio, debug)
    chosen = set(layout.selected_screens(config.screens))
    image = Image.new("RGB", (width, height), PREVIEW_GAP)
    draw = ImageDraw.Draw(image)
    badge = max(14, int(18 * system.ui_scale()))
    font = _badge_font(int(badge * 0.62))
    for number, screen in enumerate(screens, 1):
        box = (int(round(screen.left * ratio)), int(round(screen.top * ratio)),
               int(round(screen.right * ratio)) - 1, int(round(screen.bottom * ratio)) - 1)
        if screen in chosen:
            image.paste(render_screen(layout, config, number - 1, ratio, debug), box[:2])
        else:
            w, h = box[2] - box[0] + 1, box[3] - box[1] + 1
            tile = Image.new("RGB", (w, h), PREVIEW_SKIPPED)
            hatch = ImageDraw.Draw(tile)
            for x in range(-h, w, 10):          # 斜線(超出範圍的部分會自動裁掉)
                hatch.line((x, h, x + h, 0), fill=PREVIEW_GAP, width=2)
            image.paste(tile, box[:2])
        draw.rectangle(box, outline=PREVIEW_GAP)
        x, y = box[0] + 6, box[1] + 6
        draw.ellipse((x, y, x + badge, y + badge), fill=(255, 255, 255), outline=PREVIEW_GAP)
        draw.text((x + badge / 2, y + badge / 2), str(number), fill=(30, 34, 42), font=font, anchor="mm")
    return image


def render_preview(layout: DesktopLayout, config: Config, width: int, debug: bool = False) -> bytes:
    """同 render_preview_image,但回傳 PNG 位元組(自我檢查與測試用)。"""
    buffer = io.BytesIO()
    render_preview_image(layout, config, width, debug).save(buffer, "PNG", compress_level=1)
    return buffer.getvalue()
