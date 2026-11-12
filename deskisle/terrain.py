"""地形:把圖示矩形變成「離海岸線多遠」的距離場。

這個模組只用 numpy 與 Pillow,不碰任何 Windows API。
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence, Tuple

import numpy as np
from PIL import Image

Rect = Tuple[int, int, int, int]  # (left, top, right, bottom),圖片座標

FIELD_SCALE = 4          # 距離場以 1/4 解析度計算,再放大
FAR = 2000.0             # 沒有任何圖示時的距離(= 深海)
SHORE_NOISE_CELL = 150   # 海岸線起伏的最大特徵尺寸(像素)
MAX_ROUGHNESS_RATIO = 0.8  # 起伏幅度最多佔邊界留白的比例 → 保證圖示在陸地上

_BICUBIC = getattr(Image, "Resampling", Image).BICUBIC


def _resize(arr: np.ndarray, width: int, height: int) -> np.ndarray:
    img = Image.fromarray(np.ascontiguousarray(arr, dtype=np.float32))
    return np.asarray(img.resize((width, height), _BICUBIC), dtype=np.float32)


def fbm(width: int, height: int, seed: int, cell: float, octaves: int = 4, gain: float = 0.5,
        coarse: int = 1) -> np.ndarray:
    """分形雜訊:多層不同尺度的平滑亂數相加,回傳 (height, width) float32,範圍 [-1, 1]。

    cell 是最粗那一層的格子大小(像素)。相同參數一定得到相同結果。
    coarse > 1 時先以 1/coarse 的解析度計算再放大:平滑的紋理看不出差別,
    但運算量少很多。
    """
    if coarse > 1:
        w = int(math.ceil(width / coarse))
        h = int(math.ceil(height / coarse))
        small = fbm(w, h, seed, cell / coarse, octaves, gain)
        return _resize(small, w * coarse, h * coarse)[:height, :width]
    rng = np.random.default_rng(seed)
    total = np.zeros((height, width), dtype=np.float32)
    amplitude, amplitude_sum = 1.0, 0.0
    size = float(cell)
    for _ in range(octaves):
        size = max(size, 2.0)
        gw = int(math.ceil(width / size)) + 3
        gh = int(math.ceil(height / size)) + 3
        grid = rng.uniform(-1.0, 1.0, (gh, gw)).astype(np.float32)
        layer = _resize(grid, int(round(gw * size)), int(round(gh * size)))
        # 跳過最外圈:插值在邊界會貼著邊緣值,看起來較平
        oy, ox = int(size), int(size)
        total += amplitude * layer[oy:oy + height, ox:ox + width]
        amplitude_sum += amplitude
        amplitude *= gain
        size /= 2.0
    # 多層平均後數值集中在中間,拉開一點再限制範圍
    return np.clip(total / amplitude_sum * 1.7, -1.0, 1.0)


def smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    """edge0 → 0、edge1 → 1 的平滑過渡;edge0 > edge1 時方向相反。"""
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def blended_distance(width: int, height: int, rects: Iterable[Rect], blend: float,
                     scale: int = FIELD_SCALE) -> np.ndarray:
    """低解析度的「到最近圖示的平滑距離」,單位是全解析度像素。

    d = -k·ln(Σ exp(-d_i/k)):單一圖示時等於一般距離;
    圖示靠近時彼此拉近(陸地融合);越密集的地方數值越負(越內陸)。
    """
    w = int(math.ceil(width / scale))
    h = int(math.ceil(height / scale))
    xs = (np.arange(w, dtype=np.float32) + 0.5) * scale
    ys = (np.arange(h, dtype=np.float32) + 0.5) * scale

    acc = np.zeros((h, w), dtype=np.float32)
    inv_k = np.float32(1.0 / blend)
    any_rect = False
    for left, top, right, bottom in rects:
        any_rect = True
        dx = np.maximum(np.maximum(left - xs, xs - right), 0.0)
        dy = np.maximum(np.maximum(top - ys, ys - bottom), 0.0)
        d = np.sqrt(dx[None, :] ** 2 + dy[:, None] ** 2)
        acc += np.exp(-d * inv_k)
    if not any_rect:
        return np.full((h, w), FAR, dtype=np.float32)
    return np.minimum(-blend * np.log(acc + np.float32(1e-30)), FAR).astype(np.float32)


def shore_field(width: int, height: int, rects: Sequence[Rect], *, margin: float, blend: float,
                roughness: float, seed: int, noise_cell: float = SHORE_NOISE_CELL,
                scale: int = FIELD_SCALE) -> np.ndarray:
    """帶正負號的海岸距離場,(height, width) float32。

    負值 = 陸地,正值 = 水域,絕對值約等於離海岸線的像素數。
    """
    dist = blended_distance(width, height, rects, blend, scale)
    h, w = dist.shape
    roughness = min(roughness, MAX_ROUGHNESS_RATIO * margin)
    noise = fbm(w, h, seed, cell=noise_cell / scale, octaves=4)
    low = dist - margin + roughness * noise
    full = _resize(low, w * scale, h * scale)
    return full[:height, :width]
