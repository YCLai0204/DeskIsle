"""監看桌面圖示,排列改變時重畫桌布。

省資源的做法:
- 平常只做一件事:每隔一段時間讀一次圖示座標(幾毫秒),其餘時間都在睡。
- 使用者正對著桌面時檢查得勤(poll_interval);其他時候放慢(idle_interval)。
- 全螢幕程式執行或螢幕鎖定時完全不檢查,等它結束再說。
- 只有排列真的改變、而且穩定下來之後才重畫。
- 重畫在背景優先權的執行緒進行;畫完立刻把記憶體還給系統。
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, replace
from typing import Callable, Optional

from PIL import Image

from . import system
from .config import Config
from .engine import decor, photo
from .engine.layout import DesktopLayout, IconDetectionError, screen_rects
from .system import read_layout, wallpaper
from .engine.render import render
from .engine.themes import Theme, get_theme

GAP_COLOR = (0, 0, 0)   # 多螢幕合成圖中,沒有螢幕的空隙


def resolve_theme(config: Config) -> Theme:
    """實際要用的主題:選「從圖片取色」時,是用圖片顏色重新上色過的版本。"""
    theme = get_theme(config.theme)
    if config.image_mode == "colors":
        theme = photo.recolored(theme, config.image)
    return theme


def render_screen(layout: DesktopLayout, config: Config, index: int, ratio: float = 1.0,
                  debug: bool = False) -> Image.Image:
    """畫出第 index 個螢幕的桌布。ratio < 1 時畫縮小版(預覽用);
    ratio = screen.scale 時畫成螢幕的實體像素(Mac 的 Retina 螢幕)。

    每個螢幕各自計算地形;種子加上螢幕序號,讓同尺寸的螢幕也不會長得一樣。
    """
    screen = layout.screen_list()[index]
    width = max(1, int(round(screen.width * ratio)))
    height = max(1, int(round(screen.height * ratio)))
    layer = None
    if config.image_mode in ("land", "water"):
        picture = photo.load(config.image)
        if picture is not None:          # 圖片不見了就照一般主題畫
            layer = photo.cover(picture, width, height)   # 每個螢幕各自裁切
    return render(
        width, height, screen_rects(layout, screen, ratio), resolve_theme(config),
        margin=config.margin, blend=config.blend, roughness=config.roughness,
        seed=config.seed + 1013 * index, scale=system.ui_scale() * ratio,
        decorations=config.decorations, debug=debug,
        photo=layer, photo_mode=config.image_mode if layer is not None else "",
    )


def render_layout(layout: DesktopLayout, config: Config, debug: bool = False) -> Image.Image:
    """把整個桌面(所有螢幕)畫成一張圖。"""
    screens = layout.screen_list()
    if len(screens) == 1 and (screens[0].width, screens[0].height) == (layout.width, layout.height):
        return render_screen(layout, config, 0, debug=debug)
    canvas = Image.new("RGB", (layout.width, layout.height), GAP_COLOR)
    for index, screen in enumerate(screens):
        canvas.paste(render_screen(layout, config, index, debug=debug), (screen.left, screen.top))
    return canvas


def apply_layout(layout: DesktopLayout, config: Config):
    """畫圖並設為桌布;回傳桌布檔案路徑的清單。

    多螢幕而且系統支援時,只畫、只更新設定裡選的螢幕;否則整個桌面畫成一張圖套用。
    """
    screens = layout.screen_list()
    if layout.can_choose_screens():
        images = [(screen, render_screen(layout, config, screens.index(screen), ratio=screen.scale))
                  for screen in layout.selected_screens(config.screens)]
        return wallpaper.apply_per_screen(images)
    if len(screens) == 1:
        image = render_screen(layout, config, 0, ratio=screens[0].scale)
        return [wallpaper.apply_image(image, 1)]
    return [wallpaper.apply_image(render_layout(layout, config), layout.monitors)]


def new_seed(old: int) -> int:
    """換一個跟原本不一樣的種子。"""
    while True:
        seed = random.randrange(0, 100000)
        if seed != old:
            return seed


def look_key(config: Config) -> tuple:
    """設定中會影響畫面的部分;這些一變就要重畫。"""
    return (config.theme, config.seed, config.margin, config.blend, config.roughness,
            config.decorations, config.screens, config.image, config.image_mode)


class LayoutDebouncer:
    """判斷「現在該不該重畫」。

    新排列第一次出現時先記下來,等它維持不變超過 debounce 秒才放行,
    避免自動排列時一連串中間狀態各畫一次。第一次一律立刻放行。
    """

    def __init__(self, debounce: float):
        self.debounce = debounce
        self._applied = None
        self._pending = None
        self._pending_since = 0.0

    @property
    def waiting(self) -> bool:
        """有一個新排列正在等待確認。"""
        return self._pending is not None

    def should_apply(self, signature, now: float) -> bool:
        if signature == self._applied:
            self._pending = None
            return False
        if self._applied is None:
            return True
        if signature != self._pending:
            self._pending, self._pending_since = signature, now
            return self.debounce <= 0
        return now - self._pending_since >= self.debounce

    def mark_applied(self, signature) -> None:
        self._applied, self._pending = signature, None


@dataclass(frozen=True)
class WatchStatus:
    state: str               # following / paused / error / stopped
    message: str = ""
    icons: int = 0
    updated_at: str = ""     # 上次更新桌布的時間(HH:MM:SS)
    seconds: float = 0.0     # 上次重畫花了幾秒
    updates: int = 0         # 共更新幾次


class Watcher:
    """可以啟動、停止的監看器。run() 是阻塞版本;start() 會開一個背景執行緒。

    設定 reseed_on_move 開啟時,圖示排列一改變就換一個種子再重畫,
    並呼叫 on_reseed(新種子)。on_reseed 必須「立刻」讓 get_config() 回傳新的種子,
    否則下一輪會把它當成外觀被改回去而又重畫一次。
    """

    def __init__(self, get_config: Callable[[], Config],
                 on_status: Optional[Callable[[WatchStatus], None]] = None,
                 on_reseed: Optional[Callable[[int], None]] = None):
        self._get_config = get_config
        self._on_status = on_status
        self._on_reseed = on_reseed
        self._last_layout = None   # 上次畫桌布時的圖示排列
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._force = False
        self._thread: Optional[threading.Thread] = None
        self.status = WatchStatus("stopped")

    # ---- 控制 ---------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._wake.clear()
        self._thread = threading.Thread(target=self.run, name="deskisle-watcher", daemon=True)
        self._thread.start()

    def stop(self, wait: bool = True) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if wait and thread is not None and thread is not threading.current_thread():
            thread.join(timeout=10)
        self._thread = None

    def refresh(self) -> None:
        """設定變了:不等防抖動,下一輪立刻重畫。"""
        self._force = True
        self._wake.set()

    # ---- 主迴圈 -------------------------------------------------------------
    def _report(self, **changes) -> None:
        data = dict(self.status.__dict__)
        data.update(changes)
        status = WatchStatus(**data)
        changed = status != self.status
        self.status = status
        if changed and self._on_status is not None:
            try:
                self._on_status(status)
            except Exception:
                pass  # 介面已關閉等情況,不能讓監看跟著掛掉

    def run(self, max_updates: Optional[int] = None) -> int:
        """監看直到 stop() 被呼叫。回傳重畫次數。max_updates 供測試用。"""
        system.lower_thread_priority()
        debouncer = LayoutDebouncer(self._get_config().debounce)
        self._report(state="following", message="", updates=0)
        updates = 0
        try:
            while not self._stop.is_set() and (max_updates is None or updates < max_updates):
                config = self._get_config()
                debouncer.debounce = config.debounce
                delay, applied = self._tick(config, debouncer)
                updates += applied
                if applied:
                    self._report(updates=updates)
                if self._stop.is_set() or (max_updates is not None and updates >= max_updates):
                    break
                self._wake.wait(delay)
                self._wake.clear()
        finally:
            self._report(state="stopped", message="")
        return updates

    def _tick(self, config: Config, debouncer: LayoutDebouncer):
        """做一輪檢查;回傳 (下次檢查前要睡幾秒, 這一輪是否重畫了)。"""
        slow = max(config.idle_interval, config.poll_interval)
        if config.pause_when_busy and system.user_is_busy():
            self._report(state="paused", message="全螢幕程式執行中或螢幕已鎖定")
            return slow, 0

        try:
            layout = read_layout(names=False)
        except IconDetectionError as exc:
            self._report(state="error", message=str(exc))
            return slow, 0

        layout_key = layout.signature()
        signature = (layout_key, look_key(config))
        force, self._force = self._force, False
        if force or debouncer.should_apply(signature, time.monotonic()):
            # 是圖示移動造成的重畫(不是第一次、也不是外觀設定改了)→ 換一個種子
            moved = (config.reseed_on_move and not force and self._last_layout is not None
                     and layout_key != self._last_layout)
            if moved:
                config = replace(config, seed=new_seed(config.seed))
                signature = (layout_key, look_key(config))
            started = time.perf_counter()
            try:
                apply_layout(layout, config)
            except Exception as exc:  # 磁碟滿、登錄檔被鎖等;下一輪再試
                self._report(state="error", message=f"更新桌布失敗:{exc}")
                return slow, 0
            finally:
                decor.clear_cache()
                photo.clear_cache()
                system.trim_memory()
            debouncer.mark_applied(signature)
            self._last_layout = layout_key
            if moved and self._on_reseed is not None:
                self._on_reseed(config.seed)
            self._report(
                state="following", icons=len(layout.icons),
                message="" if layout.icons_visible else "桌面圖示已隱藏",
                updated_at=time.strftime("%H:%M:%S"), seconds=time.perf_counter() - started,
            )
            return config.poll_interval, 1

        self._report(state="following", icons=len(layout.icons),
                     message="" if layout.icons_visible else "桌面圖示已隱藏")
        if debouncer.waiting:
            # 排列待確認期間檢查得勤一點,讓反應時間接近 debounce
            return min(config.poll_interval, max(0.1, config.debounce / 2)), 0
        return (config.poll_interval if system.desktop_is_foreground() else slow), 0


def watch(config: Config, log: Callable[[str], None] = print,
          max_updates: Optional[int] = None) -> int:
    """命令列用:監看直到 Ctrl+C。回傳重畫的次數。"""
    last = {"state": None, "updates": 0}

    def on_status(status: WatchStatus) -> None:
        if status.updates != last["updates"]:
            last["updates"] = status.updates
            log(f"[{status.updated_at}] 已更新桌布:{status.icons} 個圖示,{status.seconds:.2f} 秒")
        if status.state != last["state"]:
            if status.state == "error":
                log(f"暫時無法更新:{status.message}(會持續重試)")
            elif status.state == "paused":
                log(f"暫停中:{status.message}")
            elif last["state"] in ("error", "paused") and status.state == "following":
                log("已恢復監看")
            last["state"] = status.state

    box = [config]

    def on_reseed(seed: int) -> None:
        box[0] = replace(box[0], seed=seed)

    watcher = Watcher(lambda: box[0], on_status, on_reseed)
    try:
        return watcher.run(max_updates)
    except KeyboardInterrupt:
        return watcher.status.updates
