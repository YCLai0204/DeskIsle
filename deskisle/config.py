"""設定:預設值、設定檔、命令列覆寫。"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import List, Tuple

from . import APP_NAME
from .themes import DEFAULT_THEME, get_theme


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

    def validate(self) -> "Config":
        get_theme(self.theme)
        if self.margin <= 0 or self.blend <= 0:
            raise ValueError("margin 與 blend 必須大於 0")
        if self.roughness < 0 or self.debounce < 0 or self.decorations < 0:
            raise ValueError("roughness、debounce、decorations 不可為負")
        if self.poll_interval < 0.1 or self.idle_interval < 0.1:
            raise ValueError("poll_interval 與 idle_interval 不可小於 0.1 秒")
        return self


def app_dir() -> Path:
    """存放設定、狀態與產生的桌布的資料夾。"""
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

    defaults = Config()
    known = {f.name: type(getattr(defaults, f.name)) for f in fields(Config)}
    values = {}
    for key, value in data.items():
        if key not in known:
            warnings.append(f"設定檔中有不認識的項目 '{key}',已忽略")
            continue
        try:
            if known[key] is bool or isinstance(value, bool):
                # 是/否 的項目只接受 true/false,其他項目不接受 true/false
                if known[key] is not bool or not isinstance(value, bool):
                    raise TypeError
                values[key] = value
            else:
                values[key] = known[key](value)
        except (TypeError, ValueError):
            raise ValueError(f"設定檔項目 '{key}' 的值 {value!r} 格式不對") from None
    return replace(defaults, **values).validate(), warnings


def save_config(config: Config, path: Path = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
