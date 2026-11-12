"""系統匣圖示與程式圖示。

系統匣用 pystray;沒有安裝時 available() 回傳 False,介面會改成「縮到工作列」。
macOS 上 pystray 必須佔用主執行緒,會跟 tkinter 衝突,所以不使用(關閉視窗時縮到 Dock)。
系統匣的訊息迴圈在自己的執行緒裡等待,沒有事件時不耗 CPU。
"""
from __future__ import annotations

import sys
from typing import Callable

from PIL import Image, ImageDraw

from .. import APP_NAME
from ..engine import decor

_RES = getattr(Image, "Resampling", Image)


def make_icon(size: int = 64) -> Image.Image:
    """程式圖示:海上的一座小島。"""
    big = size * 4
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, big - 1, big - 1), radius=int(big * 0.22), fill=(20, 116, 176, 255))
    cx, cy = big * 0.5, big * 0.56
    for radius, color in ((0.40, (60, 176, 200)), (0.33, (150, 222, 210)), (0.27, (232, 206, 150))):
        draw.ellipse((cx - big * radius, cy - big * radius * 0.82, cx + big * radius, cy + big * radius * 0.82),
                     fill=color + (255,))
    palm = decor.sprite("palm", int(big * 0.56), 1)
    image.alpha_composite(palm, (int(cx - palm.width / 2), int(cy - palm.height / 2 - big * 0.04)))
    return image.resize((size, size), _RES.LANCZOS)


def available() -> bool:
    if sys.platform == "darwin":
        return False
    try:
        import pystray  # noqa: F401
        return True
    except Exception:
        return False


class Tray:
    def __init__(self, on_show: Callable[[], None], on_toggle_follow: Callable[[], None],
                 is_following: Callable[[], bool], on_quit: Callable[[], None]):
        import pystray
        menu = pystray.Menu(
            pystray.MenuItem("開啟設定", lambda icon, item: on_show(), default=True),
            pystray.MenuItem("自動跟隨桌面圖示", lambda icon, item: on_toggle_follow(),
                             checked=lambda item: is_following()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f"結束 {APP_NAME}", lambda icon, item: on_quit()),
        )
        self._icon = pystray.Icon(APP_NAME, make_icon(64), f"{APP_NAME} 桌島", menu)

    def start(self) -> None:
        self._icon.run_detached()

    def refresh(self) -> None:
        """選單的勾選狀態變了。"""
        try:
            self._icon.update_menu()
        except Exception:
            pass

    def notify(self, message: str) -> None:
        try:
            self._icon.notify(message, APP_NAME)
        except Exception:
            pass

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:
            pass
