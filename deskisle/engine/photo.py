"""使用者自己的圖片。三種用法:

- land:  圖示周圍的島嶼鋪上這張圖,島外是主題的海(海岸留一圈主題的沙灘與浪花)
- water: 這張圖鋪滿背景當成海,圖示底下長出主題的小島(海岸邊留一圈主題的淺灘)
- colors:從圖片取出主要顏色,重新上色目前的主題;質感、浪花、裝飾物照舊

這裡只處理圖片本身(匯入、讀取、裁切、取色),合成在 render.py。不碰任何作業系統 API。
"""
from __future__ import annotations

import hashlib
import io
import os
import threading
from dataclasses import replace
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image, ImageOps

from .themes import Theme

MODES = ("off", "land", "water", "colors")
MAX_SIDE = 3840        # 匯入時超過這個大小就縮小(4K 螢幕也夠用)
KEEP_IMAGES = 5        # 圖片資料夾最多留幾張(較舊的刪掉)
IMAGE_TYPES = ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.gif", "*.webp", "*.tif", "*.tiff")

Color = Tuple[int, int, int]
_RES = getattr(Image, "Resampling", Image)
_lock = threading.Lock()
_cache = {"key": None, "image": None, "recolor": {}}


# ---------------------------------------------------------------------------
# 匯入與讀取
# ---------------------------------------------------------------------------
def import_image(source, folder: Path) -> Path:
    """把使用者選的圖片整理後存一份到 folder,回傳新檔案的路徑。

    依照相機的方向資訊轉正、透明的地方墊白色、轉成 RGB、太大就縮小,存成 JPEG。
    檔名是內容的雜湊:同一張圖重複匯入只會有一份。原始檔案之後被刪掉或移走也不影響。
    讀不了的檔案會丟出 ValueError。
    """
    try:
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened)
            if image.mode in ("RGBA", "LA", "P"):
                image = image.convert("RGBA")
                background = Image.new("RGBA", image.size, (255, 255, 255, 255))
                image = Image.alpha_composite(background, image)
            image = image.convert("RGB")
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValueError(f"無法讀取這張圖片:{exc}") from exc
    image.thumbnail((MAX_SIDE, MAX_SIDE), _RES.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=92)
    data = buffer.getvalue()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"custom_{hashlib.sha1(data).hexdigest()[:12]}.jpg"
    if not target.exists():
        target.write_bytes(data)
    os.utime(target)          # 當成最新的一張,清理時才不會被刪掉
    _prune(folder)
    return target


def _prune(folder: Path) -> None:
    """只留最近用過的幾張(已套用的與正在預覽的可能是不同張,所以不只留一張)。"""
    images = sorted(folder.glob("custom_*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in images[KEEP_IMAGES:]:
        try:
            old.unlink()
        except OSError:
            pass


def load(path: str) -> Optional[Image.Image]:
    """讀取圖片(RGB);檔案不存在或壞掉時回傳 None。最近一張會留在記憶體裡。"""
    if not path:
        return None
    try:
        stat = os.stat(path)
    except OSError:
        return None
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    with _lock:
        if _cache["key"] == key:
            return _cache["image"]
    try:
        with Image.open(path) as opened:
            image = opened.convert("RGB")
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
    with _lock:
        _cache.update(key=key, image=image, recolor={})
    return image


def clear_cache() -> None:
    """常駐時畫完桌布就把圖片從記憶體放掉(下次要用再讀,約幾十毫秒)。"""
    with _lock:
        _cache.update(key=None, image=None, recolor={})


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
    small = image.copy()
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


def recolor(theme: Theme, image: Image.Image) -> Theme:
    """用圖片的顏色重新上色主題:色帶上原本越亮的位置,就用圖片裡越亮的顏色。

    保留主題的明暗結構(例如沙灘亮、深海暗),質感、浪花、裝飾物都不變。
    """
    colors = palette(image)
    lums = [_luminance(c) for _d, c in theme.stops]
    low, high = min(lums), max(lums)
    stops = tuple((d, _sample(colors, (lum - low) / max(1e-6, high - low)))
                  for (d, _c), lum in zip(theme.stops, lums))
    lightest = colors[-1]
    vivid = sorted(colors, key=_saturation, reverse=True)
    tint = tuple(
        tuple(int(v * max(original) / max(1, max(vivid[i % len(vivid)]))) for v in vivid[i % len(vivid)])
        for i, original in enumerate(theme.tint)
    )
    sparkles = tuple(_mix(c, (255, 255, 255), 0.6) for c in colors[-3:])
    return replace(theme, stops=stops, foam=_mix(lightest, (255, 255, 255), 0.55), tint=tint,
                   sparkle_colors=sparkles or theme.sparkle_colors)


def recolored(theme: Theme, path: str) -> Theme:
    """recolor 的快取版本;圖片讀不到時回傳原本的主題。"""
    image = load(path)
    if image is None:
        return theme
    with _lock:
        cached = _cache["recolor"].get(theme.key)
    if cached is None:
        cached = recolor(theme, image)
        with _lock:
            _cache["recolor"][theme.key] = cached
    return cached
