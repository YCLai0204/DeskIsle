"""設定:預設值、設定檔、命令列覆寫。"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import List, Tuple

from . import APP_NAME
from .engine.photo import MODES as IMAGE_MODES
from .engine.photo import OBJECT_SHAPES, OBJECT_ZONES
from .engine.themes import DEFAULT_THEME, get_theme


APPEARANCES = ("system", "light", "dark")


@dataclass(frozen=True)
class Config:
    theme: str = DEFAULT_THEME
    seed: int = 7              # 雜訊種子,決定海岸線形狀
    margin: float = 46.0       # 圖示外圍保留多少像素的陸地
    blend: float = 26.0        # 融合半徑,越大越容易連成一片
    roughness: float = 22.0    # 海岸線起伏幅度
    decorations: float = 1.0   # 裝飾物數量(0 = 不畫,1 = 標準,2 = 兩倍)
    follow: bool = False       # 設定介面啟動時是否自動跟隨桌面圖示
    poll_interval: float = 1.0  # 使用者正對著桌面時,每幾秒檢查一次
    idle_interval: float = 3.0  # 其他時候每幾秒檢查一次
    debounce: float = 0.5      # 排列穩定多久後才重畫(秒)
    pause_when_busy: bool = True  # 全螢幕程式執行或螢幕鎖定時暫停
    reseed_on_move: bool = True   # 跟隨時,圖示排列一改變就換一個種子(每次的海岸線都不同)
    screens: Tuple[str, ...] = ()  # 要更新桌布的螢幕代碼;空 = 全部螢幕
    appearance: str = "system"     # 介面配色:system(跟隨系統)/ light / dark
    water_image: str = ""          # 海洋用的圖片(匯入到 app_dir()/images 的那一份)
    water_mode: str = "off"        # 海洋的用法:off / photo(照片)/ colors(取色)
    land_image: str = ""           # 陸地用的圖片
    land_mode: str = "off"         # 陸地的用法:off / photo / colors
    objects: Tuple[str, ...] = ()  # 小物件(匯入到 app_dir()/objects 的圖片)
    objects_zone: str = "water"    # 小物件放哪裡:water(海上)/ land(陸地)/ both
    objects_amount: float = 1.0    # 小物件數量倍率(0 = 不放)
    objects_size: float = 64.0     # 小物件大小(100% 縮放下的像素)
    objects_shape: str = "original"  # original(原樣)/ circle(裁成圓形)
    file_decor: bool = True        # 依檔案類型在圖示旁邊放裝飾物(資料夾 → 椰子樹……)
    night_mode: bool = False       # 晚上自動換成另一個主題
    night_theme: str = "night"     # 晚上用的主題
    night_start: int = 19          # 幾點開始算晚上(0~23)
    day_start: int = 7             # 幾點開始算白天(0~23);跟 night_start 一樣 = 永遠是白天

    def validate(self) -> "Config":
        get_theme(self.theme)
        if self.margin <= 0 or self.blend <= 0:
            raise ValueError("margin 與 blend 必須大於 0")
        if self.roughness < 0 or self.debounce < 0 or self.decorations < 0:
            raise ValueError("roughness、debounce、decorations 不可為負")
        if self.poll_interval < 0.1 or self.idle_interval < 0.1:
            raise ValueError("poll_interval 與 idle_interval 不可小於 0.1 秒")
        if not isinstance(self.screens, tuple) or not all(isinstance(i, str) for i in self.screens):
            raise ValueError("screens 必須是螢幕代碼(文字)的清單")
        get_theme(self.night_theme)
        if not (0 <= self.night_start <= 23 and 0 <= self.day_start <= 23):
            raise ValueError("night_start 與 day_start 必須是 0~23 點")
        for name in ("water_mode", "land_mode"):
            if getattr(self, name) not in IMAGE_MODES:
                raise ValueError(f"{name} 必須是 {'、'.join(IMAGE_MODES)} 其中之一")
        if self.objects_zone not in OBJECT_ZONES or self.objects_shape not in OBJECT_SHAPES:
            raise ValueError("objects_zone 或 objects_shape 的值不對")
        if not isinstance(self.objects, tuple) or not all(isinstance(i, str) for i in self.objects):
            raise ValueError("objects 必須是圖片路徑(文字)的清單")
        if self.objects_amount < 0 or self.objects_size <= 0:
            raise ValueError("objects_amount 不可為負,objects_size 必須大於 0")
        if self.appearance not in APPEARANCES:
            raise ValueError(f"appearance 必須是 {'、'.join(APPEARANCES)} 其中之一")
        return self


def app_dir() -> Path:
    """存放設定、狀態與產生的桌布的資料夾。

    Windows:%LOCALAPPDATA%\\DeskIsle;macOS:~/Library/Application Support/DeskIsle
    """
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_NAME


def config_path() -> Path:
    return app_dir() / "config.json"


def load_config(path: Path = None) -> Tuple[Config, List[str]]:
    """讀取設定檔;回傳 (設定, 警告訊息)。檔案不存在時回傳預設值。"""
    path = path or config_path()
    warnings: List[str] = []
    if not path.exists():
        return Config(), warnings
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("最外層必須是物件")
    except (OSError, ValueError) as exc:
        raise ValueError(f"設定檔 {path} 讀取失敗:{exc}") from exc

    _migrate(data)
    defaults = Config()
    known = {f.name: type(getattr(defaults, f.name)) for f in fields(Config)}
    values = {}
    for key, value in data.items():
        if key not in known:
            warnings.append(f"設定檔中有不認識的項目 '{key}',已忽略")
            continue
        try:
            if known[key] is tuple:
                if not isinstance(value, list):
                    raise TypeError
                values[key] = tuple(value)
            elif known[key] is bool or isinstance(value, bool):
                # 是/否 的項目只接受 true/false,其他項目不接受 true/false
                if known[key] is not bool or not isinstance(value, bool):
                    raise TypeError
                values[key] = value
            else:
                values[key] = known[key](value)
        except (TypeError, ValueError):
            raise ValueError(f"設定檔項目 '{key}' 的值 {value!r} 格式不對") from None
    return replace(defaults, **values).validate(), warnings


def _migrate(data: dict) -> None:
    """舊版設定檔換成新的項目名稱(直接修改 data)。

    0.0.11 只有一張圖片:image + image_mode(land / water / colors)。
    0.0.16 起海洋、陸地各自一張:land → 陸地照片、water → 海洋照片、colors → 海洋與陸地都取色。
    """
    if "image" not in data and "image_mode" not in data:
        return
    image, mode = data.pop("image", ""), data.pop("image_mode", "off")
    if not isinstance(image, str) or not image or mode not in ("land", "water", "colors"):
        return
    if mode in ("water", "colors"):
        data.setdefault("water_image", image)
        data.setdefault("water_mode", "photo" if mode == "water" else "colors")
    if mode in ("land", "colors"):
        data.setdefault("land_image", image)
        data.setdefault("land_mode", "photo" if mode == "land" else "colors")


def save_config(config: Config, path: Path = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
