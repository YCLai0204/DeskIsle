"""「測試」頁:只在以原始碼執行時出現。

打包時這個模組會被排除(見 build.py),而且 ui/app.py 在打包後的執行檔裡
也不會嘗試載入它,所以使用者拿到的程式沒有這一頁。

這一頁的所有功能都不會改動桌布。
"""
from __future__ import annotations

import os
import random
import subprocess
import sys
import threading
import time
import tkinter as tk
from dataclasses import replace
from pathlib import Path

from .. import __version__, system
from ..config import app_dir
from ..engine import decor
from ..engine.layout import DesktopIcon, DesktopLayout
from ..engine.themes import THEMES
from ..system import read_layout
from ..watcher import render_layout
from .widgets import Button, Card

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def add_test_page(app) -> None:
    kit = app.kit
    p, px = kit.p, kit.px
    page = app.add_page("測試", "test", "只在以原始碼執行時出現;這一頁的功能都不會改動桌布。")

    # log_box 在頁面最下面建立;這些函式要等按下按鈕才會用到它
    def log(text: str = "") -> None:
        def write():
            log_box.configure(state="normal")
            log_box.insert("end", text + "\n")
            log_box.see("end")
            log_box.configure(state="disabled")
        app._ui(write)

    def clear() -> None:
        log_box.configure(state="normal")
        log_box.delete("1.0", "end")
        log_box.configure(state="disabled")

    def in_background(work) -> None:
        def run():
            try:
                work()
            except Exception as exc:
                log(f"失敗:{exc}")
        threading.Thread(target=run, name="deskisle-test", daemon=True).start()

    # ---- 預覽控制 ----------------------------------------------------------
    app.section(page, "預覽")
    body = app.card(page)
    outline_var = tk.BooleanVar(value=app.debug_preview)

    def toggle_outline() -> None:
        app.debug_preview = outline_var.get()
        app.schedule_preview(10)

    app.toggle_row(body, "畫出圖示外框", "在預覽上標出偵測到的圖示範圍", outline_var, toggle_outline)

    count_var = tk.IntVar(value=25)

    def fake_layout() -> None:
        _x, _y, width, height = system.virtual_screen()
        scale = system.ui_scale()
        cell_w, cell_h = int(76 * scale), int(100 * scale)
        cols, rows = max(1, width // cell_w), max(1, (height - int(60 * scale)) // cell_h)
        cells = [(c, r) for c in range(cols) for r in range(rows)]
        rng = random.Random()
        try:
            count = max(0, int(count_var.get()))
        except (tk.TclError, ValueError):
            count = 25
        chosen = rng.sample(cells, min(len(cells), count))
        icons = tuple(
            DesktopIcon(f"假圖示 {i}", c * cell_w, r * cell_h + int(5 * scale),
                        (c + 1) * cell_w, r * cell_h + int(5 * scale) + int(rng.choice((70, 85)) * scale))
            for i, (c, r) in enumerate(chosen)
        )
        app.layout_override = DesktopLayout(width, height, icons)
        app.schedule_preview(10)
        log(f"預覽改用 {len(icons)} 個隨機位置的假圖示({width}x{height})")

    def real_layout() -> None:
        app.layout_override = None
        app.schedule_preview(10)
        log("預覽改回真實桌面")

    _line, slot = app.row(body, "假圖示", "用隨機排列的假圖示測試")
    field = Card(slot, kit, padding=(8, 4), radius=7, fill=p.field, outline=p.border_strong)
    field.pack(side="left")
    tk.Entry(field.body, textvariable=count_var, width=4, relief="flat", borderwidth=0, highlightthickness=0,
             background=p.field, foreground=p.text, insertbackground=p.text, font=kit.fonts["bold"],
             justify="center").pack()
    Button(slot, kit, "隨機排列", fake_layout, small=True).pack(side="left", padx=(px(8), 0))
    _line, slot = app.row(body, "真實桌面", "預覽改回目前的桌面圖示")
    Button(slot, kit, "回到真實桌面", real_layout, small=True).pack()

    # ---- 檢查工具 ----------------------------------------------------------
    def detect() -> None:
        def work():
            started = time.perf_counter()
            layout = read_layout()
            took = (time.perf_counter() - started) * 1000
            log(f"畫面 {layout.width}x{layout.height},螢幕 {layout.monitors} 個,"
                f"圖示 {len(layout.icons)} 個({took:.1f} 毫秒)")
            if not layout.icons_visible:
                log("桌面圖示目前是隱藏的")
            for icon in layout.icons:
                log(f"  ({icon.left:5d},{icon.top:5d}) {icon.right - icon.left}x{icon.bottom - icon.top}  {icon.name}")
        in_background(work)

    def benchmark() -> None:
        def work():
            log("效能測試中…")
            started = time.perf_counter()
            for _ in range(30):
                layout = read_layout(names=False)
            log(f"讀取圖示位置:平均 {(time.perf_counter() - started) / 30 * 1000:.1f} 毫秒")
            config = app.draft_config()
            for key in THEMES:
                best = None
                for _ in range(2):
                    started = time.perf_counter()
                    render_layout(layout, replace(config, theme=key))
                    took = time.perf_counter() - started
                    best = took if best is None else min(best, took)
                log(f"全尺寸繪製 {key:<8} {best:.2f} 秒")
            decor.clear_cache()
            system.trim_memory()
            log("完成")
        in_background(work)

    def export() -> None:
        def work():
            config = app.draft_config()
            layout = app.layout_override or read_layout(names=True)
            image = render_layout(layout, config, debug=app.debug_preview)
            folder = PROJECT_ROOT / "previews"
            folder.mkdir(exist_ok=True)
            path = folder / f"test_{config.theme}.png"
            image.save(path)
            log(f"已輸出 {path}")
        in_background(work)

    def run_tests() -> None:
        def work():
            log("執行自動化測試中…")
            env = dict(os.environ, PYTHONIOENCODING="utf-8")
            done = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                cwd=str(PROJECT_ROOT), env=env, capture_output=True, text=True, encoding="utf-8",
                errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            tail = (done.stderr or done.stdout).strip().splitlines()[-12:]
            log("\n".join(tail))
            log("測試通過" if done.returncode == 0 else f"測試失敗(結束代碼 {done.returncode})")
        in_background(work)

    def info() -> None:
        log(f"DeskIsle {__version__},Python {sys.version.split()[0]}")
        log(f"縮放比例 {system.ui_scale():.2f},螢幕 {system.monitor_count()} 個")
        log(f"資料夾 {app_dir()}")
        log(f"監看狀態 {app.watcher.status}")
        log(f"正對桌面 {system.desktop_is_foreground()},忙碌(全螢幕/鎖定){system.user_is_busy()}")
        log(f"介面配色 {'深色' if p.dark else '淺色'}")

    app.section(page, "檢查")
    body = app.card(page, padding=(14, 14))
    tools = (("偵測圖示", detect), ("效能測試", benchmark), ("輸出全尺寸圖", export),
             ("自動化測試", run_tests), ("環境資訊", info), ("清除紀錄", clear))
    for start in (0, 3):
        line = tk.Frame(body, background=p.card)
        line.pack(fill="x", pady=(0 if start == 0 else px(8), 0))
        for text, command in tools[start:start + 3]:
            Button(line, kit, text, command, small=True).pack(side="left", padx=(0, px(8)))

    # ---- 紀錄 --------------------------------------------------------------
    app.section(page, "紀錄")
    log_card = Card(page, kit, padding=(12, 10))
    log_card.pack(fill="x")
    log_box = tk.Text(log_card.body, height=14, wrap="word", state="disabled", relief="flat", borderwidth=0,
                      highlightthickness=0, background=p.card, foreground=p.text, insertbackground=p.text,
                      selectbackground=p.accent, selectforeground=p.on_accent, font=kit.fonts["mono"])
    log_box.pack(fill="both", expand=True)
