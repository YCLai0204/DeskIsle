"""套用、備份與還原桌布。"""
from __future__ import annotations

import ctypes
import hashlib
import json
import shutil
import winreg
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image

from . import screens as screen_api
from ...config import app_dir
from ...engine.layout import Screen
from .winapi import user32

SPI_SETDESKWALLPAPER = 0x0014
SPI_GETDESKWALLPAPER = 0x0073
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02

STYLE_FILL = "10"   # 填滿
STYLE_SPAN = "22"   # 跨螢幕

_DESKTOP_KEY = r"Control Panel\Desktop"
_WALLPAPERS_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Wallpapers"
_OUTPUT_NAMES = ("wallpaper_a.png", "wallpaper_b.png")

# Windows 記錄的背景類型
BACKGROUND_KINDS = {0: "圖片", 1: "純色", 2: "幻燈片", 3: "Windows 焦點"}


@dataclass(frozen=True)
class WallpaperState:
    path: str            # 桌布圖片路徑;空字串 = 沒有圖片(純色)
    style: str           # WallpaperStyle 登錄值
    tile: str            # TileWallpaper 登錄值
    kind: int = 0        # 背景類型,見 BACKGROUND_KINDS
    backup: str = ""     # 原圖備份的檔名(在 app_dir 內),沒有則為空
    per_monitor: Dict[str, str] = field(default_factory=dict)   # 多螢幕時每個螢幕原本的圖片


def state_path() -> Path:
    return app_dir() / "state.json"


def _read_reg(key_path: str, name: str, default):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return default


def current() -> WallpaperState:
    """目前的桌布設定。"""
    buf = ctypes.create_unicode_buffer(1024)
    user32.SystemParametersInfoW(SPI_GETDESKWALLPAPER, len(buf), buf, 0)
    kind = _read_reg(_WALLPAPERS_KEY, "BackgroundType", 0)
    return WallpaperState(
        path=buf.value,
        style=str(_read_reg(_DESKTOP_KEY, "WallpaperStyle", STYLE_FILL)),
        tile=str(_read_reg(_DESKTOP_KEY, "TileWallpaper", "0")),
        kind=kind if isinstance(kind, int) else 0,
    )


def _set(path: str, style: str, tile: str) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _DESKTOP_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "WallpaperStyle", 0, winreg.REG_SZ, style)
        winreg.SetValueEx(key, "TileWallpaper", 0, winreg.REG_SZ, tile)
    ok = user32.SystemParametersInfoW(
        SPI_SETDESKWALLPAPER, 0, ctypes.c_wchar_p(path), SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
    )
    if not ok:
        raise OSError(f"設定桌布失敗(錯誤碼 {ctypes.get_last_error()})")


def is_ours(path: str) -> bool:
    """這個路徑是不是 DeskIsle 自己產生的桌布。"""
    if not path:
        return False
    try:
        return Path(path).resolve().parent == app_dir().resolve()
    except OSError:
        return False


def monitor_wallpapers() -> Dict[str, str]:
    """多螢幕時,每個螢幕目前的桌布圖片;單螢幕或系統不支援時回傳空的。"""
    if len(screen_api.monitor_rects()) < 2:
        return {}
    found = {}
    try:
        with screen_api.open_desktop_wallpaper() as desktop:
            for monitor_id in desktop.monitor_ids():
                if monitor_id and desktop.monitor_rect(monitor_id) is not None:
                    found[monitor_id] = desktop.get_wallpaper(monitor_id)
    except OSError:
        return {}
    return found


def load_backup() -> Optional[WallpaperState]:
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
        return WallpaperState(**data)
    except (OSError, ValueError, TypeError):
        return None


