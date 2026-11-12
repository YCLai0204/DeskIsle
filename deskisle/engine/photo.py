"""使用者自己的圖片(「圖片」頁)。

- 海洋、陸地各自可以選一張圖片,用法二選一:
  - photo:  直接把圖片鋪上去(海岸邊留一圈主題的淺灘/沙灘與浪花,島的輪廓才清楚)
  - colors: 從圖片取出主要顏色,重新上色主題的海或陸地;質感、浪花、裝飾物照舊
  海洋與陸地可以同時使用,也可以一個用照片、一個取色。
- 小物件:使用者上傳的小圖(最好是去背的 PNG),像星球、小船一樣散落在桌布上。只能用照片。

這裡只處理圖片本身(匯入、讀取、裁切、取色、小物件的形狀),合成在 render.py。不碰任何作業系統 API。
"""
from __future__ import annotations

import hashlib
import io
import os
import threading
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from .themes import Theme

MODES = ("off", "photo", "colors")                # 海洋、陸地的用法
OBJECT_ZONES = ("water", "land", "both")          # 小物件放在哪裡
OBJECT_SHAPES = ("original", "circle")            # 小物件的形狀:原樣 / 裁成圓形
MAX_SIDE = 3840        # 背景圖片匯入時超過這個大小就縮小(4K 螢幕也夠用)
OBJECT_SIDE = 512      # 小物件匯入時的最大邊長
KEEP_IMAGES = 8        # 背景圖片最多留幾張(海洋、陸地,加上還沒套用的)
KEEP_OBJECTS = 40      # 小物件最多留幾張
IMAGE_TYPES = ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.gif", "*.webp", "*.tif", "*.tiff")

Color = Tuple[int, int, int]
_RES = getattr(Image, "Resampling", Image)
_lock = threading.Lock()
_images: "OrderedDict[tuple, Image.Image]" = OrderedDict()   # 最近讀過的圖片(海洋、陸地、小物件)
_recolor_cache: dict = {}
_CACHE_SIZE = 24


# ---------------------------------------------------------------------------
# 匯入
# ---------------------------------------------------------------------------
def _open(source) -> Image.Image:
    try:
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened)
            image.load()
            return image
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValueError(f"無法讀取這張圖片:{exc}") from exc


