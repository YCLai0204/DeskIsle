"""macOS 的系統功能:螢幕清單、桌面圖示位置、單一執行個體等。

不需要 pyobjc:所有系統查詢都透過內建的 osascript 執行。
- 螢幕清單與 Retina 倍率:JavaScript for Automation(JXA)讀 NSScreen。
- 桌面圖示位置:AppleScript 問 Finder 每個桌面項目的 desktop position。
  第一次執行時 macOS 會詢問是否允許控制「Finder」,要按「好」。

座標:一律用「點」(point),原點是虛擬桌面(所有螢幕的外接矩形)左上角、y 往下。
每個螢幕的 Retina 倍率記在 Screen.scale,套用桌布時再畫成實體像素。

省資源:呼叫 osascript 一次約要 0.1 秒,所以不會每次檢查都問 Finder。
只有 ~/Desktop 資料夾或它的 .DS_Store(Finder 記錄圖示位置的檔案)變動時才重新讀取,
另外每隔 REFRESH_SECONDS 秒保險重讀一次;螢幕清單每 SCREEN_SECONDS 秒更新一次。

這個模組在任何作業系統都能匯入(測試會在 Windows 上用假的 osascript 執行)。
"""
from __future__ import annotations

import gc
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

from .layout import DesktopIcon, DesktopLayout, IconDetectionError, Screen

REFRESH_SECONDS = 10.0     # 桌面沒有變動時,多久保險重讀一次圖示位置
SCREEN_SECONDS = 15.0      # 多久重新查詢一次螢幕清單
_OSASCRIPT_TIMEOUT = 15

# ---------------------------------------------------------------------------
# osascript
# ---------------------------------------------------------------------------
_NOT_AUTHORIZED = ("-1743", "not authorized", "不允許", "未獲授權")


def run_osascript(script: str, *args: str, javascript: bool = False) -> str:
    """執行一段 AppleScript(或 JXA),回傳輸出文字;失敗時丟出 IconDetectionError。"""
    command = ["osascript"] + (["-l", "JavaScript"] if javascript else []) + ["-e", script] + list(args)
    try:
        done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                              timeout=_OSASCRIPT_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise IconDetectionError(f"無法執行 osascript:{exc}") from exc
    if done.returncode != 0:
        message = (done.stderr or done.stdout).strip()
        if any(key in message.lower() for key in _NOT_AUTHORIZED):
            raise IconDetectionError(
                "沒有權限控制 Finder。請到「系統設定 → 隱私權與安全性 → 自動化」"
                "允許 DeskIsle(或你用來執行它的終端機)控制「Finder」。")
        raise IconDetectionError(f"osascript 執行失敗:{message}")
    return done.stdout.strip()


# ---------------------------------------------------------------------------
# 螢幕
# ---------------------------------------------------------------------------
SCREENS_JXA = r"""
ObjC.import('AppKit');
var list = $.NSScreen.screens;
var out = [];
for (var i = 0; i < list.count; i++) {
  var s = list.objectAtIndex(i);
  var f = s.frame;
  var number = s.deviceDescription.objectForKey('NSScreenNumber');
  out.push({id: String(ObjC.unwrap(number)), x: f.origin.x, y: f.origin.y,
            w: f.size.width, h: f.size.height, scale: s.backingScaleFactor});
}
JSON.stringify(out);
"""


def parse_screens(text: str) -> Tuple[Tuple[Screen, ...], Tuple[int, int]]:
    """把 SCREENS_JXA 的輸出換成 Screen(圖片座標),並回傳虛擬桌面左上角(主螢幕座標)。

    NSScreen 的座標原點在主螢幕左下角、y 往上;換成原點在左上角、y 往下。
    第一個螢幕就是主螢幕(有選單列的那個)。
    """
    data = json.loads(text)
    if not data:
        raise IconDetectionError("找不到任何螢幕")
    main_height = data[0]["h"]
    raw = []
    for index, item in enumerate(data):
        left = int(round(item["x"]))
        top = int(round(main_height - item["y"] - item["h"]))
        raw.append((str(item["id"]), left, top, int(round(item["w"])), int(round(item["h"])),
                    index == 0, float(item.get("scale") or 1.0)))
    origin_x = min(r[1] for r in raw)
    origin_y = min(r[2] for r in raw)
    screens = tuple(sorted(
        (Screen(i, l - origin_x, t - origin_y, w, h, primary, scale) for i, l, t, w, h, primary, scale in raw),
        key=lambda s: (s.left, s.top),
    ))
    return screens, (origin_x, origin_y)