def backup_original() -> Optional[WallpaperState]:
    """記下原本的桌布(只在還沒有備份時)。回傳剛建立的備份,否則 None。"""
    if state_path().exists():
        return None
    state = current()
    if is_ours(state.path):
        return None  # 目前已經是我們的圖,沒有「原本的桌布」可記
    folder = app_dir()
    folder.mkdir(parents=True, exist_ok=True)

    backup_name = ""
    source = Path(state.path) if state.path else None
    if source and source.is_file():
        # 複製一份:Windows 焦點等來源的快取檔之後可能被系統清掉
        backup_name = "original" + (source.suffix or ".jpg")
        try:
            shutil.copy2(source, folder / backup_name)
        except OSError:
            backup_name = ""
    per_monitor = {k: v for k, v in monitor_wallpapers().items() if not is_ours(v)}
    state = WallpaperState(state.path, state.style, state.tile, state.kind, backup_name, per_monitor)
    state_path().write_text(json.dumps(asdict(state), indent=2, ensure_ascii=False), encoding="utf-8")
    return state


def apply_image(image: Image.Image, monitors: int = 1) -> Path:
    """把圖片存檔並設為桌布;第一次呼叫時會先備份原本的桌布。"""
    backup_original()
    folder = app_dir()
    folder.mkdir(parents=True, exist_ok=True)
    # 兩個檔名交替使用:路徑每次不同,Windows 一定會重新載入
    now = Path(current().path).name.lower()
    name = _OUTPUT_NAMES[1] if now == _OUTPUT_NAMES[0] else _OUTPUT_NAMES[0]
    target = folder / name
    image.save(target, "PNG", compress_level=1)
    _set(str(target), STYLE_SPAN if monitors > 1 else STYLE_FILL, "0")
    return target


def _screen_file_names(screen: Screen) -> Tuple[str, str]:
    """每個螢幕自己的兩個交替檔名(依螢幕代碼,拔插螢幕後仍是同一組)。"""
    key = hashlib.sha1(screen.id.encode("utf-8")).hexdigest()[:8]
    return (f"wallpaper_{key}_a.png", f"wallpaper_{key}_b.png")


def apply_per_screen(images: Sequence[Tuple[Screen, Image.Image]]) -> List[Path]:
    """每個螢幕各自設定桌布(只動 images 裡的螢幕,其他螢幕維持原樣)。

    第一次呼叫時會先備份原本的桌布。回傳寫出的檔案路徑。
    """
    backup_original()
    folder = app_dir()
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    with screen_api.open_desktop_wallpaper() as desktop:
        desktop.set_position(screen_api.DWPOS_FILL)
        for screen, image in images:
            names = _screen_file_names(screen)
            try:
                now = Path(desktop.get_wallpaper(screen.id)).name.lower()
            except OSError:
                now = ""
            target = folder / (names[1] if now == names[0] else names[0])
            image.save(target, "PNG", compress_level=1)
            desktop.set_wallpaper(screen.id, str(target))
            written.append(target)
    return written


def _restore_per_monitor(state: WallpaperState) -> None:
    """原本每個螢幕的圖不一樣時,逐一設回去(做不到就維持 _set 設好的那一張)。"""
    paths = {k: v for k, v in state.per_monitor.items() if v and Path(v).is_file()}
    if len(set(paths.values())) < 2 and all(v == state.path for v in paths.values()):
        return
    try:
        with screen_api.open_desktop_wallpaper() as desktop:
            for monitor_id, path in paths.items():
                if desktop.monitor_rect(monitor_id) is not None:
                    desktop.set_wallpaper(monitor_id, path)
    except OSError:
        pass


def restore() -> Optional[WallpaperState]:
    """還原成備份的桌布。沒有備份時回傳 None。"""
    state = load_backup()
    if state is None:
        return None
    path = state.path
    if path and not Path(path).is_file():
        backup = app_dir() / state.backup if state.backup else None
        path = str(backup) if backup and backup.is_file() else ""
    _set(path, state.style, state.tile)
    if state.per_monitor:
        _restore_per_monitor(state)
    try:
        state_path().unlink()
    except OSError:
        pass
    return state