def _save(data: bytes, folder: Path, prefix: str, suffix: str, keep: int) -> Path:
    """以內容雜湊命名存檔(同一張圖只存一份),並只留最近用過的 keep 張。"""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{prefix}_{hashlib.sha1(data).hexdigest()[:12]}{suffix}"
    if not target.exists():
        target.write_bytes(data)
    os.utime(target)          # 當成最新的一張,清理時才不會被刪掉
    files = sorted(folder.glob(f"{prefix}_*{suffix}"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        try:
            old.unlink()
        except OSError:
            pass
    return target


def import_image(source, folder: Path) -> Path:
    """匯入海洋或陸地用的圖片:轉正、透明處墊白、轉 RGB、太大就縮小,存成 JPEG。

    原始檔案之後被刪掉或移走也不影響。讀不了的檔案會丟出 ValueError。
    """
    image = _open(source)
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        image = Image.alpha_composite(Image.new("RGBA", image.size, (255, 255, 255, 255)), image)
    image = image.convert("RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE), _RES.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=92)
    return _save(buffer.getvalue(), folder, "custom", ".jpg", KEEP_IMAGES)


def import_object(source, folder: Path) -> Path:
    """匯入小物件:保留透明背景(存成 PNG),太大就縮小,四周多餘的透明邊裁掉。"""
    image = _open(source).convert("RGBA")
    box = image.getchannel("A").getbbox()
    if box is None:
        raise ValueError("這張圖片整張都是透明的")
    image = image.crop(box)
    image.thumbnail((OBJECT_SIDE, OBJECT_SIDE), _RES.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "PNG", optimize=True)
    return _save(buffer.getvalue(), folder, "object", ".png", KEEP_OBJECTS)


# ---------------------------------------------------------------------------
# 讀取(有快取)
# ---------------------------------------------------------------------------
def _cached(path: str, mode: str) -> Optional[Image.Image]:
    if not path:
        return None
    try:
        stat = os.stat(path)
    except OSError:
        return None
    key = (str(path), stat.st_mtime_ns, stat.st_size, mode)
    with _lock:
        image = _images.get(key)
        if image is not None:
            _images.move_to_end(key)
            return image
    try:
        with Image.open(path) as opened:
            image = opened.convert(mode)
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
    with _lock:
        _images[key] = image
        while len(_images) > _CACHE_SIZE:
            _images.popitem(last=False)
    return image


def load(path: str) -> Optional[Image.Image]:
    """讀取海洋或陸地的圖片(RGB);檔案不存在或壞掉時回傳 None。"""
    return _cached(path, "RGB")


def load_object(path: str) -> Optional[Image.Image]:
    """讀取小物件(RGBA);檔案不存在或壞掉時回傳 None。"""
    return _cached(path, "RGBA")


def clear_cache() -> None:
    """常駐時畫完桌布就把圖片從記憶體放掉(下次要用再讀,約幾十毫秒)。"""
    with _lock:
        _images.clear()
        _recolor_cache.clear()


# ---------------------------------------------------------------------------
# 裁切與形狀
# ---------------------------------------------------------------------------
def cover(image: Image.Image, width: int, height: int) -> np.ndarray:
    """把圖片等比例縮放到剛好蓋滿 width×height,超出的部分從中間裁掉。回傳 float32 陣列。"""
    source_w, source_h = image.size
    scale = max(width / source_w, height / source_h)
    crop_w, crop_h = min(source_w, width / scale), min(source_h, height / scale)
    # 浮點誤差可能讓邊界變成 -0.0000001 之類,Pillow 不接受,所以夾在圖片範圍內
    left, top = max(0.0, (source_w - crop_w) / 2), max(0.0, (source_h - crop_h) / 2)
    box = (left, top, min(float(source_w), left + crop_w), min(float(source_h), top + crop_h))
    fitted = image.resize((width, height), _RES.BICUBIC, box=box, reducing_gap=2.0)
    return np.asarray(fitted, dtype=np.float32)


def thumbnail(image: Image.Image, width: int, height: int) -> Image.Image:
    """介面用的小縮圖(蓋滿、從中間裁切)。"""
    return ImageOps.fit(image, (width, height), _RES.LANCZOS)


def contain(image: Image.Image, width: int, height: int) -> Image.Image:
    """等比例縮小到放得進 width×height(不裁切)。"""
    copy = image.copy()
    copy.thumbnail((max(1, width), max(1, height)), _RES.LANCZOS)
    return copy


def shape_object(image: Image.Image, shape: str) -> Image.Image:
    """小物件的形狀:original 原樣;circle 從中間裁成正方形再切成圓形(照片當星球用)。"""
    if shape != "circle":
        return image
    side = min(image.size)
    square = ImageOps.fit(image, (side, side), _RES.LANCZOS)
    big = side * 4
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, big - 1, big - 1), fill=255)
    mask = mask.resize((side, side), _RES.LANCZOS)
    alpha = Image.composite(square.getchannel("A"), Image.new("L", (side, side), 0), mask)
    square.putalpha(alpha)
    return square


# ---------------------------------------------------------------------------
# 取色
# ---------------------------------------------------------------------------
def _luminance(color) -> float:
    r, g, b = color[:3]
    return 0.299 * r + 0.587 * g + 0.114 * b


def _mix(a, b, t: float) -> Color:
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def palette(image: Image.Image, count: int = 8) -> List[Color]:
    """圖片的主要顏色,由暗到亮排列。顏色太接近時補上更暗與更亮的版本,色帶才有層次。"""
    small = image.convert("RGB")
    small.thumbnail((128, 128), _RES.BILINEAR)
    method = getattr(getattr(Image, "Quantize", Image), "MEDIANCUT", 0)
    quantized = small.quantize(colors=count, method=method)
    raw = quantized.getpalette()[:count * 3]
    total = small.width * small.height
    colors = []
    for amount, index in quantized.getcolors() or []:
        if amount / total >= 0.02 and index * 3 + 2 < len(raw):
            colors.append(tuple(raw[index * 3:index * 3 + 3]))
    if not colors:
        colors = [tuple(int(v) for v in np.asarray(small).reshape(-1, 3).mean(axis=0))]
    colors = sorted(set(colors), key=_luminance)
    if _luminance(colors[-1]) - _luminance(colors[0]) < 90:
        colors = [_mix(colors[0], (0, 0, 0), 0.45)] + colors + [_mix(colors[-1], (255, 255, 255), 0.5)]
    return colors


def _sample(colors: List[Color], t: float) -> Color:
    """沿著由暗到亮的調色盤,取位置 t(0~1)的顏色(以亮度為座標內插)。"""
    lums = [_luminance(c) for c in colors]
    low, high = lums[0], lums[-1]
    target = low + (high - low) * max(0.0, min(1.0, t))
    for i in range(len(colors) - 1):
        if lums[i] <= target <= lums[i + 1]:
            span = lums[i + 1] - lums[i]
            return _mix(colors[i], colors[i + 1], 0.0 if span <= 0 else (target - lums[i]) / span)
    return colors[-1]


def _saturation(color) -> float:
    return max(color) - min(color)


def recolor(theme: Theme, land: Optional[Image.Image] = None, water: Optional[Image.Image] = None) -> Theme:
    """用圖片的顏色重新上色主題的陸地(色帶上距離 ≤ 0 的部分)和/或海(> 0 的部分)。

    色帶上每個位置依它在整條色帶裡的相對亮度,到圖片的調色盤上取同樣相對亮度的顏色,
    所以主題的明暗結構不變(例如沙灘亮、深海暗),只換色相。
    換了海的顏色時,浪花、星雲、光點也跟著用海的圖片取色。
    """
    lums = [_luminance(c) for _d, c in theme.stops]
    low, high = min(lums), max(lums)
    land_colors = palette(land) if land is not None else None
    water_colors = palette(water) if water is not None else None
    stops = []
    for (distance, color), lum in zip(theme.stops, lums):
        colors = land_colors if distance <= 0 else water_colors
        if colors is not None:
            color = _sample(colors, (lum - low) / max(1e-6, high - low))
        stops.append((distance, color))
    changes = dict(stops=tuple(stops))
    if water_colors is not None:
        vivid = sorted(water_colors, key=_saturation, reverse=True)
        changes["tint"] = tuple(
            tuple(int(v * max(original) / max(1, max(vivid[i % len(vivid)]))) for v in vivid[i % len(vivid)])
            for i, original in enumerate(theme.tint))
        changes["foam"] = _mix(water_colors[-1], (255, 255, 255), 0.55)
        changes["sparkle_colors"] = tuple(_mix(c, (255, 255, 255), 0.6) for c in water_colors[-3:])
    return replace(theme, **changes)


def recolored(theme: Theme, land_path: str = "", water_path: str = "") -> Theme:
    """recolor 的快取版本;圖片讀不到的那一邊維持主題原本的顏色。"""
    land, water = load(land_path), load(water_path)
    if land is None and water is None:
        return theme
    key = (theme.key, land_path if land is not None else "", water_path if water is not None else "")
    with _lock:
        cached = _recolor_cache.get(key)
    if cached is None:
        cached = recolor(theme, land, water)
        with _lock:
            _recolor_cache[key] = cached
    return cached


def object_sprites(paths: Sequence[str], shape: str) -> List[Image.Image]:
    """讀取小物件並套用形狀;讀不到的略過。"""
    sprites = []
    for path in paths:
        image = load_object(path)
        if image is not None:
            sprites.append(shape_object(image, shape))
    return sprites