_screen_cache = {"at": -1e9, "value": None}
_lock = threading.Lock()


def _screens_and_origin():
    with _lock:
        now = time.monotonic()
        if _screen_cache["value"] is None or now - _screen_cache["at"] > SCREEN_SECONDS:
            _screen_cache["value"] = parse_screens(run_osascript(SCREENS_JXA, javascript=True))
            _screen_cache["at"] = now
        return _screen_cache["value"]


def list_screens() -> Tuple[Screen, ...]:
    return _screens_and_origin()[0]


def virtual_screen() -> tuple:
    """整個虛擬桌面:(x, y, 寬, 高),單位是點。"""
    screens, (origin_x, origin_y) = _screens_and_origin()
    return (origin_x, origin_y, max(s.right for s in screens), max(s.bottom for s in screens))


def monitor_count() -> int:
    return len(list_screens())


# ---------------------------------------------------------------------------
# 桌面圖示
# ---------------------------------------------------------------------------
ICONS_SCRIPT = r"""
tell application "Finder"
  set thePositions to desktop position of every item of desktop
  set theNames to name of every item of desktop
  try
    set opts to icon view options of window of desktop
    set iconSize to icon size of opts
    set textSize to text size of opts
    set labelPos to (label position of opts) as text
  on error
    set iconSize to 64
    set textSize to 12
    set labelPos to "bottom"
  end try
end tell
set out to (iconSize as text) & tab & (textSize as text) & tab & labelPos & linefeed
repeat with i from 1 to count of thePositions
  set p to item i of thePositions
  set out to out & ((item 1 of p) as text) & tab & ((item 2 of p) as text) & tab & (item i of theNames) & linefeed
end repeat
return out
"""


