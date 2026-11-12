"""「圖片」頁:海洋、陸地各自可以用一張圖片(照片或取色),以及使用者的小物件。

海洋與陸地可以同時使用;小物件只能用照片(建議用去背的 PNG)。
圖片都會複製一份到設定資料夾(images/、objects/),原檔之後刪掉也沒關係。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Dict, List

from .. import APP_NAME
from ..config import app_dir
from ..engine import photo
from ..engine.themes import get_theme
from . import style
from .widgets import Button, ObjectTile, label, to_photo

MODE_OPTIONS = (("off", "不使用"), ("photo", "照片"), ("colors", "取色"))
ZONE_OPTIONS = (("water", "海上"), ("land", "陸地上"), ("both", "都可以"))
SHAPE_OPTIONS = (("original", "原樣"), ("circle", "裁成圓形"))

# 海洋、陸地:標題、說明、選了圖片後預設的用法、各用法的說明
SLOTS = {
    "water": dict(
        title="海洋", hint="把圖片鋪在海上,或只用它的顏色重新上色海。", default="photo",
        modes={"off": "選一張圖片後,可以直接鋪在海上(照片),或只用它的顏色(取色)。",
               "photo": "你的圖片鋪滿海面,海岸邊留一圈「{theme}」的淺灘與浪花,浪花會疊在圖片上。",
               "colors": "用圖片裡的顏色重新上色「{theme}」的海;深淺照主題,浪花與星雲也跟著換色。"}),
    "land": dict(
        title="陸地", hint="用圖片的顏色重新上色陸地,或直接把圖片鋪在陸地上。", default="colors",
        modes={"off": "選一張圖片後,可以只用它的顏色(取色,推薦),或直接鋪在陸地上(照片)。",
               "photo": "圖示周圍的陸地鋪上你的圖片,海岸留一圈「{theme}」的沙灘。陸地上的樹、花不畫。",
               "colors": "用圖片裡的顏色重新上色「{theme}」的陸地;質感與裝飾物照舊。"}),
}
OBJECTS_PER_ROW = 5


class ImagesPage:
    def __init__(self, app):
        self.app = app
        kit = self.kit = app.kit
        self.var_image = {kind: tk.StringVar() for kind in SLOTS}
        self.var_mode = {kind: tk.StringVar(value="off") for kind in SLOTS}
        self.objects: List[str] = []
        self.var_zone = tk.StringVar(value="water")
        self.var_amount = tk.DoubleVar(value=1.0)
        self.var_size = tk.DoubleVar(value=64.0)
        self.var_shape = tk.StringVar(value="original")
        self._thumb_keys: Dict[str, tuple] = {}
        self._thumb_photos: Dict[str, tk.PhotoImage] = {}

        page = app.add_page("圖片", "look", "用自己的圖片當海洋、陸地的材質或顏色,或放上自己的小物件。")
        for kind in SLOTS:
            self._build_slot(page, kind)

        # \u00a0 是不換行空白:tkinter 會優先在一般空白處換行,一行會斷得太早
        app.section(page, "小物件", "上傳小圖(建議用去背的\u00a0PNG,例如星球、小船、自己的貼圖),"
                                    "會像裝飾物一樣散落在桌布上。小物件只能用照片。")
        body = app.card(page)
        self.gallery = tk.Frame(body, background=kit.p.card)
        self.gallery.pack(fill="x", padx=kit.px(14), pady=(kit.px(14), kit.px(6)))
        app.segmented_row(body, "位置", "", ZONE_OPTIONS, self.var_zone, app._look_changed)
        app.slider_row(body, "數量", "0 = 不放", self.var_amount, 0, 3, "{:.1f}", app._look_changed)
        app.slider_row(body, "大小", "以 100% 縮放為準的像素", self.var_size, 24, 160, "{:.0f} px", app._look_changed)
        app.segmented_row(body, "形狀", "照片想當成星球時可以裁成圓形", SHAPE_OPTIONS, self.var_shape,
                          app._look_changed)
        label(page, kit, "", font="small").pack(pady=(0, kit.px(4)))
        self._build_gallery()

    # ------------------------------------------------------------ 海洋、陸地
    def _build_slot(self, page: tk.Frame, kind: str) -> None:
        app, kit = self.app, self.kit
        p, px = kit.p, kit.px
        info = SLOTS[kind]
        app.section(page, info["title"], info["hint"])
        body = app.card(page)
        line = tk.Frame(body, background=p.card)
        line.pack(fill="x", padx=px(14), pady=px(12))
        size = (px(104), px(66))
        thumb = tk.Canvas(line, width=size[0], height=size[1], background=p.card, highlightthickness=0, borderwidth=0)
        thumb.grid(row=0, column=0, rowspan=3, sticky="w")
        thumb.size = size
        label(line, kit, "圖片").grid(row=0, column=1, sticky="w", padx=(px(14), 0))
        caption = label(line, kit, font="caption", color=p.muted)
        caption.grid(row=1, column=1, sticky="w", padx=(px(14), 0), pady=(px(2), 0))
        buttons = tk.Frame(line, background=p.card)
        buttons.grid(row=2, column=1, sticky="w", padx=(px(14), 0), pady=(px(8), 0))
        Button(buttons, kit, "選擇圖片…", lambda: self.choose(kind), icon="look", small=True).pack(side="left")
        remove = Button(buttons, kit, "移除", lambda: self.remove(kind), kind="danger", small=True)
        remove.pack(side="left", padx=(px(6), 0))
        control = app.segmented_row(body, "用法", "", MODE_OPTIONS, self.var_mode[kind],
                                    lambda: self.mode_changed(kind))
        hint = label(control.master, kit, font="caption", color=p.muted, wrap=style.TEXT_WRAP - 30)
        hint.grid(row=3, column=0, columnspan=2, sticky="w", pady=(px(8), 0))
        setattr(self, f"{kind}_widgets", dict(thumb=thumb, caption=caption, remove=remove, hint=hint))

    def _refresh_slot(self, kind: str) -> None:
        kit = self.kit
        p = kit.p
        widgets = getattr(self, f"{kind}_widgets")
        path, mode = self.var_image[kind].get(), self.var_mode[kind].get()
        picture = photo.load(path)
        thumb = widgets["thumb"]
        width, height = thumb.size
        key = (path, picture is not None, p.dark)
        if key != self._thumb_keys.get(kind):
            self._thumb_keys[kind] = key
            thumb.delete("all")
            if picture is not None:
                image = style.rounded(photo.thumbnail(picture, width, height), kit.px(8))
                self._thumb_photos[kind] = to_photo(image, kit.root)
                thumb.create_image(0, 0, anchor="nw", image=self._thumb_photos[kind])
            else:
                kit.draw_box(thumb, 0, 0, width, height, kit.px(8), p.field, p.border)
                thumb.create_image(width / 2, height / 2, image=kit.icon("look", kit.px(22), p.subtle))
        if picture is not None:
            caption = f"{picture.width} × {picture.height}"
        elif path:
            caption = "找不到圖片檔案,請重新選擇"
        else:
            caption = "還沒有選擇圖片"
        widgets["caption"].configure(text=caption)
        widgets["remove"].set_enabled(bool(path))
        theme = get_theme(self.app._theme_key()).label
        widgets["hint"].configure(text=SLOTS[kind]["modes"].get(mode, "").format(theme=theme))

    def choose(self, kind: str) -> bool:
        """請使用者挑一張圖片,複製一份到程式的資料夾。挑好回傳 True。"""
        root = self.app.root
        path = filedialog.askopenfilename(parent=root, title=f"選擇{SLOTS[kind]['title']}的圖片",
                                          filetypes=[("圖片", " ".join(photo.IMAGE_TYPES)), ("所有檔案", "*.*")])
        if not path:
            return False
        target = self._import(lambda: photo.import_image(path, app_dir() / "images"))
        if target is None:
            return False
        self.var_image[kind].set(str(target))
        if self.var_mode[kind].get() == "off":
            self.var_mode[kind].set(SLOTS[kind]["default"])     # 選了圖片通常就是要用它
        self.app._look_changed()
        return True

    def mode_changed(self, kind: str) -> None:
        if self.var_mode[kind].get() != "off" and photo.load(self.var_image[kind].get()) is None:
            if not self.choose(kind):
                self.var_mode[kind].set("off")   # 沒選圖片就維持「不使用」
        self.app._look_changed()

    def remove(self, kind: str) -> None:
        self.var_image[kind].set("")
        self.var_mode[kind].set("off")
        self.app._look_changed()

    def _import(self, work):
        root = self.app.root
        root.configure(cursor="watch")
        root.update_idletasks()
        try:
            return work()
        except (ValueError, OSError) as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=root)
            return None
        finally:
            root.configure(cursor="")

    # -------------------------------------------------------------- 小物件
    def _build_gallery(self) -> None:
        kit = self.kit
        px = kit.px
        for child in self.gallery.winfo_children():
            child.destroy()
        size, gap = px(64), px(8)
        tiles = [(photo.load_object(path), lambda i=i: self.remove_object(i)) for i, path in enumerate(self.objects)]
        tiles = [(image, command) for image, command in tiles if image is not None]
        tiles.append((None, self.add_objects))
        for index, (image, command) in enumerate(tiles):
            tile = ObjectTile(self.gallery, kit, image, command, size)
            tile.grid(row=index // OBJECTS_PER_ROW, column=index % OBJECTS_PER_ROW,
                      padx=(0, gap), pady=(0, gap))
        count = len(tiles) - 1
        note = f"{count} 個小物件 · 滑到小物件上按一下可以刪除" if count else "按 + 加入小物件(可以一次選好幾張)"
        label(self.gallery, kit, note, font="caption", color=kit.p.muted).grid(
            row=len(tiles) // OBJECTS_PER_ROW + 1, column=0, columnspan=OBJECTS_PER_ROW, sticky="w")

    def add_objects(self) -> None:
        paths = filedialog.askopenfilenames(parent=self.app.root, title="加入小物件",
                                            filetypes=[("圖片", " ".join(photo.IMAGE_TYPES)), ("所有檔案", "*.*")])
        added = False
        for path in paths:
            target = self._import(lambda path=path: photo.import_object(path, app_dir() / "objects"))
            if target is not None and str(target) not in self.objects:
                self.objects.append(str(target))
                added = True
        if added:
            self._build_gallery()
            self.app._look_changed()

    def remove_object(self, index: int) -> None:
        if 0 <= index < len(self.objects):
            del self.objects[index]
            self._build_gallery()
            self.app._look_changed()

    # ---------------------------------------------------------------- 設定值
    def load(self, config) -> None:
        for kind in SLOTS:
            self.var_image[kind].set(getattr(config, f"{kind}_image"))
            self.var_mode[kind].set(getattr(config, f"{kind}_mode"))
        if list(config.objects) != self.objects:
            self.objects = list(config.objects)
            self._build_gallery()
        self.var_zone.set(config.objects_zone)
        self.var_amount.set(config.objects_amount)
        self.var_size.set(config.objects_size)
        self.var_shape.set(config.objects_shape)

    def values(self) -> dict:
        """畫面上的設定(給 App.draft_config 用)。"""
        return dict(
            water_image=self.var_image["water"].get(), water_mode=self.var_mode["water"].get(),
            land_image=self.var_image["land"].get(), land_mode=self.var_mode["land"].get(),
            objects=tuple(self.objects), objects_zone=self.var_zone.get(),
            objects_amount=round(self.var_amount.get(), 1), objects_size=float(round(self.var_size.get())),
            objects_shape=self.var_shape.get(),
        )

    def refresh(self) -> None:
        for kind in SLOTS:
            self._refresh_slot(kind)

    def missing(self, config) -> List[str]:
        """設定裡用到、但檔案不見了的圖片(預覽下方提示用)。"""
        names = []
        for kind in SLOTS:
            if getattr(config, f"{kind}_mode") != "off" and photo.load(getattr(config, f"{kind}_image")) is None:
                names.append(SLOTS[kind]["title"])
        if config.objects and len(photo.object_sprites(config.objects, "original")) < len(config.objects):
            names.append("小物件")
        return names
