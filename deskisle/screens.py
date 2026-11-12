"""螢幕(顯示器)清單與「每個螢幕各自的桌布」。

- 列出所有螢幕的位置與大小:EnumDisplayMonitors(便宜,每次檢查都可以呼叫)。
- 每個螢幕各自設定桌布:Windows 8 以後的 IDesktopWallpaper COM 介面。
  這裡直接用 ctypes 呼叫它的函式表,不需要 pywin32 / comtypes。

螢幕的「代碼」是 IDesktopWallpaper 給的裝置路徑,拔插螢幕後仍然不變,
所以設定檔記的是代碼而不是第幾個。COM 用不了時代碼是空字串,
此時只能把所有螢幕畫成一張圖、以「跨螢幕」模式套用(舊做法)。
"""
from __future__ import annotations

import ctypes
from contextlib import contextmanager
from ctypes import wintypes
from typing import Dict, Iterator, List, Optional, Tuple

from .layout import Screen
from .winapi import user32


# ---------------------------------------------------------------------------
# EnumDisplayMonitors
# ---------------------------------------------------------------------------
class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


_MONITORINFOF_PRIMARY = 1
_MonitorEnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                      ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), _MonitorEnumProc,
                                       wintypes.LPARAM]
user32.EnumDisplayMonitors.restype = wintypes.BOOL
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
user32.GetMonitorInfoW.restype = wintypes.BOOL


def monitor_rects() -> List[Tuple[Tuple[int, int, int, int], bool]]:
    """所有螢幕的 ((左, 上, 右, 下), 是否為主螢幕),螢幕座標。"""
    found = []

    def callback(hmonitor, _hdc, _rect, _data):
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            r = info.rcMonitor
            found.append(((r.left, r.top, r.right, r.bottom), bool(info.dwFlags & _MONITORINFOF_PRIMARY)))
        return True

    user32.EnumDisplayMonitors(None, None, _MonitorEnumProc(callback), 0)
    return found


# ---------------------------------------------------------------------------
# IDesktopWallpaper(COM)
# ---------------------------------------------------------------------------
class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


_ole32 = ctypes.WinDLL("ole32")
_ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
_ole32.CoInitializeEx.restype = ctypes.c_long
_ole32.CoUninitialize.argtypes = []
_ole32.CoUninitialize.restype = None
_ole32.CoCreateInstance.argtypes = [ctypes.POINTER(_GUID), ctypes.c_void_p, wintypes.DWORD,
                                    ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
_ole32.CoCreateInstance.restype = ctypes.HRESULT
_ole32.CLSIDFromString.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(_GUID)]
_ole32.CLSIDFromString.restype = ctypes.HRESULT
_ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
_ole32.CoTaskMemFree.restype = None


def _guid(text: str) -> _GUID:
    guid = _GUID()
    _ole32.CLSIDFromString(text, ctypes.byref(guid))
    return guid


_CLSID_DESKTOP_WALLPAPER = _guid("{C2CF3110-460E-4FC1-B9D0-8A1C0C9CC4BD}")
_IID_IDESKTOP_WALLPAPER = _guid("{B92B56A9-8B55-4E14-9A89-0199BBB6F93B}")
_CLSCTX_ALL = 0x17
_COINIT_APARTMENTTHREADED = 0x2

# DESKTOP_WALLPAPER_POSITION
DWPOS_CENTER, DWPOS_TILE, DWPOS_STRETCH, DWPOS_FIT, DWPOS_FILL, DWPOS_SPAN = range(6)

# 函式表的順序(前 3 個是 IUnknown):見 ShObjIdl_core.h
_RELEASE = 2
_SET_WALLPAPER = 3
_GET_WALLPAPER = 4
_GET_MONITOR_PATH_AT = 5
_GET_MONITOR_PATH_COUNT = 6
_GET_MONITOR_RECT = 7
_SET_POSITION = 10