def parse_icons(text: str, origin: Tuple[int, int]) -> List[DesktopIcon]:
    """把 ICONS_SCRIPT 的輸出換成圖示矩形(圖片座標)。

    Finder 給的是圖示圖片的中心點;外框依圖示大小、文字大小與文字位置估算
    (文字在下方時約兩行高、比圖示寬一些)。
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    head = lines[0].split("\t")
    icon = float(head[0].replace(",", ".")) if head and head[0] else 64.0
    font = float(head[1].replace(",", ".")) if len(head) > 1 and head[1] else 12.0
    label_right = len(head) > 2 and "right" in head[2].lower()
    ox, oy = origin
    icons = []
    for line in lines[1:]:
        parts = line.split("\t", 2)
        if len(parts) < 2:
            continue
        try:
            x, y = float(parts[0].replace(",", ".")), float(parts[1].replace(",", "."))
        except ValueError:
            continue
        name = parts[2] if len(parts) > 2 else ""
        x, y = x - ox, y - oy
        half = icon / 2
        if label_right:
            rect = (x - half, y - half, x + half + font * 10, y + half)
        else:
            width = max(icon, font * 7.5)
            rect = (x - width / 2, y - half, x + width / 2, y + half + font * 2.8)
        icons.append(DesktopIcon(name, *(int(round(v)) for v in rect)))
    return icons


def desktop_folder() -> Path:
    return Path.home() / "Desktop"


def _desktop_stamp() -> tuple:
    """~/Desktop 的變動指紋:檔案清單、資料夾與 .DS_Store 的修改時間。"""
    folder = desktop_folder()
    stamp = []
    for path in (folder, folder / ".DS_Store"):
        try:
            stamp.append(path.stat().st_mtime_ns)
        except OSError:
            stamp.append(0)
    try:
        stamp.append(tuple(sorted(os.listdir(folder))))
    except OSError:
        stamp.append(())
    return tuple(stamp)


def icons_visible() -> bool:
    """Finder 是否顯示桌面圖示(defaults write com.apple.finder CreateDesktop false 會隱藏)。"""
    try:
        done = subprocess.run(["defaults", "read", "com.apple.finder", "CreateDesktop"],
                              capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return True
    return done.stdout.strip().lower() not in ("0", "false", "no")


_icon_cache = {"stamp": None, "at": -1e9, "screens": None, "layout": None}


def read_layout(names: bool = True) -> DesktopLayout:
    """讀取目前的桌面圖示排列(單位是點)。桌面沒有變動時直接用上次的結果。"""
    screens, origin = _screens_and_origin()
    width = max(s.right for s in screens)
    height = max(s.bottom for s in screens)
    stamp = _desktop_stamp()
    now = time.monotonic()
    cache = _icon_cache
    if (cache["layout"] is not None and cache["stamp"] == stamp and cache["screens"] == screens
            and now - cache["at"] < REFRESH_SECONDS):
        return cache["layout"]

    if not icons_visible():
        layout = DesktopLayout(width, height, (), icons_visible=False, screens=screens)
    else:
        icons = []
        for icon in parse_icons(run_osascript(ICONS_SCRIPT), origin):
            left, top = max(icon.left, 0), max(icon.top, 0)
            right, bottom = min(icon.right, width), min(icon.bottom, height)
            if right - left >= 2 and bottom - top >= 2:
                icons.append(DesktopIcon(icon.name, left, top, right, bottom))
        layout = DesktopLayout(width, height, tuple(icons), icons_visible=True, screens=screens)
    cache.update(stamp=stamp, at=now, screens=screens, layout=layout)
    return layout


# ---------------------------------------------------------------------------
# 省資源相關(Mac 上大多不需要)
# ---------------------------------------------------------------------------
def enable_dpi_awareness() -> None:
    """Mac 用「點」座標,不需要設定。"""


def ui_scale() -> float:
    """座標已經是點,像素類參數不必再放大;Retina 由 Screen.scale 處理。"""
    return 1.0


def desktop_is_foreground() -> bool:
    """Mac 上沒變動時讀取幾乎不花成本,一律以「正對桌面」的間隔檢查。"""
    return True


def user_is_busy() -> bool:
    return False


def lower_thread_priority() -> None:
    """macOS 沒有個別執行緒的背景優先權可用;不處理。"""


def trim_memory() -> None:
    gc.collect()


# ---------------------------------------------------------------------------
# 單一執行個體:在暫存資料夾放一個 Unix socket
# ---------------------------------------------------------------------------
_SOCKET_NAME = "DeskIsle.sock"
_server: Optional[socket.socket] = None


def _socket_path() -> str:
    return os.path.join(tempfile.gettempdir(), _SOCKET_NAME)


def acquire_single_instance(name: str = "") -> bool:
    """取得「只能有一個」的標記;已經有另一個在執行時回傳 False。"""
    global _server
    path = _socket_path()
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.connect(path)
        return False            # 有人在聽 → 另一個 DeskIsle 正在執行
    except OSError:
        pass
    finally:
        probe.close()
    try:
        os.unlink(path)         # 上次沒正常結束留下的
    except OSError:
        pass
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(4)
    _server = server
    return True


def create_signal(name: str = ""):
    """回傳單一執行個體的 socket;沒有取得時回傳 None。"""
    return _server


def wait_signal(handle, timeout_ms: int = 0) -> bool:
    """等到另一個執行個體連進來(等待期間不耗 CPU)。"""
    try:
        connection, _address = handle.accept()
        connection.close()
        return True
    except OSError:
        return False


def send_signal(name: str = "") -> bool:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(_socket_path())
        return True
    except OSError:
        return False
    finally:
        client.close()
