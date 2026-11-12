"""依作業系統選擇實作:其他模組只透過這裡呼叫系統功能。

    Windows → winapi.py、icons.py、screens.py、wallpaper.py、autostart.py
    macOS   → macos.py、wallpaper_mac.py、autostart_mac.py

對外提供的東西兩邊都一樣:

    read_layout(names)            讀取桌面圖示排列 → DesktopLayout
    list_screens()                目前的螢幕清單
    wallpaper                     apply_image / apply_per_screen / restore / load_backup / BACKGROUND_KINDS
    autostart                     is_enabled / enable / disable
    ui_scale()                    系統縮放比例(畫圖時像素類參數要乘上它)
    desktop_is_foreground()       使用者是不是正對著桌面
    user_is_busy()                全螢幕程式執行中或螢幕已鎖定
    lower_thread_priority()       目前執行緒降為背景優先權
    trim_memory()                 把用不到的記憶體還給系統
    enable_dpi_awareness()        取得實體像素座標(只有 Windows 需要)
    acquire_single_instance / create_signal / wait_signal / send_signal   只允許一個執行個體
"""
from __future__ import annotations

import sys

from .layout import IconDetectionError, Screen  # noqa: F401

SUPPORTED = sys.platform in ("win32", "darwin")

if sys.platform == "win32":
    from . import autostart, wallpaper  # noqa: F401
    from . import screens as _screens
    from .icons import read_layout  # noqa: F401
    from .winapi import (  # noqa: F401
        acquire_single_instance, create_signal, desktop_is_foreground, enable_dpi_awareness,
        lower_thread_priority, monitor_count, send_signal, trim_memory, ui_scale, user_is_busy,
        virtual_screen, wait_signal,
    )

    def list_screens():
        vx, vy, _width, _height = virtual_screen()
        return _screens.list_screens(vx, vy)

elif sys.platform == "darwin":
    from . import autostart_mac as autostart  # noqa: F401
    from . import wallpaper_mac as wallpaper  # noqa: F401
    from .macos import (  # noqa: F401
        acquire_single_instance, create_signal, desktop_is_foreground, enable_dpi_awareness,
        list_screens, lower_thread_priority, monitor_count, read_layout, send_signal, trim_memory,
        ui_scale, user_is_busy, virtual_screen, wait_signal,
    )

else:  # pragma: no cover
    raise ImportError("DeskIsle 只支援 Windows 與 macOS")