class DesktopWallpaper:
    """IDesktopWallpaper 的薄包裝;用 open_desktop_wallpaper() 取得。"""

    def __init__(self, pointer: ctypes.c_void_p):
        self._ptr = pointer
        self._vtable = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]

    def _call(self, index: int, restype, argtypes, *args):
        prototype = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
        return prototype(self._vtable[index])(self._ptr, *args)

    def release(self) -> None:
        self._call(_RELEASE, wintypes.ULONG, [])

    def monitor_ids(self) -> List[str]:
        count = wintypes.UINT(0)
        self._call(_GET_MONITOR_PATH_COUNT, ctypes.HRESULT, [ctypes.POINTER(wintypes.UINT)],
                   ctypes.byref(count))
        ids = []
        for index in range(count.value):
            text = ctypes.c_void_p()
            self._call(_GET_MONITOR_PATH_AT, ctypes.HRESULT,
                       [wintypes.UINT, ctypes.POINTER(ctypes.c_void_p)], index, ctypes.byref(text))
            ids.append(ctypes.wstring_at(text.value) if text.value else "")
            _ole32.CoTaskMemFree(text)
        return ids

    def monitor_rect(self, monitor_id: str) -> Optional[Tuple[int, int, int, int]]:
        """螢幕的範圍(螢幕座標);沒有接上的螢幕回傳 None。"""
        rect = wintypes.RECT()
        try:
            self._call(_GET_MONITOR_RECT, ctypes.HRESULT, [wintypes.LPCWSTR, ctypes.POINTER(wintypes.RECT)],
                       monitor_id, ctypes.byref(rect))
        except OSError:
            return None
        if rect.right <= rect.left or rect.bottom <= rect.top:
            return None
        return (rect.left, rect.top, rect.right, rect.bottom)

    def get_wallpaper(self, monitor_id: str) -> str:
        text = ctypes.c_void_p()
        self._call(_GET_WALLPAPER, ctypes.HRESULT, [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)],
                   monitor_id, ctypes.byref(text))
        value = ctypes.wstring_at(text.value) if text.value else ""
        _ole32.CoTaskMemFree(text)
        return value

    def set_wallpaper(self, monitor_id: str, path: str) -> None:
        self._call(_SET_WALLPAPER, ctypes.HRESULT, [wintypes.LPCWSTR, wintypes.LPCWSTR], monitor_id, path)

    def set_position(self, position: int) -> None:
        self._call(_SET_POSITION, ctypes.HRESULT, [ctypes.c_int], position)


@contextmanager
def open_desktop_wallpaper() -> Iterator[DesktopWallpaper]:
    """在目前的執行緒建立 IDesktopWallpaper;失敗時丟出 OSError。"""
    hr = _ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    initialized = hr in (0, 1)   # S_OK / S_FALSE 才需要對應的 CoUninitialize
    try:
        pointer = ctypes.c_void_p()
        _ole32.CoCreateInstance(ctypes.byref(_CLSID_DESKTOP_WALLPAPER), None, _CLSCTX_ALL,
                                ctypes.byref(_IID_IDESKTOP_WALLPAPER), ctypes.byref(pointer))
        wallpaper = DesktopWallpaper(pointer)
        try:
            yield wallpaper
        finally:
            wallpaper.release()
    finally:
        if initialized:
            _ole32.CoUninitialize()


# ---------------------------------------------------------------------------
# 螢幕清單(有快取:螢幕配置沒變時不必每次都建立 COM 物件)
# ---------------------------------------------------------------------------
_cache: Dict[tuple, Tuple[Screen, ...]] = {}


def list_screens(origin_x: int, origin_y: int) -> Tuple[Screen, ...]:
    """目前所有螢幕,由左到右(同一欄由上到下)排序。

    origin 是虛擬桌面的左上角,用來把螢幕座標換成圖片座標。
    """
    rects = monitor_rects()
    key = (origin_x, origin_y, tuple(sorted(rects)))
    if key in _cache:
        return _cache[key]

    ids: Dict[Tuple[int, int, int, int], str] = {}
    try:
        with open_desktop_wallpaper() as wallpaper:
            for monitor_id in wallpaper.monitor_ids():
                rect = wallpaper.monitor_rect(monitor_id)
                if rect is not None:
                    ids[rect] = monitor_id
    except OSError:
        ids = {}   # 沒有 COM 介面 → 不能各自設定

    screens = tuple(sorted(
        (Screen(ids.get(rect, ""), rect[0] - origin_x, rect[1] - origin_y,
                rect[2] - rect[0], rect[3] - rect[1], primary)
         for rect, primary in rects),
        key=lambda s: (s.left, s.top),
    ))
    _cache.clear()
    _cache[key] = screens
    return screens
