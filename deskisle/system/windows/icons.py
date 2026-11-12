"""偵測桌面圖示的位置。

桌面圖示是檔案總管裡的一個 ListView(SysListView32 "FolderView")。
我們對它送 LVM_* 訊息取得每個項目的外框與名稱。這些訊息的結果要寫進
「檔案總管行程」的記憶體,所以需要在對方行程配置一小塊緩衝區再讀回來。
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import List, Optional

from . import screens as screen_api
from . import winapi
from ...engine.layout import DesktopIcon, DesktopLayout, IconDetectionError, Screen  # noqa: F401
from .winapi import kernel32, user32

LVM_FIRST = 0x1000
LVM_GETITEMCOUNT = LVM_FIRST + 4
LVM_GETITEMRECT = LVM_FIRST + 14
LVM_GETITEMTEXTW = LVM_FIRST + 115
LVIR_BOUNDS = 0

_TEXT_OFFSET = 512      # 遠端緩衝區內,文字區的起始位移
_TEXT_CHARS = 520       # 文字區可容納的字元數
_BUFFER_SIZE = 4096


class _LVITEMW(ctypes.Structure):
    _fields_ = [
        ("mask", wintypes.UINT),
        ("iItem", ctypes.c_int),
        ("iSubItem", ctypes.c_int),
        ("state", wintypes.UINT),
        ("stateMask", wintypes.UINT),
        ("pszText", ctypes.c_void_p),
        ("cchTextMax", ctypes.c_int),
        ("iImage", ctypes.c_int),
        ("lParam", wintypes.LPARAM),
        ("iIndent", ctypes.c_int),
        ("iGroupId", ctypes.c_int),
        ("cColumns", wintypes.UINT),
        ("puColumns", ctypes.c_void_p),
        ("piColFmt", ctypes.c_void_p),
        ("iGroup", ctypes.c_int),
    ]


def find_desktop_listview() -> Optional[int]:
    """回傳桌面 ListView 的視窗代碼;找不到回傳 None。"""
    progman = user32.FindWindowW("Progman", None)
    defview = user32.FindWindowExW(progman, None, "SHELLDLL_DefView", None) if progman else None
    if not defview:
        # 桌布幻燈片等功能啟用後,DefView 會被搬到某個 WorkerW 底下
        worker = None
        while True:
            worker = user32.FindWindowExW(None, worker, "WorkerW", None)
            if not worker:
                break
            defview = user32.FindWindowExW(worker, None, "SHELLDLL_DefView", None)
            if defview:
                break
    if not defview:
        return None
    return user32.FindWindowExW(defview, None, "SysListView32", None) or None


class _RemoteBuffer:
    """在另一個行程裡配置的一塊可讀寫記憶體(不可執行)。"""

    def __init__(self, pid: int, size: int = _BUFFER_SIZE):
        access = (winapi.PROCESS_VM_OPERATION | winapi.PROCESS_VM_READ
                  | winapi.PROCESS_VM_WRITE | winapi.PROCESS_QUERY_LIMITED_INFORMATION)
        self.process = kernel32.OpenProcess(access, False, pid)
        if not self.process:
            raise IconDetectionError(f"無法開啟檔案總管行程(錯誤碼 {ctypes.get_last_error()})")
        self.address = kernel32.VirtualAllocEx(
            self.process, None, size, winapi.MEM_COMMIT | winapi.MEM_RESERVE, winapi.PAGE_READWRITE
        )
        if not self.address:
            code = ctypes.get_last_error()
            kernel32.CloseHandle(self.process)
            raise IconDetectionError(f"無法在檔案總管行程配置記憶體(錯誤碼 {code})")

    def __enter__(self) -> "_RemoteBuffer":
        return self

    def __exit__(self, *exc) -> None:
        kernel32.VirtualFreeEx(self.process, self.address, 0, winapi.MEM_RELEASE)
        kernel32.CloseHandle(self.process)

    def write(self, data, offset: int = 0) -> None:
        size = ctypes.sizeof(data)
        done = winapi.SIZE_T(0)
        ok = kernel32.WriteProcessMemory(
            self.process, self.address + offset, ctypes.byref(data), size, ctypes.byref(done)
        )
        if not ok or done.value != size:
            raise IconDetectionError("寫入檔案總管行程記憶體失敗")

    def read(self, ctype, offset: int = 0):
        out = ctype()
        size = ctypes.sizeof(out)
        done = winapi.SIZE_T(0)
        ok = kernel32.ReadProcessMemory(
            self.process, self.address + offset, ctypes.byref(out), size, ctypes.byref(done)
        )
        if not ok or done.value != size:
            raise IconDetectionError("讀取檔案總管行程記憶體失敗")
        return out


def _clip(rect, width: int, height: int):
    left, top, right, bottom = rect
    left, top = max(left, 0), max(top, 0)
    right, bottom = min(right, width), min(bottom, height)
    if right - left < 2 or bottom - top < 2:
        return None
    return (left, top, right, bottom)


def read_layout(names: bool = True) -> DesktopLayout:
    """讀取目前的桌面圖示排列。

    names=False 時不讀圖示名稱(監看時用不到,可省下一半的跨行程呼叫)。
    """
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        raise IconDetectionError("需要 64 位元的 Python(必須與檔案總管位元數相同)")

    winapi.enable_dpi_awareness()
    vx, vy, width, height = winapi.virtual_screen()
    screens = screen_api.list_screens(vx, vy)

    listview = find_desktop_listview()
    if not listview:
        raise IconDetectionError("找不到桌面圖示視窗(檔案總管可能正在重新啟動)")

    if not user32.IsWindowVisible(listview):
        # 使用者關閉了「顯示桌面圖示」
        return DesktopLayout(width, height, (), icons_visible=False, screens=screens)

    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(listview, ctypes.byref(pid))
    if not pid.value:
        raise IconDetectionError("無法取得檔案總管的行程代碼")

    try:
        count = winapi.send_message(listview, LVM_GETITEMCOUNT)
    except TimeoutError as exc:
        raise IconDetectionError(str(exc)) from exc

    # ListView 用戶區原點在螢幕上的位置 → 換算成圖片座標的位移
    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(listview, ctypes.byref(origin))
    dx, dy = origin.x - vx, origin.y - vy

    icons: List[DesktopIcon] = []
    if count > 0:
        with _RemoteBuffer(pid.value) as buf:
            for index in range(count):
                try:
                    icon = _read_icon(listview, buf, index, dx, dy, width, height, names)
                except TimeoutError as exc:
                    raise IconDetectionError(str(exc)) from exc
                if icon is not None:
                    icons.append(icon)

    return DesktopLayout(width, height, tuple(icons), icons_visible=True, screens=screens)


def _read_icon(listview, buf: _RemoteBuffer, index: int, dx: int, dy: int,
               width: int, height: int, names: bool = True) -> Optional[DesktopIcon]:
    # 外框:送出前 RECT.left 要填入想要的範圍種類
    request = wintypes.RECT(LVIR_BOUNDS, 0, 0, 0)
    buf.write(request)
    if not winapi.send_message(listview, LVM_GETITEMRECT, index, buf.address):
        return None  # 讀取當下項目剛好被刪除
    r = buf.read(wintypes.RECT)
    rect = _clip((r.left + dx, r.top + dy, r.right + dx, r.bottom + dy), width, height)
    if rect is None:
        return None

    if not names:
        return DesktopIcon("", *rect)

    # 名稱
    item = _LVITEMW()
    item.iSubItem = 0
    item.pszText = buf.address + _TEXT_OFFSET
    item.cchTextMax = _TEXT_CHARS
    buf.write(item)
    length = winapi.send_message(listview, LVM_GETITEMTEXTW, index, buf.address)
    name = ""
    if 0 < length < _TEXT_CHARS:
        raw = buf.read(ctypes.c_wchar * (length + 1), _TEXT_OFFSET)
        name = raw.value

    return DesktopIcon(name, *rect)


def _main() -> int:  # python -m deskisle.icons
    layout = read_layout()
    print(f"{layout.width}x{layout.height}, {len(layout.icons)} icons")
    for icon in layout.icons:
        print(icon)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
