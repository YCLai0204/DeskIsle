"""設定視窗。

版面:
- 左邊是導覽列:外觀、螢幕、運作(以原始碼執行時多一頁「測試」,見 ui/dev.py),
  下方是「自動跟隨」開關與目前狀態。
- 中間是目前這一頁的設定(可以捲動)。
- 右邊是即時預覽、「套用到桌布」與狀態訊息。

配色跟著系統的淺色/深色模式;環境變數 DESKISLE_APPEARANCE=light 或 dark 可以強制指定。
關閉視窗時縮到系統匣,監看繼續在背景執行。

省資源:介面本身不做任何輪詢。預覽只在視窗看得見、而且設定有變時才重畫
(畫的是縮小版,約幾十毫秒);背景工作完成後才通知介面更新。
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import random
import sys
import threading
import time
import tkinter as tk
import traceback
from dataclasses import replace
from tkinter import messagebox
from typing import Dict, List, Optional, Tuple

from .. import APP_NAME, __version__, is_frozen, system
from ..config import Config, app_dir, load_config, save_config
from ..engine.layout import DesktopLayout, Screen
from ..engine.themes import THEMES, get_theme
from ..system import autostart, read_layout, wallpaper
from ..watcher import Watcher, WatchStatus, apply_layout, look_key
from . import style, tray
from .preview import fit_width, render_preview, render_preview_image
from .widgets import (Button, Card, Divider, Kit, NavItem, Pill, ScreenTile, ScrollArea, Slider, ThemeTile,
                      Toggle, label, to_photo)

INSTANCE_NAME = "DeskIsle.Instance"
SHOW_SIGNAL = "DeskIsle.Show"
LOOK_FIELDS = ("theme", "seed", "margin", "blend", "roughness", "decorations")
STATE_TEXT = {"following": "跟隨中", "paused": "暫停中", "error": "發生問題", "stopped": "未啟動"}

# 版面尺寸(以 100% 縮放為準)
SIDEBAR_WIDTH = 212
SETTINGS_WIDTH = 408
PREVIEW_SIZE = (480, 300)
TEXT_WRAP = SETTINGS_WIDTH - 40


def choose_palette() -> style.Palette:
    forced = os.environ.get("DESKISLE_APPEARANCE", "").strip().lower()
    if forced in ("light", "dark"):
        return style.DARK if forced == "dark" else style.LIGHT
    try:
        return style.DARK if system.prefers_dark() else style.LIGHT
    except Exception:
        return style.LIGHT


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
        self._preview_box = (0, 0)
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
            self._icon_image = to_photo(tray.make_icon(64), root)
            root.iconphoto(True, self._icon_image)
        except tk.TclError:
            pass

        self._build_ui()
        self._load_controls(config)
        self.set_status("調整外觀後按「套用到桌布」。要讓桌布自動跟著圖示變化,打開左下角的「自動跟隨」。")
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

    # ================================================================== 版面
    def _build_ui(self) -> None:
        root = self.root
        self._scale = system.ui_scale()
        self.kit = kit = Kit(root, choose_palette(), self._scale)
        p, px = kit.p, kit.px
        root.configure(background=p.bg)
        root.option_add("*Font", kit.fonts["body"])
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)

        # 開關、勾選狀態等變數(兩個地方的開關可以共用同一個變數)
        self.var_theme = tk.StringVar()
        self.var_seed = tk.IntVar()
        self.var_margin, self.var_blend = tk.DoubleVar(), tk.DoubleVar()
        self.var_roughness, self.var_decor = tk.DoubleVar(), tk.DoubleVar()
        self.var_follow, self.var_pause = tk.BooleanVar(), tk.BooleanVar()
        self.var_autostart, self.var_reseed = tk.BooleanVar(), tk.BooleanVar()
        self.var_poll, self.var_idle, self.var_debounce = tk.DoubleVar(), tk.DoubleVar(), tk.DoubleVar()

        self._build_sidebar()

        content = tk.Frame(root, background=p.bg)
        content.grid(row=0, column=1, sticky="nsew", padx=(px(32), px(24)), pady=(px(24), px(22)))
        content.columnconfigure(1, weight=1)
        content.rowconfigure(1, weight=1)

        head = tk.Frame(content, background=p.bg)
        head.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, px(16)))
        self.page_title = label(head, kit, font="title")
        self.page_title.pack(anchor="w")
        self.page_subtitle = label(head, kit, color=p.muted)
        self.page_subtitle.pack(anchor="w", pady=(px(2), 0))

        self.scroll = ScrollArea(content, kit, width=px(SETTINGS_WIDTH))
        self.scroll.grid(row=1, column=0, sticky="ns")
        self._build_preview(content)

        self.pages: Dict[str, tk.Frame] = {}
        self._subtitles: Dict[str, str] = {}
        self._nav: Dict[str, NavItem] = {}
        self.current_page = ""
        self._build_look_page()
        self._build_screens_page()
        self._build_behavior_page()
        self.has_test_page = False
        if not is_frozen():
            # 測試頁只存在於原始碼版本;打包時這個模組會被排除
            try:
                from . import dev
                dev.add_test_page(self)
                self.has_test_page = True
            except ImportError:
                pass
        self.show_page("外觀")

        root.update_idletasks()
        want_w = px(SIDEBAR_WIDTH + 32 + SETTINGS_WIDTH + 12 + 22 + PREVIEW_SIZE[0] + 44 + 24)
        want_h = px(740)
        width = min(want_w, int(root.winfo_screenwidth() * 0.94))
        height = min(want_h, int(root.winfo_screenheight() * 0.86))
        root.geometry(f"{width}x{height}")
        root.minsize(min(width, px(SIDEBAR_WIDTH + SETTINGS_WIDTH + 400)), min(height, px(560)))
        try:
            system.style_title_bar(root.winfo_id(), p.dark, p.bg, p.text)
        except Exception:
            pass

    def _build_sidebar(self) -> None:
        kit = self.kit
        p, px = kit.p, kit.px
        side = tk.Frame(self.root, background=p.sidebar, width=px(SIDEBAR_WIDTH))
        side.grid(row=0, column=0, sticky="ns")
        side.pack_propagate(False)

        brand = tk.Frame(side, background=p.sidebar)
        brand.pack(fill="x", padx=px(20), pady=(px(24), px(22)))
        self._brand_icon = to_photo(tray.make_icon(px(38)), self.root)
        tk.Label(brand, image=self._brand_icon, background=p.sidebar, borderwidth=0).pack(side="left")
        names = tk.Frame(brand, background=p.sidebar)
        names.pack(side="left", padx=(px(12), 0))
        label(names, kit, "DeskIsle", font="brand").pack(anchor="w")
        label(names, kit, "桌島 · 你的檔案就是島嶼", font="small", color=p.muted).pack(anchor="w")

        self.nav_box = tk.Frame(side, background=p.sidebar)
        self.nav_box.pack(fill="x", padx=px(12))

        bottom = tk.Frame(side, background=p.sidebar)
        bottom.pack(side="bottom", fill="x", padx=px(12), pady=(0, px(14)))
        card = Card(bottom, kit, padding=(14, 12), radius=10)
        card.pack(fill="x")
        body = card.body
        body.columnconfigure(0, weight=1)
        label(body, kit, "自動跟隨", font="bold").grid(row=0, column=0, sticky="w")
        Toggle(body, kit, self.var_follow, self._follow_toggled).grid(row=0, column=1, sticky="e")
        state = tk.Frame(body, background=p.card)
        state.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(px(6), 0))
        self._state_dot = tk.Label(state, background=p.card, borderwidth=0)
        self._state_dot.pack(side="left")
        self._state_text = label(state, kit, font="caption", color=p.muted)
        self._state_text.pack(side="left", padx=(px(6), 0))

        footer = tk.Frame(bottom, background=p.sidebar)
        footer.pack(fill="x", pady=(px(10), 0))
        label(footer, kit, f"版本 {__version__}", font="small", color=p.subtle).pack(side="left", padx=(px(8), 0))
        Button(footer, kit, "結束程式", self.quit, kind="danger", icon="power", small=True).pack(side="right")

    def _build_preview(self, parent) -> None:
        """右邊的預覽卡片:標題、預覽圖、桌面資訊;按鈕與狀態固定在卡片底部。"""
        kit = self.kit
        p, px = kit.p, kit.px
        card = Card(parent, kit, padding=(22, 20), radius=14)
        card.grid(row=1, column=1, sticky="nsew", padx=(px(12), 0))
        body = self.preview_body = card.body
        body.columnconfigure(0, weight=1)
        body.rowconfigure(4, weight=1)

        head = tk.Frame(body, background=p.card)
        head.grid(row=0, column=0, sticky="ew")
        label(head, kit, "預覽", font="h2").pack(side="left")
        self.pending_pill = Pill(head, kit)
        self.pending_pill.pack(side="right")
        self.preview_caption = label(body, kit, "依照目前桌面圖示的位置繪製;調整設定時即時更新,不會動到桌布。",
                                     font="caption", color=p.muted)
        self.preview_caption.grid(row=1, column=0, sticky="ew", pady=(px(4), 0))

        # 預覽圖:畫布大小跟著圖片,圖片大小跟著卡片裡可用的空間
        self.preview_canvas = tk.Canvas(body, background=p.card, highlightthickness=0, borderwidth=0,
                                        width=px(PREVIEW_SIZE[0]), height=px(PREVIEW_SIZE[1]))
        self.preview_canvas.grid(row=2, column=0, sticky="nw", pady=(px(16), px(10)))
        self.preview_info = label(body, kit, "", font="caption", color=p.muted)
        self.preview_info.grid(row=3, column=0, sticky="ew")

        footer = tk.Frame(body, background=p.card)
        footer.grid(row=5, column=0, sticky="ew", pady=(px(16), 0))
        Divider(footer, kit).pack(fill="x", pady=(0, px(16)))
        buttons = tk.Frame(footer, background=p.card)
        buttons.pack(fill="x")
        self.apply_button = Button(buttons, kit, "套用到桌布", self.apply_now, kind="primary", icon="brush")
        self.apply_button.pack(side="left")
        Button(buttons, kit, "還原原本桌布", self.restore_wallpaper, icon="restore").pack(side="left", padx=(px(10), 0))

        # 狀態訊息固定佔兩行,訊息長短不同時版面才不會跳動
        self.status_var = tk.StringVar(value="")
        self.status_label = label(footer, kit, font="caption", color=p.muted, textvariable=self.status_var,
                                  height=2, anchor="nw")
        self.status_label.pack(fill="x", pady=(px(12), 0))
        self._preview_fixed = (head, self.preview_caption, self.preview_info, footer)
        body.bind("<Configure>", self._preview_area_changed, add="+")

    # ---------------------------------------------------------------- 頁面
    def add_page(self, name: str, icon: str, subtitle: str) -> tk.Frame:
        """新增一頁(左邊導覽列多一項),回傳放內容的 Frame。"""
        frame = tk.Frame(self.scroll.inner, background=self.kit.p.bg)
        self.pages[name] = frame
        self._subtitles[name] = subtitle
        item = NavItem(self.nav_box, self.kit, name, icon, lambda: self.show_page(name))
        item.pack(fill="x", pady=(0, self.kit.px(2)))
        self._nav[name] = item
        return frame

    def page_names(self) -> List[str]:
        return list(self.pages)

    def show_page(self, name: str) -> None:
        for other, frame in self.pages.items():
            if other != name:
                frame.pack_forget()
            self._nav[other].set_selected(other == name)
        self.pages[name].pack(fill="x", anchor="n", padx=(0, self.kit.px(6)))
        self.page_title.configure(text=name)
        self.page_subtitle.configure(text=self._subtitles[name])
        self.current_page = name
        self.scroll.to_top()

    # ------------------------------------------------------------ 共用的版面
    def section(self, page: tk.Frame, title: str, hint: str = "") -> None:
        kit = self.kit
        top = kit.px(22) if page.winfo_children() else 0
        label(page, kit, title, font="h2").pack(fill="x", pady=(top, kit.px(8)))
        if hint:
            label(page, kit, hint, font="caption", color=kit.p.muted, wrap=TEXT_WRAP).pack(
                fill="x", pady=(0, kit.px(10)))

    def card(self, page: tk.Frame, padding=(4, 4)) -> tk.Frame:
        card = Card(page, self.kit, padding=padding)
        card.pack(fill="x")
        return card.body

    def row(self, body: tk.Frame, title: str, hint: str = "") -> Tuple[tk.Frame, tk.Frame]:
        """卡片裡的一列:左邊標題與說明,右邊放控制項(回傳 (這一列, 右邊的空位))。"""
        kit = self.kit
        p, px = kit.p, kit.px
        if body.winfo_children():
            Divider(body, kit).pack(fill="x", padx=px(12))
        line = tk.Frame(body, background=p.card)
        line.pack(fill="x", padx=px(14), pady=px(12))
        line.columnconfigure(0, weight=1)
        label(line, kit, title).grid(row=0, column=0, sticky="w")
        if hint:
            label(line, kit, hint, font="caption", color=p.muted, wrap=TEXT_WRAP - 110).grid(
                row=1, column=0, sticky="w", pady=(px(2), 0))
        slot = tk.Frame(line, background=p.card)
        slot.grid(row=0, column=1, rowspan=2, sticky="e", padx=(px(12), 0))
        return line, slot

    def toggle_row(self, body, title: str, hint: str, variable: tk.BooleanVar, command) -> Toggle:
        _line, slot = self.row(body, title, hint)
        toggle = Toggle(slot, self.kit, variable, command)
        toggle.pack()
        return toggle

    def slider_row(self, body, title: str, hint: str, variable: tk.DoubleVar, low: float, high: float,
                   fmt: str, command) -> None:
        kit = self.kit
        line, slot = self.row(body, title, hint)
        value = label(slot, kit, font="bold", color=kit.p.accent)
        value.pack()

        def refresh(*_args):
            try:
                value.configure(text=fmt.format(variable.get()))
            except (tk.TclError, ValueError):
                pass

        variable.trace_add("write", refresh)
        refresh()
        Slider(line, kit, variable, low, high, command).grid(row=2, column=0, columnspan=2, sticky="ew",
                                                             pady=(kit.px(10), 0))

    # ---------------------------------------------------------------- 外觀頁
    def _build_look_page(self) -> None:
        kit = self.kit
        p, px = kit.p, kit.px
        page = self.add_page("外觀", "look", "挑一個主題,調整海岸線的樣子;右邊的預覽會跟著變。")

        self._theme_names = {f"{t.label}({t.key})": t.key for t in THEMES.values()}
        self.section(page, "主題")
        body = self.card(page, padding=(14, 14))
        grid = tk.Frame(body, background=p.card)
        grid.pack(anchor="w")
        columns, gap = 4, px(4)
        tile_w = (px(SETTINGS_WIDTH) - px(6) - px(28) - gap * (columns - 1)) // columns - px(8)
        size = (tile_w, int(tile_w * 0.62))
        self._theme_tiles: Dict[str, ThemeTile] = {}
        for index, theme in enumerate(THEMES.values()):
            image = style.theme_swatch(theme, size, size[0] / 420)
            tile = ThemeTile(grid, kit, image, theme.label, lambda key=theme.key: self._choose_theme(key))
            tile.grid(row=index // columns, column=index % columns, padx=(0, gap), pady=(0, px(4)))
            self._theme_tiles[theme.key] = tile
        self.theme_hint = label(body, kit, font="caption", color=p.muted, wrap=TEXT_WRAP - 20)
        self.theme_hint.pack(fill="x", padx=px(4), pady=(px(6), 0))

        self.section(page, "海岸線")
        body = self.card(page)
        _line, slot = self.row(body, "形狀編號", "同一個編號會畫出同樣的海岸線")
        field = Card(slot, kit, padding=(10, 5), radius=7, fill=p.field, outline=p.border_strong)
        field.pack(side="left")
        seed_box = tk.Entry(field.body, textvariable=self.var_seed, width=6, relief="flat", borderwidth=0,
                            highlightthickness=0, background=p.field, foreground=p.text,
                            insertbackground=p.text, selectbackground=p.accent, selectforeground=p.on_accent,
                            font=kit.fonts["bold"], justify="center")
        seed_box.pack()
        seed_box.bind("<Return>", lambda _e: self._look_changed())
        seed_box.bind("<FocusOut>", lambda _e: self._look_changed())
        Button(slot, kit, "換一個", self._random_seed, icon="refresh", small=True).pack(side="left", padx=(px(8), 0))
        self.slider_row(body, "陸地留白", "圖示外圍保留多寬的陸地", self.var_margin, 20, 110, "{:.0f}",
                        self._look_changed)
        self.slider_row(body, "融合程度", "越大,相鄰的圖示越容易連成一片", self.var_blend, 8, 70, "{:.0f}",
                        self._look_changed)
        self.slider_row(body, "海岸起伏", "海岸線的不規則程度(不會讓圖示掉進水裡)", self.var_roughness, 0, 80,
                        "{:.0f}", self._look_changed)

        self.section(page, "裝飾物")
        body = self.card(page)
        self.slider_row(body, "數量", "0 = 不放裝飾物,1 = 標準,2 = 兩倍", self.var_decor, 0, 2, "{:.1f}",
                        self._look_changed)

        Button(page, kit, "恢復預設外觀", self._reset_look, icon="restore", small=True).pack(
            anchor="w", pady=(px(18), px(6)))

    def _choose_theme(self, key: str) -> None:
        for name, value in self._theme_names.items():
            if value == key:
                self.var_theme.set(name)
        self._look_changed()

    def _refresh_theme_tiles(self) -> None:
        current = self._theme_key()
        for key, tile in self._theme_tiles.items():
            if tile.selected != (key == current):
                tile.set_selected(key == current)

    # ---------------------------------------------------------------- 螢幕頁
    def _build_screens_page(self) -> None:
        kit = self.kit
        page = self.add_page("螢幕", "screens", "選擇要換桌布的螢幕;沒選的螢幕維持原本的桌布。")
        self.section(page, "要更新的螢幕", "點一下螢幕卡片來選擇或取消,橫向、直向都可以。改完按「套用到桌布」生效。")
        self.screen_box = tk.Frame(page, background=kit.p.bg)
        self.screen_box.pack(fill="x")
        self.screen_hint = label(page, kit, font="caption", color=kit.p.muted, wrap=TEXT_WRAP)
        self.screen_hint.pack(fill="x", pady=(kit.px(12), 0))
        self._screens: Tuple[Screen, ...] = ()
        self._screen_vars: Dict[str, tk.BooleanVar] = {}
        self._screen_choice: Tuple[str, ...] = self.applied.screens
        self._set_screens(self._current_screens())

    @staticmethod
    def _current_screens() -> Tuple[Screen, ...]:
        try:
            return system.list_screens()
        except (OSError, system.IconDetectionError):
            return ()

    def _set_screens(self, screens: Tuple[Screen, ...]) -> None:
        """依目前接著的螢幕重建選擇卡(螢幕沒變就不動)。"""
        if screens == self._screens and self.screen_box.winfo_children():
            return
        kit = self.kit
        px = kit.px
        self._screens = screens
        for child in self.screen_box.winfo_children():
            child.destroy()
        self._screen_vars = {}
        choosable = DesktopLayout(1, 1, (), screens=screens).can_choose_screens()
        gap = px(10)
        width = (px(SETTINGS_WIDTH) - px(6) - gap) // 2
        self._screen_tiles = []
        for number, screen in enumerate(screens, 1):
            var = tk.BooleanVar(value=True)
            tile = ScreenTile(self.screen_box, kit, number, screen, var, self._screens_toggled, width,
                              enabled=choosable)
            tile.grid(row=(number - 1) // 2, column=(number - 1) % 2, sticky="w",
                      padx=(0, gap if number % 2 else 0), pady=(0, gap))
            self._screen_tiles.append(tile)   # 沒有放進 _screen_vars 的也要留住,勾選狀態才不會消失
            if choosable:
                self._screen_vars[screen.id] = var
        if not screens:
            hint = "偵測不到螢幕。"
        elif len(screens) == 1:
            hint = "目前只偵測到一個螢幕。接上更多螢幕後,這裡可以分別選擇。"
        elif choosable:
            #   是不換行空白:tkinter 會優先在一般空白處換行,一行會斷得太早
            hint = "預覽中每個螢幕左上角的編號,就是這裡的「螢幕\u00a0N」;沒選的螢幕在預覽裡是灰色斜線。"
        else:
            hint = "這台電腦無法各自設定每個螢幕,會把所有螢幕畫成一張圖。"
        self.screen_hint.configure(text=hint)
        self._sync_screen_vars()

    def _sync_screen_vars(self) -> None:
        """把 _screen_choice 反映到選擇卡。"""
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

    # ---------------------------------------------------------------- 運作頁
    def _build_behavior_page(self) -> None:
        kit = self.kit
        page = self.add_page("運作", "behavior", "自動更新與省電。這一頁的設定改了立刻生效。")

        self.section(page, "自動更新")
        body = self.card(page)
        self.toggle_row(body, "自動跟隨桌面圖示", "圖示移動後自動重畫桌布", self.var_follow, self._follow_toggled)
        self.toggle_row(body, "每次換一種海岸線", "圖示移動後換一個形狀編號,每次都不一樣",
                        self.var_reseed, self._behavior_changed)
        if sys.platform == "darwin":
            title, hint = "登入時自動啟動", "啟動後縮到 Dock"
        else:
            title, hint = "開機時自動啟動", "啟動後縮在系統匣"
        self.toggle_row(body, title, hint, self.var_autostart, self._autostart_toggled)

        self.section(page, "省電")
        body = self.card(page)
        self.toggle_row(body, "全螢幕或鎖定時暫停", "玩遊戲、看影片或螢幕鎖定時不檢查", self.var_pause,
                        self._behavior_changed)
        self.slider_row(body, "檢查間隔", "你正對著桌面時,多久檢查一次圖示位置", self.var_poll, 0.5, 5,
                        "{:.1f} 秒", self._behavior_changed)
        self.slider_row(body, "背景檢查", "你在用其他視窗時,多久檢查一次", self.var_idle, 1, 30, "{:.0f} 秒",
                        self._behavior_changed)
        self.slider_row(body, "穩定等待", "圖示停止移動多久後才重畫", self.var_debounce, 0.2, 3, "{:.1f} 秒",
                        self._behavior_changed)
        label(page, kit, "間隔越長越省電。桌布是靜態圖片,平常不使用顯示卡;只有圖示排列改變時才會花約半秒重畫一次。",
              font="caption", color=kit.p.muted, wrap=TEXT_WRAP).pack(fill="x", pady=(kit.px(14), kit.px(6)))

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
        self._set_header_state("following" if config.follow else "stopped",
                               "" if config.follow else "未開啟")
        try:
            self.var_autostart.set(autostart.is_enabled())
        except OSError:
            self.var_autostart.set(False)
        self._refresh_labels()

    def _refresh_labels(self) -> None:
        self.theme_hint.configure(text=get_theme(self._theme_key()).description)
        self._refresh_theme_tiles()

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
        p = self.kit.p
        self.pending_pill.show("尚未套用" if differs else "", p.warn, p.warn_soft)

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
            self._set_header_state("following", "啟動中…")
            if not self.headless:
                self.watcher.start()
        else:
            self._behavior_changed()
            self.watcher.stop(wait=False)
            self._set_header_state("stopped", "未開啟")
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
        self.apply_button.set_enabled(False)
        self.set_status("正在繪製桌布…")
        config = self.applied

        def work():
            system.lower_thread_priority()
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
                system.trim_memory()
            self._ui(self._apply_finished, message)

        threading.Thread(target=work, name="deskisle-apply", daemon=True).start()

    def _apply_finished(self, message: str) -> None:
        self._busy_applying = False
        self.apply_button.set_enabled(True)
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
    def _preview_area_changed(self, event) -> None:
        """卡片大小改變:重新計算預覽圖可用的空間,差很多才重畫。"""
        width = max(100, event.width)
        self.status_label.configure(wraplength=width)
        self.preview_caption.configure(wraplength=width)
        self.root.after_idle(self._measure_preview_box)

    def _measure_preview_box(self) -> None:
        px = self.kit.px
        body = self.preview_body
        used = sum(widget.winfo_reqheight() for widget in self._preview_fixed) + px(16 + 10 + 16 + 24)
        box = (max(px(120), body.winfo_width()), max(px(90), body.winfo_height() - used))
        old_w, old_h = self._preview_box
        self._preview_box = box
        if self._photo is None:
            self._draw_preview_placeholder("正在產生預覽…")
        if abs(box[0] - old_w) > 6 or abs(box[1] - old_h) > 6:
            self.schedule_preview(160)

    def _draw_preview_placeholder(self, text: str) -> None:
        kit = self.kit
        canvas = self.preview_canvas
        width, height = self._preview_box
        if width < 20 or height < 20:
            return
        height = min(height, int(width * 9 / 16))
        canvas.configure(width=width, height=height)
        canvas.delete("all")
        kit.draw_box(canvas, 0, 0, width, height, kit.px(12), kit.p.preview_bg)
        canvas.create_text(width / 2, height / 2, text=text, fill=kit.p.muted, font=kit.fonts["caption"],
                           width=width - kit.px(40), justify="center")

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
        width, height = self._preview_box
        if width < 20 or height < 20:
            return
        self._preview_busy = True
        args = (self.draft_config(), self.layout_override, self.debug_preview, self._preview_box,
                self.kit.px(12))
        threading.Thread(target=self._preview_worker, args=args, name="deskisle-preview",
                         daemon=True).start()

    def _preview_worker(self, config, override, debug, box, radius) -> None:
        try:
            layout = override or read_layout(names=False)
            image = render_preview_image(layout, config, fit_width(layout, *box), debug)
            buffer = io.BytesIO()
            style.rounded(image, radius).save(buffer, "PNG", compress_level=1)
            screens = layout.screen_list()
            info = f"{len(layout.icons)} 個圖示 · {len(screens)} 個螢幕"
            if len(screens) == 1:
                info += f" · {screens[0].width} × {screens[0].height}"
            if not layout.icons_visible:
                info += " · 桌面圖示目前是隱藏的"
            self._ui(self._preview_done, buffer.getvalue(), "", None if override else layout.screens, info)
        except Exception as exc:
            self._ui(self._preview_done, None, str(exc))

    def _preview_done(self, data: Optional[bytes], error: str, screens=None, info: str = "") -> None:
        self._preview_busy = False
        if screens is not None and screens != self._screens:
            self._set_screens(screens)   # 螢幕接上或拔掉了
        if data is not None:
            self._photo = tk.PhotoImage(master=self.root, data=base64.b64encode(data))
            canvas = self.preview_canvas
            canvas.configure(width=self._photo.width(), height=self._photo.height())
            canvas.delete("all")
            canvas.create_image(0, 0, image=self._photo, anchor="nw")
            self.preview_info.configure(text=info)
        else:
            self._photo = None
            self._draw_preview_placeholder(f"無法產生預覽:\n{error}")
            self.preview_info.configure(text="")
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

    def _set_header_state(self, state: str, text: str = "") -> None:
        """左下角「自動跟隨」卡片裡的狀態(彩色圓點 + 文字)。"""
        p = self.kit.p
        color = {"following": p.ok, "paused": p.warn, "error": p.danger}.get(state, p.subtle)
        self._state_dot.configure(image=self.kit.circle(self.kit.px(8), color))
        self._state_text.configure(text=text or STATE_TEXT.get(state, state))

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
        if status.state != "stopped" or not self.var_follow.get():
            detail = ""
            if status.state == "following" and status.updated_at:
                detail = f"跟隨中 · {status.updated_at} 更新"
            elif status.state == "stopped":
                detail = "未開啟"
            self._set_header_state(status.state, detail)
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
        handle = system.create_signal(SHOW_SIGNAL)
        if not handle:
            return

        def wait():
            while not self._quitting:
                if not system.wait_signal(handle):
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
        result["pages"] = app.page_names()
        result["has_test_page"] = app.has_test_page
        result["dark"] = app.kit.p.dark
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

    system.enable_dpi_awareness()
    if args.selftest:
        return selftest(args.selftest)

    if not system.acquire_single_instance(INSTANCE_NAME):
        system.send_signal(SHOW_SIGNAL)   # 已經在執行 → 請它把視窗叫出來
        return 0

    root = tk.Tk()
    App(root, start_hidden=args.minimized)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
