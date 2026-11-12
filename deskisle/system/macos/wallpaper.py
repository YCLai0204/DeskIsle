"""macOS 的套用、備份與還原桌布。

用 NSWorkspace 的 setDesktopImageURL(透過 JXA 呼叫)逐一設定每個螢幕。
限制:macOS 只會改「目前這個桌面空間(Space)」的桌布;其他空間要切過去後再套用一次。

macOS 會依檔案路徑快取桌布,所以跟 Windows 一樣在兩個檔名之間交替。
這個模組在任何作業系統都能匯入(測試會用假的 osascript 執行)。
"""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image

from ...config import app_dir
from ...engine.layout import Screen
from .desktop import run_osascript

BACKGROUND_KINDS = {0: "圖片"}
_OUTPUT_NAMES = ("wallpaper_a.png", "wallpaper_b.png")

GET_JXA = r"""
ObjC.import('AppKit');
var ws = $.NSWorkspace.sharedWorkspace;
var list = $.NSScreen.screens;
var out = {};
for (var i = 0; i < list.count; i++) {
  var s = list.objectAtIndex(i);
  var id = String(ObjC.unwrap(s.deviceDescription.objectForKey('NSScreenNumber')));
  var url = ws.desktopImageURLForScreen(s);
  out[id] = (url && !url.isNil()) ? ObjC.unwrap(url.path) : "";
}
JSON.stringify(out);
"""

# 參數:螢幕代碼 路徑 螢幕代碼 路徑 …;代碼為 * 表示所有螢幕
SET_JXA = r"""
function run(argv) {
  ObjC.import('AppKit');
  var ws = $.NSWorkspace.sharedWorkspace;
  var list = $.NSScreen.screens;
  var wanted = {};
  for (var i = 0; i + 1 < argv.length; i += 2) { wanted[argv[i]] = argv[i + 1]; }
  var done = [];
  for (var j = 0; j < list.count; j++) {
    var s = list.objectAtIndex(j);
    var id = String(ObjC.unwrap(s.deviceDescription.objectForKey('NSScreenNumber')));
    var path = wanted[id] || wanted['*'];
    if (!path) { continue; }
    var ok = ws.setDesktopImageURLForScreenOptionsError($.NSURL.fileURLWithPath(path), s,
                                                         $.NSDictionary.dictionary, null);
    if (!ok) { throw new Error('screen ' + id); }
    done.push(id);
  }
  return done.join(',');
}
"""


@dataclass(frozen=True)
class WallpaperState:
    per_screen: Dict[str, str] = field(default_factory=dict)   # 螢幕代碼 → 原本的圖片
    backups: Dict[str, str] = field(default_factory=dict)      # 螢幕代碼 → 原圖備份的檔名
    kind: int = 0

    @property
    def path(self) -> str:
        return next(iter(self.per_screen.values()), "")


def state_path() -> Path:
    return app_dir() / "state.json"


def current() -> Dict[str, str]:
    """每個螢幕目前的桌布圖片路徑。"""
    return json.loads(run_osascript(GET_JXA, javascript=True) or "{}")


def _set(paths: Dict[str, str]) -> None:
    args = []
    for screen_id, path in paths.items():
        args += [screen_id, path]
    run_osascript(SET_JXA, *args, javascript=True)


def is_ours(path: str) -> bool:
    if not path:
        return False
    try:
        return Path(path).resolve().parent == app_dir().resolve()
    except OSError:
        return False


def load_backup() -> Optional[WallpaperState]:
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
        return WallpaperState(**data)
    except (OSError, ValueError, TypeError):
        return None


def backup_original(now: Optional[Dict[str, str]] = None) -> Optional[WallpaperState]:
    """記下每個螢幕原本的桌布(只在還沒有備份時)。回傳剛建立的備份,否則 None。"""
    if state_path().exists():
        return None
    now = current() if now is None else now
    originals = {k: v for k, v in now.items() if v and not is_ours(v)}
    if not originals:
        return None
    folder = app_dir()
    folder.mkdir(parents=True, exist_ok=True)
    backups = {}
    for number, (screen_id, path) in enumerate(originals.items(), 1):
        source = Path(path)
        if source.is_file():
            name = f"original_{number}{source.suffix or '.jpg'}"
            try:
                shutil.copy2(source, folder / name)
                backups[screen_id] = name
            except OSError:
                pass
    state = WallpaperState(originals, backups)
    state_path().write_text(json.dumps(asdict(state), indent=2, ensure_ascii=False), encoding="utf-8")
    return state


def _next_name(names: Tuple[str, str], now_path: str) -> str:
    return names[1] if Path(now_path).name.lower() == names[0] else names[0]


def apply_image(image: Image.Image, monitors: int = 1) -> Path:
    """所有螢幕都設成同一張圖。"""
    now = current()
    backup_original(now)
    folder = app_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / _next_name(_OUTPUT_NAMES, next(iter(now.values()), ""))
    image.save(target, "PNG", compress_level=1)
    _set({"*": str(target)})
    return target


def _screen_file_names(screen: Screen) -> Tuple[str, str]:
    return (f"wallpaper_{screen.id}_a.png", f"wallpaper_{screen.id}_b.png")


def apply_per_screen(images: Sequence[Tuple[Screen, Image.Image]]) -> List[Path]:
    """每個螢幕各自設定桌布(只動 images 裡的螢幕)。"""
    now = current()
    backup_original(now)
    folder = app_dir()
    folder.mkdir(parents=True, exist_ok=True)
    targets: Dict[str, str] = {}
    written = []
    for screen, image in images:
        target = folder / _next_name(_screen_file_names(screen), now.get(screen.id, ""))
        image.save(target, "PNG", compress_level=1)
        targets[screen.id] = str(target)
        written.append(target)
    _set(targets)
    return written


def restore() -> Optional[WallpaperState]:
    """還原成備份的桌布。沒有備份時回傳 None。"""
    state = load_backup()
    if state is None:
        return None
    paths = {}
    for screen_id, path in state.per_screen.items():
        if not Path(path).is_file() and screen_id in state.backups:
            path = str(app_dir() / state.backups[screen_id])
        if Path(path).is_file():
            paths[screen_id] = path
    if paths:
        _set(paths)
    try:
        state_path().unlink()
    except OSError:
        pass
    return state
