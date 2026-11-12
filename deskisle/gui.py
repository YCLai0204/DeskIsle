"""設定介面(tkinter)。

- 「外觀」「運作」兩頁可以調整大部分設定,右邊是即時預覽。
- 以原始碼執行時多一頁「測試」(見 gui_dev.py);打包後的執行檔沒有這一頁。
- 關閉視窗時縮到系統匣,監看繼續在背景執行。

省資源:介面本身不做任何輪詢。預覽只在視窗看得見、而且設定有變時才重畫
(畫的是縮小版,約幾十毫秒);背景工作完成後才通知介面更新。
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import random
import sys
import threading
import time
import tkinter as tk
import traceback
from dataclasses import replace
from tkinter import messagebox, ttk
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from . import APP_NAME, __version__, autostart, is_frozen, tray, wallpaper, winapi
from . import screens as screen_api
from .config import Config, app_dir, load_config, save_config
from .icons import read_layout
from .layout import DesktopLayout, Screen
from .themes import THEMES, get_theme
from .watcher import Watcher, WatchStatus, apply_layout, look_key, render_screen

INSTANCE_NAME = "DeskIsle.Instance"
SHOW_SIGNAL = "DeskIsle.Show"
PREVIEW_WIDTH = 520
LOOK_FIELDS = ("theme", "seed", "margin", "blend", "roughness", "decorations")
PREVIEW_GAP = (30, 34, 42)        # 預覽中螢幕之間的空隙
PREVIEW_SKIPPED = (62, 68, 80)    # 預覽中「不更新」的螢幕
STATE_TEXT = {"following": "跟隨中", "paused": "暫停中", "error": "發生問題", "stopped": "未啟動"}


def _badge_font(size: int):
    for name in ("segoeuib.ttf", "arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:   # Pillow 10.1 以前
        return ImageFont.load_default()


def render_preview(layout: DesktopLayout, config: Config, width: int, debug: bool = False) -> bytes:
    """把一個排列畫成寬 width 的縮小版,回傳 PNG 位元組。

    多螢幕時每個螢幕左上角標上編號;沒有選要更新的螢幕畫成灰色斜線。
    """
    ratio = width / layout.width
    height = max(1, int(round(layout.height * ratio)))
    screens = layout.screen_list()
    if len(screens) == 1:
        image = render_screen(layout, config, 0, ratio, debug)
    else:
        chosen = set(layout.selected_screens(config.screens))
        image = Image.new("RGB", (width, height), PREVIEW_GAP)
        draw = ImageDraw.Draw(image)
        badge = max(14, int(18 * winapi.ui_scale()))
        font = _badge_font(int(badge * 0.62))
        for number, screen in enumerate(screens, 1):
            box = (int(round(screen.left * ratio)), int(round(screen.top * ratio)),
                   int(round(screen.right * ratio)) - 1, int(round(screen.bottom * ratio)) - 1)
            if screen in chosen:
                image.paste(render_screen(layout, config, number - 1, ratio, debug), box[:2])
            else:
                w, h = box[2] - box[0] + 1, box[3] - box[1] + 1
                tile = Image.new("RGB", (w, h), PREVIEW_SKIPPED)
                hatch = ImageDraw.Draw(tile)
                for x in range(-h, w, 10):          # 斜線(超出範圍的部分會自動裁掉)
                    hatch.line((x, h, x + h, 0), fill=PREVIEW_GAP, width=2)
                image.paste(tile, box[:2])
            draw.rectangle(box, outline=PREVIEW_GAP)
            x, y = box[0] + 6, box[1] + 6
            draw.ellipse((x, y, x + badge, y + badge), fill=(255, 255, 255), outline=PREVIEW_GAP)
            draw.text((x + badge / 2, y + badge / 2), str(number), fill=(30, 34, 42), font=font, anchor="mm")
    buffer = io.BytesIO()
    image.save(buffer, "PNG", compress_level=1)
    return buffer.getvalue()


def log_error(text: str) -> None:
    """把錯誤記到檔案(打包後沒有主控台可以看)。"""
    try:
        folder = app_dir()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "deskisle.log"
        if path.exists() and path.stat().st_size > 200_000:
            path.unlink()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
    except OSError:
        pass


class App:
    def __init__(self, root: tk.Tk, start_hidden: bool = False, headless: bool = False):
        self.root = root
        self.headless = headless      # 自我檢查用:不啟動監看、不建系統匣、不寫入任何設定
        self.startup_warning = ""
        try:
            config, warnings = load_config()
            self.startup_warning = ";".join(warnings)
        except ValueError as exc:
            config, self.startup_warning = Config(), f"{exc}(已改用預設值)"
        self.applied = config          # 已生效的設定;監看器讀的是這一份
        self.layout_override: Optional[DesktopLayout] = None   # 測試頁用:假的圖示排列
        self.debug_preview = False                              # 測試頁用:預覽加上圖示外框
        self._preview_job = None
        self._preview_busy = False
        self._preview_dirty = False
        self._photo = None
        self._busy_applying = False
        self._visible = False
        self._quitting = False
        self.tray: Optional[tray.Tray] = None
        self.watcher = Watcher(lambda: self.applied, self._on_watch_status, self._on_reseed)

        root.title(f"{APP_NAME} 桌島")
        root.protocol("WM_DELETE_WINDOW", self.hide)
        root.report_callback_exception = self._on_callback_error
        try:
            self._icon_image = tk.PhotoImage(data=self._png_b64(tray.make_icon(64)))
            root.iconphoto(True, self._icon_image)
        except tk.TclError:
            pass

        self._build_ui()
        self._load_controls(config)
        self.set_status("調整外觀後按「套用到桌布」;要讓桌布自動跟著圖示變化,到「運作」頁開啟自動跟隨。")
        root.bind("<Map>", self._on_map)
        root.bind("<Unmap>", self._on_unmap)

        if headless:
            return
        if tray.available():
            try:
                self.tray = tray.Tray(
                    on_show=lambda: self._ui(self.show),
                    on_toggle_follow=lambda: self._ui(self._toggle_follow_from_tray),
                    is_following=lambda: self.applied.follow,
                    on_quit=lambda: self._ui(self.quit),
                )
                self.tray.start()
            except Exception as exc:
                log_error(f"系統匣啟動失敗:{exc}")
                self.tray = None
        self._listen_for_second_instance()
        if config.follow:
            self.watcher.start()
        if start_hidden:
            self.hide(first_time=False)
        if self.startup_warning:
            self.set_status(self.startup_warning)

    # ------------------------------------------------------------------ 介面
    @staticmethod
    def _png_b64(image) -> bytes:
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        return base64.b64encode(buffer.getvalue())

    def _build_ui(self) -> None:
        root = self.root
        self.preview_width = int(min(900, PREVIEW_WIDTH * winapi.ui_scale()))
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)

        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=0, column=0, sticky="nsew", padx=(10, 6), pady=10)
        self._build_look_page()
        self._build_behavior_page()
        self.has_test_page = False
        if not is_frozen():
            # 測試頁只存在於原始碼版本;打包時這個模組會被排除
            try:
                from . import gui_dev
                gui_dev.add_test_page(self, self.notebook)
                self.has_test_page = True
            except ImportError:
                pass

        right = ttk.Frame(root)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 10), pady=10)
        right.columnconfigure(0, weight=1)
        ttk.Label(right, text="預覽(依照你目前的桌面圖示位置)").grid(row=0, column=0, sticky="w")
        self.preview_label = ttk.Label(right, anchor="center", relief="sunken", text="正在產生預覽…")
        self.preview_label.grid(row=1, column=0, sticky="nsew", pady=(4, 6))
        right.rowconfigure(1, weight=1)
        self.pending_label = ttk.Label(right, text="", foreground="#b06000")
        self.pending_label.grid(row=2, column=0, sticky="w")

        buttons = ttk.Frame(right)
        buttons.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.apply_button = ttk.Button(buttons, text="套用到桌布", command=self.apply_now)
        self.apply_button.pack(side="left")
        ttk.Button(buttons, text="還原原本桌布", command=self.restore_wallpaper).pack(side="left", padx=8)
        ttk.Button(buttons, text="結束程式", command=self.quit).pack(side="right")

        self.status_var = tk.StringVar(value="")
        ttk.Label(root, textvariable=self.status_var, relief="sunken", anchor="w", padding=(6, 2)).grid(
            row=1, column=0, columnspan=2, sticky="ew")

    def _slider(self, parent, row: int, label: str, variable, low: float, high: float,
                fmt: str, command, hint: str = "") -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=(8, 0))
        value_label = ttk.Label(parent, width=7, anchor="e")
        value_label.grid(row=row, column=2, sticky="e", pady=(8, 0))

        def changed(_value=None):
            value_label.configure(text=fmt.format(variable.get()))
            if _value is not None:
                command()

        ttk.Scale(parent, from_=low, to=high, variable=variable, command=changed).grid(
            row=row, column=1, sticky="ew", padx=8, pady=(8, 0))
        self._value_refreshers.append(changed)
        if hint:
            ttk.Label(parent, text=hint, foreground="#666666").grid(
                row=row + 1, column=0, columnspan=3, sticky="w")

    def _build_look_page(self) -> None:
        self._value_refreshers = []
        page = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(page, text="外觀")
        page.columnconfigure(1, weight=1)

        self.var_theme = tk.StringVar()
        self._theme_names = {f"{t.label}({t.key})": t.key for t in THEMES.values()}
        ttk.Label(page, text="主題").grid(row=0, column=0, sticky="w")
        self.theme_box = ttk.Combobox(page, textvariable=self.var_theme, state="readonly",
                                      values=list(self._theme_names), width=22)
        self.theme_box.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(8, 0))
        self.theme_box.bind("<<ComboboxSelected>>", lambda _e: self._look_changed())
        self.theme_hint = ttk.Label(page, text="", foreground="#666666", wraplength=330, justify="left")
        self.theme_hint.grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 0))

        self.var_seed = tk.IntVar()
        ttk.Label(page, text="海岸線形狀").grid(row=2, column=0, sticky="w", pady=(10, 0))
        seed_row = ttk.Frame(page)
        seed_row.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=(10, 0))
        seed_box = ttk.Spinbox(seed_row, from_=0, to=99999, textvariable=self.var_seed, width=8,
                               command=self._look_changed)
        seed_box.pack(side="left")
        seed_box.bind("<Return>", lambda _e: self._look_changed())
        seed_box.bind("<FocusOut>", lambda _e: self._look_changed())
        ttk.Button(seed_row, text="換一個", command=self._random_seed).pack(side="left", padx=8)

        self.var_margin = tk.DoubleVar()
        self.var_blend = tk.DoubleVar()
        self.var_roughness = tk.DoubleVar()
        self.var_decor = tk.DoubleVar()
        self._slider(page, 3, "陸地留白", self.var_margin, 20, 110, "{:.0f}", self._look_changed,
                     "圖示外圍保留多寬的陸地")
        self._slider(page, 5, "融合程度", self.var_blend, 8, 70, "{:.0f}", self._look_changed,
                     "越大,相鄰的圖示越容易連成一片")
        self._slider(page, 7, "海岸起伏", self.var_roughness, 0, 80, "{:.0f}", self._look_changed,
                     "海岸線的不規則程度(不會讓圖示掉進水裡)")
        self._slider(page, 9, "裝飾物數量", self.var_decor, 0, 2, "{:.1f}", self._look_changed,
                     "0 = 不放裝飾物,1 = 標準,2 = 兩倍")
        ttk.Button(page, text="恢復預設外觀", command=self._reset_look).grid(
            row=11, column=0, columnspan=3, sticky="w", pady=(16, 0))

        self.screen_box = ttk.LabelFrame(page, text="要更新的螢幕", padding=8)
        self.screen_box.grid(row=12, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        self._screens: Tuple[Screen, ...] = ()
        self._screen_vars = {}
        self._screen_choice: Tuple[str, ...] = self.applied.screens
        self._set_screens(self._current_screens())

    # ---------------------------------------------------------------- 螢幕選擇
    @staticmethod
    def _current_screens() -> Tuple[Screen, ...]:
        try:
            vx, vy, _w, _h = winapi.virtual_screen()
            return screen_api.list_screens(vx, vy)
        except OSError:
            return ()

    def _set_screens(self, screens: Tuple[Screen, ...]) -> None:
        """依目前接著的螢幕重建勾選框(螢幕沒變就不動)。"""
        if screens == self._screens and self.screen_box.winfo_children():
            return
        self._screens = screens
        for child in self.screen_box.winfo_children():
            child.destroy()
        self._screen_vars = {}
        choosable = DesktopLayout(1, 1, (), screens=screens).can_choose_screens()
        for number, screen in enumerate(screens, 1):
            var = tk.BooleanVar(value=True)
            box = ttk.Checkbutton(self.screen_box, text=screen.describe(number), variable=var,
                                  command=self._screens_toggled)
            box.grid(row=number - 1, column=0, sticky="w")
            box._var = var   # 沒有放進 _screen_vars 的也要留住,勾選狀態才不會消失
            if choosable:
                self._screen_vars[screen.id] = var
            else:
                box.state(["disabled"])
        if len(screens) <= 1:
            hint = "只有一個螢幕。"
        elif choosable:
            hint = "可以只更新部分螢幕(直向、橫向都可以),沒勾選的螢幕維持原本的桌布。"
        else:
            hint = "這台電腦無法各自設定每個螢幕,會把所有螢幕畫成一張圖。"
        ttk.Label(self.screen_box, text=hint, foreground="#666666", wraplength=320, justify="left").grid(
            row=len(screens), column=0, sticky="w", pady=(4, 0))
        self._sync_screen_vars()

    def _sync_screen_vars(self) -> None:
        """把 _screen_choice 反映到勾選框。"""
        wanted = set(self._screen_choice)
        present = [i for i in self._screen_vars if i in wanted]
        for screen_id, var in self._screen_vars.items():
            var.set(not present or screen_id in wanted)

    def _screens_toggled(self) -> None:
        checked = [i for i, var in self._screen_vars.items() if var.get()]
        if not checked:
            # 至少要留一個螢幕
            self._sync_screen_vars()
            self.set_status("至少要選一個螢幕。")
            return
        missing = tuple(i for i in self._screen_choice if i not in self._screen_vars)  # 目前沒接上的螢幕
        everything = len(checked) == len(self._screen_vars)
        self._screen_choice = () if everything and not missing else tuple(checked) + missing
        self._look_changed()

    def _build_behavior_page(self) -> None:
        page = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(page, text="運作")
        page.columnconfigure(1, weight=1)

        self.var_follow = tk.BooleanVar()
        self.var_pause = tk.BooleanVar()
        self.var_autostart = tk.BooleanVar()
        self.var_reseed = tk.BooleanVar()
        self.var_poll = tk.DoubleVar()
        self.var_idle = tk.DoubleVar()
        self.var_debounce = tk.DoubleVar()

        ttk.Checkbutton(page, text="自動跟隨桌面圖示(圖示移動後自動重畫桌布)",
                        variable=self.var_follow, command=self._follow_toggled).grid(
            row=0, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(page, text="圖示移動後換一種海岸線形狀(每次都不一樣)",
                        variable=self.var_reseed, command=self._behavior_changed).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Checkbutton(page, text="全螢幕程式執行或螢幕鎖定時暫停",
                        variable=self.var_pause, command=self._behavior_changed).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Checkbutton(page, text="開機時自動啟動(縮在系統匣)",
                        variable=self.var_autostart, command=self._autostart_toggled).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))

        ttk.Separator(page).grid(row=4, column=0, columnspan=3, sticky="ew", pady=12)
        self._slider(page, 5, "檢查間隔", self.var_poll, 0.5, 5, "{:.1f} 秒", self._behavior_changed,
                     "你正對著桌面時,多久檢查一次圖示位置")
        self._slider(page, 7, "背景檢查間隔", self.var_idle, 1, 30, "{:.0f} 秒", self._behavior_changed,
                     "你在用其他視窗時,多久檢查一次")
        self._slider(page, 9, "穩定等待", self.var_debounce, 0.2, 3, "{:.1f} 秒", self._behavior_changed,
                     "圖示停止移動多久後才重畫")
        ttk.Label(
            page, foreground="#666666", wraplength=330, justify="left",
            text="間隔越長越省電。桌布是靜態圖片,平常不使用顯示卡;"
                 "只有圖示排列改變時才會花約半秒重畫一次。",
        ).grid(row=11, column=0, columnspan=3, sticky="w", pady=(14, 0))

    # ---------------------------------------------------------------- 設定值
    def _load_controls(self, config: Config) -> None:
        for name, key in self._theme_names.items():
            if key == config.theme:
                self.var_theme.set(name)
        self.var_seed.set(config.seed)
        self.var_margin.set(config.margin)
        self.var_blend.set(config.blend)
        self.var_roughness.set(config.roughness)
        self.var_decor.set(config.decorations)
        self.var_follow.set(config.follow)
        if hasattr(self, "_screen_vars"):
            self._screen_choice = config.screens
            self._sync_screen_vars()
        self.var_pause.set(config.pause_when_busy)
        self.var_reseed.set(config.reseed_on_move)
        self.var_poll.set(config.poll_interval)
        self.var_idle.set(config.idle_interval)
        self.var_debounce.set(config.debounce)
        try:
            self.var_autostart.set(autostart.is_enabled())
        except OSError:
            self.var_autostart.set(False)
        self._refresh_labels()

    def _refresh_labels(self) -> None:
        for refresh in self._value_refreshers:
            refresh()
        self.theme_hint.configure(text=get_theme(self._theme_key()).description)

    def _theme_key(self) -> str:
        return self._theme_names.get(self.var_theme.get(), self.applied.theme)

    def _seed_value(self) -> int:
        try:
            return max(0, min(99999, int(self.var_seed.get())))
        except (tk.TclError, ValueError):
            return self.applied.seed

    def draft_config(self) -> Config:
        """介面上目前的設定(外觀部分可能還沒套用)。"""
        return Config(
            theme=self._theme_key(),
            seed=self._seed_value(),
            margin=float(round(self.var_margin.get())),
            blend=float(round(self.var_blend.get())),
            roughness=float(round(self.var_roughness.get())),
            decorations=round(self.var_decor.get(), 1),
            follow=bool(self.var_follow.get()),
            poll_interval=round(self.var_poll.get(), 1),
            idle_interval=float(round(self.var_idle.get())),
            debounce=round(self.var_debounce.get(), 1),
            pause_when_busy=bool(self.var_pause.get()),
            reseed_on_move=bool(self.var_reseed.get()),
            screens=self._screen_choice,
        ).validate()

    def _save(self) -> None:
        if self.headless:
            return
        try:
            save_config(self.applied)
        except OSError as exc:
            self.set_status(f"設定無法儲存:{exc}")

    # ---------------------------------------------------------------- 外觀頁
    def _look_changed(self) -> None:
        self._refresh_labels()
        self._update_pending()
        self.schedule_preview()

    def _update_pending(self) -> None:
        differs = look_key(self.draft_config()) != look_key(self.applied)
        self.pending_label.configure(text="預覽中的外觀尚未套用到桌布" if differs else "")

    def _random_seed(self) -> None:
        self.var_seed.set(random.randrange(0, 100000))
        self._look_changed()

    def _reset_look(self) -> None:
        defaults = Config()
        self._load_controls(replace(self.draft_config(), **{f: getattr(defaults, f) for f in LOOK_FIELDS}))
        self._look_changed()

    # ---------------------------------------------------------------- 運作頁
    def _behavior_changed(self) -> None:
        """運作相關的設定改了就立刻生效並儲存(外觀維持已套用的那一份)。"""
        draft = self.draft_config()
        self.applied = replace(
            self.applied, follow=draft.follow, poll_interval=draft.poll_interval,
            idle_interval=draft.idle_interval, debounce=draft.debounce,
            pause_when_busy=draft.pause_when_busy, reseed_on_move=draft.reseed_on_move,
        )
        self._save()

    def _follow_toggled(self) -> None:
        if self.var_follow.get():
            # 開始跟隨:用畫面上看到的外觀
            self.applied = self.draft_config()
            self._save()
            self._update_pending()
            if not self.headless:
                self.watcher.start()
        else:
            self._behavior_changed()
            self.watcher.stop(wait=False)
            self.set_status("已停止跟隨。桌布會維持現在的樣子。")
        if self.tray:
            self.tray.refresh()

    def _toggle_follow_from_tray(self) -> None:
        self.var_follow.set(not self.var_follow.get())
        self._follow_toggled()

    def _autostart_toggled(self) -> None:
        if self.headless:
            return
        try:
            if self.var_autostart.get():
                autostart.enable()
            else:
                autostart.disable()
        except OSError as exc:
            self.var_autostart.set(not self.var_autostart.get())
            messagebox.showerror(APP_NAME, f"無法變更開機啟動設定:\n{exc}", parent=self.root)

    # ------------------------------------------------------------- 套用/還原
    def apply_now(self) -> None:
        """把畫面上的設定存檔並套用到桌布。"""
        if self.headless or self._busy_applying:
            return
        self.applied = self.draft_config()
        self._save()
        self._update_pending()
        if self.watcher.running:
            self.watcher.refresh()
            return
        self._busy_applying = True
        self.apply_button.state(["disabled"])
        self.set_status("正在繪製桌布…")
        config = self.applied

        def work():
            winapi.lower_thread_priority()
            try:
                started = time.perf_counter()
                layout = read_layout(names=False)
                apply_layout(layout, config)
                message = (f"已套用桌布:{len(layout.icons)} 個圖示,"
                           f"{time.perf_counter() - started:.2f} 秒")
            except Exception as exc:
                log_error(traceback.format_exc())
                message = f"套用失敗:{exc}"
            finally:
                winapi.trim_memory()
            self._ui(self._apply_finished, message)

        threading.Thread(target=work, name="deskisle-apply", daemon=True).start()

    def _apply_finished(self, message: str) -> None:
        self._busy_applying = False
        self.apply_button.state(["!disabled"])
        self.set_status(message)

    def restore_wallpaper(self) -> None:
        if self.headless:
            return
        if self.var_follow.get():
            self.var_follow.set(False)
            self._follow_toggled()
        try:
            state = wallpaper.restore()
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"還原失敗:\n{exc}", parent=self.root)
            return
        if state is None:
            messagebox.showinfo(APP_NAME, "沒有備份可還原(還沒套用過,或已經還原過了)。", parent=self.root)
            return
        text = "已還原原本的桌布。"
        if state.kind in (2, 3):
            kind = wallpaper.BACKGROUND_KINDS[state.kind]
            text += (f"\n\n原本的背景類型是「{kind}」。圖片已還原,但自動更換功能需要到\n"
                     f"設定 → 個人化 → 背景 重新選一次「{kind}」。")
        self.set_status("已還原原本的桌布。")
        messagebox.showinfo(APP_NAME, text, parent=self.root)

    # ------------------------------------------------------------------ 預覽
    def schedule_preview(self, delay_ms: int = 120) -> None:
        if not self._visible:
            return  # 視窗沒顯示就不畫
        if self._preview_job is not None:
            self.root.after_cancel(self._preview_job)
        self._preview_job = self.root.after(delay_ms, self._start_preview)

    def _start_preview(self) -> None:
        self._preview_job = None
        if self._preview_busy:
            self._preview_dirty = True
            return
        self._preview_busy = True
        args = (self.draft_config(), self.layout_override, self.debug_preview, self.preview_width)
        threading.Thread(target=self._preview_worker, args=args, name="deskisle-preview",
                         daemon=True).start()

    def _preview_worker(self, config, override, debug, width) -> None:
        try:
            layout = override or read_layout(names=False)
            data = render_preview(layout, config, width, debug)
            self._ui(self._preview_done, data, "", None if override else layout.screens)
        except Exception as exc:
            self._ui(self._preview_done, None, str(exc))

    def _preview_done(self, data: Optional[bytes], error: str, screens=None) -> None:
        self._preview_busy = False
        if screens is not None and screens != self._screens:
            self._set_screens(screens)   # 螢幕接上或拔掉了
        if data is not None:
            self._photo = tk.PhotoImage(data=base64.b64encode(data))
            self.preview_label.configure(image=self._photo, text="")
        else:
            self.preview_label.configure(image="", text=f"無法產生預覽:\n{error}")
        if self._preview_dirty:
            self._preview_dirty = False
            self.schedule_preview(10)

    # ------------------------------------------------------------ 視窗與狀態
    def _ui(self, function, *args) -> None:
        """從其他執行緒安排一件事到介面執行緒去做。"""
        if self._quitting:
            return
        try:
            self.root.after(0, function, *args)
        except (RuntimeError, tk.TclError):
            pass  # 介面已經關閉

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _on_watch_status(self, status: WatchStatus) -> None:
        self._ui(self._show_watch_status, status)

    def _on_reseed(self, seed: int) -> None:
        """監看器因為圖示移動換了種子(在監看執行緒呼叫)。"""
        old = self.applied.seed
        self.applied = replace(self.applied, seed=seed)   # 立刻生效,下一輪監看就讀得到
        self._ui(self._show_reseed, old, seed)

    def _show_reseed(self, old: int, seed: int) -> None:
        # 使用者沒有正在改種子的話,介面上的種子也跟著換,預覽才會跟桌布一樣
        if self._seed_value() == old:
            self.var_seed.set(seed)
            self._look_changed()
        self._save()

    def _show_watch_status(self, status: WatchStatus) -> None:
        parts = [STATE_TEXT.get(status.state, status.state)]
        if status.message:
            parts.append(status.message)
        if status.state != "stopped":
            parts.append(f"{status.icons} 個圖示")
            if status.updated_at:
                parts.append(f"上次更新 {status.updated_at}({status.seconds:.2f} 秒)")
        self.set_status(" · ".join(parts))

    def _on_map(self, event) -> None:
        if event.widget is self.root and not self._visible:
            self._visible = True
            self.schedule_preview(30)

    def _on_unmap(self, event) -> None:
        if event.widget is self.root:
            self._visible = False

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

    def hide(self, first_time: bool = True) -> None:
        """關閉視窗 = 縮到系統匣(沒有系統匣時縮到工作列),監看照常進行。"""
        if self.headless:
            return
        if self.tray:
            self.root.withdraw()
            if first_time and not getattr(self, "_told_about_tray", False):
                self._told_about_tray = True
                self.tray.notify("DeskIsle 仍在系統匣中運作。在圖示上按右鍵可以結束。")
        else:
            self.root.iconify()

    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self.watcher.stop(wait=False)
        if self.tray:
            self.tray.stop()
        self.root.destroy()

    def _listen_for_second_instance(self) -> None:
        """再次啟動程式時,由已經在執行的這一個把視窗叫出來。"""
        handle = winapi.create_signal(SHOW_SIGNAL)
        if not handle:
            return

        def wait():
            while not self._quitting:
                if not winapi.wait_signal(handle):
                    break   # 等待失敗就放棄,不能空轉
                self._ui(self.show)

        threading.Thread(target=wait, name="deskisle-signal", daemon=True).start()

    def _on_callback_error(self, exc_type, exc, tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log_error(text)
        self.set_status(f"發生錯誤:{exc}")
        if not is_frozen() and sys.stderr is not None:
            sys.stderr.write(text)


# ---------------------------------------------------------------------------
def selftest(output: str) -> int:
    """不開視窗、不動桌布的自我檢查,結果寫成 JSON。用來確認打包後的執行檔能運作。"""
    result = {"ok": False, "frozen": is_frozen(), "version": __version__}
    try:
        layout = read_layout()
        result["icons"] = len(layout.icons)
        result["screen"] = [layout.width, layout.height]
        timings = {}
        for key in THEMES:
            started = time.perf_counter()
            data = render_preview(layout, Config(theme=key), 480)
            assert data[:8] == b"\x89PNG\r\n\x1a\n"
            timings[key] = round((time.perf_counter() - started) * 1000)
        result["preview_ms"] = timings
        result["tray_available"] = tray.available()

        root = tk.Tk()
        root.withdraw()
        app = App(root, headless=True)
        root.update_idletasks()
        result["pages"] = [app.notebook.tab(i, "text") for i in range(app.notebook.index("end"))]
        result["has_test_page"] = app.has_test_page
        root.destroy()
        result["ok"] = True
    except Exception:
        result["error"] = traceback.format_exc()
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    return 0 if result["ok"] else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog=APP_NAME, add_help=False)
    parser.add_argument("--minimized", action="store_true")
    parser.add_argument("--selftest", metavar="FILE")
    args, _unknown = parser.parse_known_args(argv)

    winapi.enable_dpi_awareness()
    if args.selftest:
        return selftest(args.selftest)

    if not winapi.acquire_single_instance(INSTANCE_NAME):
        winapi.send_signal(SHOW_SIGNAL)   # 已經在執行 → 請它把視窗叫出來
        return 0

    root = tk.Tk()
    App(root, start_hidden=args.minimized)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
