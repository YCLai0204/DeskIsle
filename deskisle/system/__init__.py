"""依作業系統選擇實作:其他模組只透過這裡呼叫系統功能。

    Windows → windows/(winapi、icons、screens、wallpaper、autostart)
    macOS   → macos/(desktop、wallpaper、autostart)

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
    prefers_dark()                系統是不是深色模式(介面配色跟著它)
    desktop_folders()             桌面圖示來自哪些資料夾(判斷檔案類型用)
    style_title_bar(id, dark, …)  讓視窗標題列配合介面配色(只有 Windows 需要)
    round_window_corners(id)      沒有標題列的小視窗也有圓角(Windows 11)
    acquire_single_instance / create_signal / wait_signal / send_signal   只允許一個執行個體
"""
from __future__ import annotations

import sys

from ..engine.layout import IconDetectionError, Screen  # noqa: F401

SUPPORTED = sys.platform in ("win32", "darwin")

if sys.platform == "win32":
    from .windows import autostart, wallpaper  # noqa: F401
    from .windows import screens as _screens
    from .windows.icons import read_layout  # noqa: F401
    from .windows.winapi import (  # noqa: F401
        acquire_single_instance, create_signal, desktop_folders, desktop_is_foreground, enable_dpi_awareness,
        lower_thread_priority, monitor_count, prefers_dark, round_window_corners, send_signal, style_title_bar,
        trim_memory,
        ui_scale, user_is_busy, virtual_screen, wait_signal,
    )

    def list_screens():
        vx, vy, _width, _height = virtual_screen()
        return _screens.list_screens(vx, vy)

elif sys.platform == "darwin":
    from .macos import autostart, wallpaper  # noqa: F401
    from .macos.desktop import (  # noqa: F401
        acquire_single_instance, create_signal, desktop_folders, desktop_is_foreground, enable_dpi_awareness,
        list_screens, lower_thread_priority, monitor_count, prefers_dark, read_layout, round_window_corners,
        send_signal,
        style_title_bar, trim_memory, ui_scale, user_is_busy, virtual_screen, wait_signal,
    )

else:  # pragma: no cover
    raise ImportError("DeskIsle 只支援 Windows 與 macOS")
