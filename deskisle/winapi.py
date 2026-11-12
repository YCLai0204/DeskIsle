"""Win32 函式宣告與共用的小工具。

所有 ctypes 原型都集中在這裡宣告。64 位元下代碼與指標是 8 位元組,
不宣告 argtypes/restype 的話 ctypes 會當成 32 位元整數而截斷。
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

if sys.platform != "win32":  # pragma: no cover
    raise ImportError("deskisle.winapi 只能在 Windows 上使用")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
DWORD_PTR = ctypes.c_size_t
SIZE_T = ctypes.c_size_t

# ---- user32 ---------------------------------------------------------------
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND

user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowExW.restype = wintypes.HWND

user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    wintypes.UINT, wintypes.UINT, ctypes.POINTER(DWORD_PTR),
]
user32.SendMessageTimeoutW.restype = LRESULT

user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD

user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL

user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.ClientToScreen.restype = wintypes.BOOL

user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int

user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
user32.SystemParametersInfoW.restype = wintypes.BOOL

user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND

user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int

shell32.SHQueryUserNotificationState.argtypes = [ctypes.POINTER(ctypes.c_int)]
shell32.SHQueryUserNotificationState.restype = ctypes.c_long

# ---- kernel32 -------------------------------------------------------------
kernel32.GetCurrentProcess.argtypes = []
kernel32.GetCurrentProcess.restype = wintypes.HANDLE

kernel32.GetCurrentThread.argtypes = []
kernel32.GetCurrentThread.restype = wintypes.HANDLE

kernel32.SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
kernel32.SetThreadPriority.restype = wintypes.BOOL

kernel32.SetProcessWorkingSetSize.argtypes = [wintypes.HANDLE, SIZE_T, SIZE_T]
kernel32.SetProcessWorkingSetSize.restype = wintypes.BOOL

kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE

kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateEventW.restype = wintypes.HANDLE

kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.OpenEventW.restype = wintypes.HANDLE

kernel32.SetEvent.argtypes = [wintypes.HANDLE]
kernel32.SetEvent.restype = wintypes.BOOL

kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

kernel32.VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, SIZE_T, wintypes.DWORD, wintypes.DWORD]
kernel32.VirtualAllocEx.restype = ctypes.c_void_p

kernel32.VirtualFreeEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, SIZE_T, wintypes.DWORD]
kernel32.VirtualFreeEx.restype = wintypes.BOOL

kernel32.ReadProcessMemory.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, SIZE_T, ctypes.POINTER(SIZE_T),
]
kernel32.ReadProcessMemory.restype = wintypes.BOOL

kernel32.WriteProcessMemory.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, SIZE_T, ctypes.POINTER(SIZE_T),
]
kernel32.WriteProcessMemory.restype = wintypes.BOOL

# ---- 常數 -----------------------------------------------------------------
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
SM_CMONITORS = 80

SMTO_ABORTIFHUNG = 0x0002

PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04

_dpi_ready = False


def enable_dpi_awareness() -> None:
    """讓本行程拿到實體像素座標,而不是被系統縮放過的座標。

    必須在任何視窗/座標相關呼叫之前執行;重複呼叫無害。
    """
    global _dpi_ready
    if _dpi_ready:
        return
    _dpi_ready = True
    try:
        # Windows 10 1703+:Per-Monitor V2
        fn = user32.SetProcessDpiAwarenessContext
        fn.argtypes = [ctypes.c_void_p]
        fn.restype = wintypes.BOOL
        if fn(ctypes.c_void_p(-4)):
            return
    except AttributeError:
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)  # Windows 8.1+
        return
    except (OSError, AttributeError):
        pass
    try:
        user32.SetProcessDPIAware()  # Vista+
    except AttributeError:
        pass


def ui_scale() -> float:
    """系統縮放比例(100% → 1.0,150% → 1.5)。"""
    enable_dpi_awareness()
    try:
        fn = user32.GetDpiForSystem
        fn.restype = wintypes.UINT
        dpi = fn()
    except AttributeError:
        dpi = 96
    return max(dpi, 96) / 96.0


def virtual_screen() -> tuple:
    """整個虛擬桌面(所有螢幕的外接矩形):(x, y, 寬, 高)。"""
    enable_dpi_awareness()
    gm = user32.GetSystemMetrics
    return (
        gm(SM_XVIRTUALSCREEN), gm(SM_YVIRTUALSCREEN),
        gm(SM_CXVIRTUALSCREEN), gm(SM_CYVIRTUALSCREEN),
    )


def monitor_count() -> int:
    return max(1, user32.GetSystemMetrics(SM_CMONITORS))


def send_message(hwnd, msg: int, wparam: int = 0, lparam: int = 0, timeout_ms: int = 2000) -> int:
    """SendMessage 的逾時版本;對方視窗沒回應時丟出 TimeoutError 而不是卡死。"""
    result = DWORD_PTR(0)
    ok = user32.SendMessageTimeoutW(
        hwnd, msg, wparam, lparam, SMTO_ABORTIFHUNG, timeout_ms, ctypes.byref(result)
    )
    if not ok:
        raise TimeoutError(f"視窗沒有回應訊息 0x{msg:04X}")
    # 結果是不帶正負號的指標寬度整數,轉回帶正負號
    return ctypes.c_ssize_t(result.value).value


# ---------------------------------------------------------------------------
# 省資源相關
# ---------------------------------------------------------------------------
_DESKTOP_CLASSES = ("Progman", "WorkerW")
# SHQueryUserNotificationState:1 = 螢幕保護/鎖定,2 = 全螢幕程式,
# 3 = 全螢幕 Direct3D(遊戲),4 = 簡報模式
_BUSY_STATES = (1, 2, 3, 4)

THREAD_MODE_BACKGROUND_BEGIN = 0x00010000
THREAD_PRIORITY_LOWEST = -2


def desktop_is_foreground() -> bool:
    """使用者現在是不是正對著桌面(最前面的視窗就是桌面本身)。"""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    buf = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, buf, len(buf))
    return buf.value in _DESKTOP_CLASSES


def user_is_busy() -> bool:
    """有全螢幕程式(遊戲、影片、簡報)在執行,或螢幕已鎖定 → 桌布反正看不到。"""
    if desktop_is_foreground():
        return False
    state = ctypes.c_int(0)
    if shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
        return False
    return state.value in _BUSY_STATES


def lower_thread_priority() -> None:
    """把目前的執行緒降為背景優先權:CPU、磁碟、記憶體都排在前景程式之後。"""
    thread = kernel32.GetCurrentThread()
    if not kernel32.SetThreadPriority(thread, THREAD_MODE_BACKGROUND_BEGIN):
        kernel32.SetThreadPriority(thread, THREAD_PRIORITY_LOWEST)


def trim_memory() -> None:
    """把目前用不到的記憶體還給系統(畫完一張圖之後呼叫)。"""
    import gc
    gc.collect()
    everything = SIZE_T(-1).value
    kernel32.SetProcessWorkingSetSize(kernel32.GetCurrentProcess(), everything, everything)


# ---------------------------------------------------------------------------
# 單一執行個體
# ---------------------------------------------------------------------------
ERROR_ALREADY_EXISTS = 183
EVENT_MODIFY_STATE = 0x0002
INFINITE = 0xFFFFFFFF
_keep_alive = []   # 代碼要活到程式結束


def acquire_single_instance(name: str) -> bool:
    """取得「只能有一個」的標記;已經有另一個在執行時回傳 False。"""
    handle = kernel32.CreateMutexW(None, False, "Local\\" + name)
    already = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
    if handle:
        _keep_alive.append(handle)
    return bool(handle) and not already


def create_signal(name: str):
    """建立一個可被其他行程觸發的訊號;回傳代碼。"""
    handle = kernel32.CreateEventW(None, False, False, "Local\\" + name)
    if handle:
        _keep_alive.append(handle)
    return handle


def wait_signal(handle, timeout_ms: int = INFINITE) -> bool:
    """等到訊號被觸發(等待期間不耗 CPU)。"""
    return kernel32.WaitForSingleObject(handle, timeout_ms) == 0


def send_signal(name: str) -> bool:
    """觸發另一個行程建立的訊號。"""
    handle = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, "Local\\" + name)
    if not handle:
        return False
    try:
        return bool(kernel32.SetEvent(handle))
    finally:
        kernel32.CloseHandle(handle)
