"""監看桌面圖示,排列改變時重畫桌布。

省資源的做法:
- 平常只做一件事:每隔一段時間讀一次圖示座標(幾毫秒),其餘時間都在睡。
- 使用者正對著桌面時檢查得勤(poll_interval);其他時候放慢(idle_interval)。
- 全螢幕程式執行或螢幕鎖定時完全不檢查,等它結束再說。
- 只有排列真的改變、而且穩定下來之後才重畫。
- 重畫在背景優先權的執行緒進行;畫完立刻把記憶體還給系統。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from . import decor, wallpaper, winapi
from .config import Config
from .icons import DesktopLayout, IconDetectionError, read_layout
from .render import render
from .themes import get_theme


def render_layout(layout: DesktopLayout, config: Config, debug: bool = False):
    """依設定把一個排列畫成圖片。"""
    return render(
        layout.width, layout.height, layout.rects, get_theme(config.theme),
        margin=config.margin, blend=config.blend, roughness=config.roughness,
        seed=config.seed, scale=winapi.ui_scale(), decorations=config.decorations, debug=debug,
    )


def apply_layout(layout: DesktopLayout, config: Config):
    """畫圖並設為桌布;回傳桌布檔案路徑。"""
    return wallpaper.apply_image(render_layout(layout, config), layout.monitors)


def look_key(config: Config) -> tuple:
    """設定中會影響畫面的部分;這些一變就要重畫。"""
    return (config.theme, config.seed, config.margin, config.blend, config.roughness,
            config.decorations)


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
    """可以啟動、停止的監看器。run() 是阻塞版本;start() 會開一個背景執行緒。"""

    def __init__(self, get_config: Callable[[], Config],
                 on_status: Optional[Callable[[WatchStatus], None]] = None):
        self._get_config = get_config
        self._on_status = on_status
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
        winapi.lower_thread_priority()
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
        if config.pause_when_busy and winapi.user_is_busy():
            self._report(state="paused", message="全螢幕程式執行中或螢幕已鎖定")
            return slow, 0

        try:
            layout = read_layout(names=False)
        except IconDetectionError as exc:
            self._report(state="error", message=str(exc))
            return slow, 0

        signature = (layout.signature(), look_key(config))
        force, self._force = self._force, False
        if force or debouncer.should_apply(signature, time.monotonic()):
            started = time.perf_counter()
            try:
                apply_layout(layout, config)
            except Exception as exc:  # 磁碟滿、登錄檔被鎖等;下一輪再試
                self._report(state="error", message=f"更新桌布失敗:{exc}")
                return slow, 0
            finally:
                decor.clear_cache()
                winapi.trim_memory()
            debouncer.mark_applied(signature)
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
        return (config.poll_interval if winapi.desktop_is_foreground() else slow), 0


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

    watcher = Watcher(lambda: config, on_status)
    try:
        return watcher.run(max_updates)
    except KeyboardInterrupt:
        return watcher.status.updates
