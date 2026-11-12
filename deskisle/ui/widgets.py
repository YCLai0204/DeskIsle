"""設定介面的自繪元件:卡片、按鈕、開關、滑桿、標籤、主題縮圖、螢幕選擇、導覽項目、捲動區。

全部畫在 tk.Canvas 上;圓角、圓點用 style.py 以 Pillow 畫的反鋸齒圖片,
所以在淺色、深色、高 DPI 下都乾淨,而且不需要額外套件。
每個元件都可以用鍵盤操作(Tab 移動,空白鍵/Enter 按下,左右鍵調整滑桿)。
"""
from __future__ import annotations

import base64
import io
import time
import tkinter as tk
from typing import Callable, Dict, Optional

from PIL import Image

from . import style
from .style import Palette


def to_photo(image: Image.Image, master: tk.Misc) -> tk.PhotoImage:
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return tk.PhotoImage(master=master, data=base64.b64encode(buffer.getvalue()))


def bg_of(widget: tk.Misc) -> str:
    return str(widget.cget("background"))


COLOR_OPTIONS = ("background", "foreground", "highlightbackground", "highlightcolor", "insertbackground",
                 "selectbackground", "selectforeground", "activebackground", "activeforeground", "selectcolor",
                 "disabledforeground")


def palette_map(old: Palette, new: Palette) -> Dict[str, str]:
    """舊配色的每個色碼 → 新配色同一個項目的色碼(小寫)。"""
    mapping = {}
    for name in old.__dataclass_fields__:
        if name != "dark":
            mapping[getattr(old, name).lower()] = getattr(new, name)
    return mapping


def apply_palette(root: tk.Misc, kit: "Kit", palette: Palette) -> None:
    """不重建介面,直接把整個視窗換成另一組配色。

    一般元件(Frame、Label、Entry、Menu……)把用到的舊色碼換成新色碼;
    自己畫的元件(有 recolor 方法的)再依新配色重畫。
    """
    mapping = palette_map(kit.p, palette)
    kit.p = palette

    def visit(widget):
        changes = {}
        for option in COLOR_OPTIONS:
            try:
                value = str(widget.cget(option)).lower()
            except (tk.TclError, ValueError):
                continue
            if value in mapping:
                changes[option] = mapping[value]
        if changes:
            try:
                widget.configure(**changes)
            except tk.TclError:
                pass
        if hasattr(widget, "recolor"):
            widget.recolor(mapping)
        for child in widget.winfo_children():
            visit(child)

    visit(root)


class Kit:
    """一個視窗共用的東西:配色、縮放比例、字型、圖片快取。"""

    def __init__(self, root: tk.Misc, palette: Palette, scale: float = 1.0):
        self.root = root
        self.p = palette
        self.scale = scale
        self.fonts = style.make_fonts(root)
        self._photos: Dict[tuple, tk.PhotoImage] = {}

    def px(self, value: float) -> int:
        """以 100% 縮放為準的像素,換成目前縮放比例下的像素。"""
        return int(round(value * self.scale))

    def photo(self, key: tuple, make: Callable[[], Image.Image]) -> tk.PhotoImage:
        image = self._photos.get(key)
        if image is None:
            image = self._photos[key] = to_photo(make(), self.root)
        return image

    def round_rect(self, width, height, radius, fill=None, outline=None, line=1) -> tk.PhotoImage:
        return self.photo(("rr", width, height, radius, fill, outline, line),
                          lambda: style.round_rect(width, height, radius, fill, outline, line))

    def circle(self, size, fill=None, outline=None, line=1) -> tk.PhotoImage:
        return self.round_rect(size, size, size / 2, fill, outline, line)

    def icon(self, name: str, size: int, color: str) -> tk.PhotoImage:
        return self.photo(("icon", name, size, color), lambda: style.icon(name, size, color))

    def draw_box(self, canvas: tk.Canvas, x0: int, y0: int, x1: int, y1: int, radius: int,
                 fill: Optional[str], outline: Optional[str] = None, tags=()) -> None:
        """在 canvas 上畫任意大小的圓角矩形:四個角用圖片,其餘用一般矩形(改大小時不必重畫圖)。"""
        radius = max(1, min(radius, (x1 - x0) // 2, (y1 - y0) // 2))
        line = max(1, self.px(1))
        corners = ((0, 0, x0, y0, "nw"), (1, 0, x1, y0, "ne"), (0, 1, x0, y1, "sw"), (1, 1, x1, y1, "se"))
        for qx, qy, x, y, anchor in corners:
            def make(qx=qx, qy=qy):
                full = style.round_rect(radius * 2, radius * 2, radius, fill, outline, line)
                return full.crop((qx * radius, qy * radius, (qx + 1) * radius, (qy + 1) * radius))
            image = self.photo(("corner", qx, qy, radius, fill, outline, line), make)
            canvas.create_image(x, y, image=image, anchor=anchor, tags=tags)
        if fill:
            canvas.create_rectangle(x0 + radius, y0, x1 - radius, y1, fill=fill, width=0, tags=tags)
            canvas.create_rectangle(x0, y0 + radius, x1, y1 - radius, fill=fill, width=0, tags=tags)
        if outline:
            for box in ((x0 + radius, y0, x1 - radius, y0 + line), (x0 + radius, y1 - line, x1 - radius, y1),
                        (x0, y0 + radius, x0 + line, y1 - radius), (x1 - line, y0 + radius, x1, y1 - radius)):
                canvas.create_rectangle(*box, fill=outline, width=0, tags=tags)


class _CanvasWidget(tk.Canvas):
    def __init__(self, parent, kit: Kit, bg: Optional[str] = None, **options):
        options.setdefault("highlightthickness", 0)
        options.setdefault("borderwidth", 0)
        super().__init__(parent, background=bg or bg_of(parent), **options)
        self.kit = kit
        self.hover = False
        self._traces = []
        self._job = None        # 動畫的下一格(after 的代碼)
        self.bind("<Destroy>", self._on_destroy, add="+")

    def _watch(self, variable: tk.Variable, callback) -> None:
        """變數改了就重畫;元件消失時取消監看(變數可能比元件活得久)。"""
        name = variable.trace_add("write", lambda *_a: self._safe(callback))
        self._traces.append((variable, name))

    def _on_destroy(self, event) -> None:
        if event.widget is not self:
            return
        for variable, name in self._traces:
            try:
                variable.trace_remove("write", name)
            except tk.TclError:
                pass
        self._traces = []
        if self._job is not None:
            # 沒做完的動畫要取消,不然計時器之後會呼叫已經不存在的函式
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def _safe(self, callback) -> None:
        try:
            callback()
        except tk.TclError:
            pass   # 視窗已經關閉

    def recolor(self, mapping: Dict[str, str]) -> None:
        """換配色後重畫(大部分元件畫的時候都直接讀 kit.p,重畫就好)。"""
        paint = getattr(self, "_paint", None)
        if paint is not None:
            self._safe(paint)


# ---------------------------------------------------------------------------
class Card(_CanvasWidget):
    """圓角卡片。內容放在 card.body 裡(一般的 tk.Frame)。"""

    def __init__(self, parent, kit: Kit, padding=(16, 16), radius: int = 10, fill: Optional[str] = None,
                 outline: Optional[str] = "", bg: Optional[str] = None):
        super().__init__(parent, kit, bg)
        self.fill = fill or kit.p.card
        self.outline = kit.p.border if outline == "" else outline
        self.radius = kit.px(radius)
        padx, pady = (padding, padding) if isinstance(padding, (int, float)) else padding
        self.body = tk.Frame(self, background=self.fill)
        self.body.pack(fill="both", expand=True, padx=kit.px(padx), pady=kit.px(pady))
        self.bind("<Configure>", self._redraw)

    def recolor(self, mapping: Dict[str, str]) -> None:
        self.fill = mapping.get(self.fill.lower(), self.fill)
        if self.outline:
            self.outline = mapping.get(self.outline.lower(), self.outline)
        self._redraw()

    def _redraw(self, _event=None) -> None:
        self.delete("box")
        width, height = self.winfo_width(), self.winfo_height()
        if width > 2 and height > 2:
            self.kit.draw_box(self, 0, 0, width, height, self.radius, self.fill, self.outline, tags="box")
            self.tag_lower("box")


class Divider(tk.Frame):
    def __init__(self, parent, kit: Kit):
        super().__init__(parent, background=kit.p.border, height=max(1, kit.px(1)))


def label(parent, kit: Kit, text: str = "", font: str = "body", color: Optional[str] = None,
          wrap: int = 0, **options) -> tk.Label:
    """跟父元件同底色的文字。wrap 是以 100% 縮放為準的換行寬度。"""
    settings = dict(text=text, font=kit.fonts[font], foreground=color or kit.p.text, background=bg_of(parent),
                    anchor="w", justify="left", wraplength=kit.px(wrap) if wrap else 0,
                    borderwidth=0, padx=0, pady=0)
    settings.update(options)
    return tk.Label(parent, **settings)


# ---------------------------------------------------------------------------
class Button(_CanvasWidget):
    """圓角按鈕。kind:primary(主要動作)、secondary、ghost(只有文字)、danger(滑過變紅的 ghost)。"""

    def __init__(self, parent, kit: Kit, text: str, command: Optional[Callable] = None,
                 kind: str = "secondary", icon: Optional[str] = None, small: bool = False,
                 bg: Optional[str] = None):
        px = kit.px
        font = kit.fonts["bold" if kind == "primary" else ("caption" if small else "body")]
        height = px(30 if small else 38)
        padx = px(12 if small else 18)
        icon_size, gap = px(15 if small else 16), px(7 if small else 8)
        width = padx * 2 + font.measure(text) + (icon_size + gap if icon else 0)
        super().__init__(parent, kit, bg, width=width, height=height, cursor="hand2", takefocus=1)
        self.command = command
        self.enabled = True
        self._pressed = False
        self.size = (width, height)
        self.radius = px(7)
        self.kind = kind
        self._colors = self._color_table()
        self._back = self.create_image(0, 0, anchor="nw")
        x = padx
        self._icon_name, self._icon_size = icon, icon_size
        self._icon = self.create_image(x, height / 2, anchor="w") if icon else None
        if icon:
            x += icon_size + gap
        self._text = self.create_text(x, height / 2, anchor="w", text=text, font=font)
        for sequence, handler in (("<Enter>", self._enter), ("<Leave>", self._leave),
                                  ("<ButtonPress-1>", self._press), ("<ButtonRelease-1>", self._release),
                                  ("<KeyPress-space>", self._key), ("<KeyPress-Return>", self._key)):
            self.bind(sequence, handler)
        self._paint()

    def _color_table(self):
        p = self.kit.p
        return {
            "primary": {"normal": (p.accent, None, p.on_accent), "hover": (p.accent_hover, None, p.on_accent),
                        "pressed": (p.accent_press, None, p.on_accent), "disabled": (p.track, None, p.subtle)},
            "secondary": {"normal": (p.card, p.border_strong, p.text), "hover": (p.card_hover, p.border_strong, p.text),
                          "pressed": (p.bg, p.border, p.muted), "disabled": (p.card, p.border, p.subtle)},
            "ghost": {"normal": (None, None, p.muted), "hover": (p.nav_hover, None, p.text),
                      "pressed": (p.nav_selected, None, p.text), "disabled": (None, None, p.subtle)},
            "danger": {"normal": (None, None, p.muted), "hover": (p.nav_hover, None, p.danger),
                       "pressed": (p.nav_selected, None, p.danger), "disabled": (None, None, p.subtle)},
        }[self.kind]

    def recolor(self, mapping) -> None:
        self._colors = self._color_table()
        self._paint()

    def _state(self) -> str:
        if not self.enabled:
            return "disabled"
        if self._pressed and self.hover:
            return "pressed"
        return "hover" if self.hover else "normal"

    def _paint(self) -> None:
        fill, outline, color = self._colors[self._state()]
        width, height = self.size
        image = self.kit.round_rect(width, height, self.radius, fill, outline) if (fill or outline) else ""
        self.itemconfigure(self._back, image=image)
        self.itemconfigure(self._text, fill=color)
        if self._icon is not None:
            self.itemconfigure(self._icon, image=self.kit.icon(self._icon_name, self._icon_size, color))

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self.configure(cursor="hand2" if enabled else "")
        self._paint()

    def invoke(self) -> None:
        if self.enabled and self.command:
            self.command()

    def _enter(self, _event) -> None:
        self.hover = True
        self._paint()

    def _leave(self, _event) -> None:
        self.hover = False
        self._paint()

    def _press(self, _event) -> None:
        self._pressed = True
        self.focus_set()
        self._paint()

    def _release(self, _event) -> None:
        clicked = self._pressed and self.hover
        self._pressed = False
        self._paint()
        if clicked:
            self.invoke()

    def _key(self, _event) -> None:
        self.invoke()


# ---------------------------------------------------------------------------
class Toggle(_CanvasWidget):
    """開關。綁定一個 BooleanVar;使用者切換後呼叫 command()。"""

    STEPS = 5

    def __init__(self, parent, kit: Kit, variable: tk.BooleanVar, command: Optional[Callable] = None,
                 bg: Optional[str] = None):
        width, height = kit.px(40), kit.px(20)
        super().__init__(parent, kit, bg, width=width, height=height, cursor="hand2", takefocus=1)
        self.variable = variable
        self.command = command
        self.size = (width, height)
        self._position = 1.0 if variable.get() else 0.0
        self._track = self.create_image(0, 0, anchor="nw")
        self._knob = self.create_image(0, height / 2, anchor="center")
        self._watch(variable, self._animate)
        for sequence, handler in (("<Enter>", self._enter), ("<Leave>", self._leave),
                                  ("<ButtonRelease-1>", self._click), ("<KeyPress-space>", self._click)):
            self.bind(sequence, handler)
        self._paint()

    def _paint(self) -> None:
        p, kit = self.kit.p, self.kit
        width, height = self.size
        on = bool(self.variable.get())
        if on:
            track = kit.round_rect(width, height, height / 2, p.accent_hover if self.hover else p.accent)
            knob_color = p.on_accent
        else:
            track = kit.round_rect(width, height, height / 2, p.card_hover if self.hover else None,
                                   p.muted, max(1, kit.px(1)))
            knob_color = p.muted
        knob = kit.px(14 if self.hover else 12)
        self.itemconfigure(self._track, image=track)
        self.itemconfigure(self._knob, image=kit.circle(knob, knob_color))
        left, right = height / 2, width - height / 2
        self.coords(self._knob, left + (right - left) * self._position, height / 2)

    def _animate(self) -> None:
        target = 1.0 if self.variable.get() else 0.0
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None
        step = 1.0 / self.STEPS

        def tick():
            self._job = None
            if abs(self._position - target) <= step:
                self._position = target
            else:
                self._position += step if target > self._position else -step
                self._job = self.after(14, lambda: self._safe(tick))
            self._paint()

        tick()

    def _click(self, _event=None) -> None:
        self.focus_set()
        self.variable.set(not self.variable.get())
        if self.command:
            self.command()

    def _enter(self, _event) -> None:
        self.hover = True
        self._paint()

    def _leave(self, _event) -> None:
        self.hover = False
        self._paint()


# ---------------------------------------------------------------------------
class Slider(_CanvasWidget):
    """滑桿。綁定一個 DoubleVar;使用者拖動時呼叫 command()。"""

    def __init__(self, parent, kit: Kit, variable: tk.DoubleVar, low: float, high: float,
                 command: Optional[Callable] = None, bg: Optional[str] = None):
        super().__init__(parent, kit, bg, width=kit.px(200), height=kit.px(24), cursor="hand2", takefocus=1)
        self.variable, self.low, self.high, self.command = variable, low, high, command
        self._dragging = False
        self.radius = kit.px(10)
        self._watch(variable, self._paint)
        for sequence, handler in (("<Configure>", self._paint), ("<Enter>", self._enter), ("<Leave>", self._leave),
                                  ("<ButtonPress-1>", self._press), ("<B1-Motion>", self._drag),
                                  ("<ButtonRelease-1>", self._release),
                                  ("<KeyPress-Left>", lambda _e: self._nudge(-1)),
                                  ("<KeyPress-Right>", lambda _e: self._nudge(1))):
            self.bind(sequence, handler)

    def _ends(self):
        return self.radius, max(self.radius + 1, self.winfo_width() - self.radius)

    def _fraction(self) -> float:
        try:
            value = float(self.variable.get())
        except (tk.TclError, ValueError):
            value = self.low
        return max(0.0, min(1.0, (value - self.low) / (self.high - self.low)))

    def _paint(self, _event=None) -> None:
        p, kit = self.kit.p, self.kit
        self.delete("all")
        x0, x1 = self._ends()
        y = int(self.winfo_reqheight() / 2)
        x = x0 + (x1 - x0) * self._fraction()
        thick = max(2, kit.px(4))
        self.create_line(x0, y, x1, y, width=thick, fill=p.track, capstyle="round")
        if x > x0 + 1:
            self.create_line(x0, y, x, y, width=thick, fill=p.accent, capstyle="round")
        outer = self.radius * 2
        self.create_image(x, y, image=kit.circle(outer, p.card, p.border_strong, max(1, kit.px(1))))
        inner = kit.px(8 if self._dragging else (12 if self.hover else 10))
        self.create_image(x, y, image=kit.circle(inner, p.accent_hover if self.hover else p.accent))

    def _set_from(self, x: int) -> None:
        x0, x1 = self._ends()
        fraction = max(0.0, min(1.0, (x - x0) / (x1 - x0)))
        self.variable.set(self.low + fraction * (self.high - self.low))
        if self.command:
            self.command()

    def _nudge(self, direction: int) -> None:
        value = self.low + self._fraction() * (self.high - self.low) + direction * (self.high - self.low) / 40
        self.variable.set(max(self.low, min(self.high, value)))
        if self.command:
            self.command()

    def _press(self, event) -> None:
        self.focus_set()
        self._dragging = True
        self._set_from(event.x)

    def _drag(self, event) -> None:
        self._set_from(event.x)

    def _release(self, _event) -> None:
        self._dragging = False
        self._paint()

    def _enter(self, _event) -> None:
        self.hover = True
        self._paint()

    def _leave(self, _event) -> None:
        self.hover = False
        self._paint()


# ---------------------------------------------------------------------------
class Segmented(_CanvasWidget):
    """幾個選項排成一排、一次選一個(例如「跟隨系統 / 淺色 / 深色」)。綁定一個 StringVar。"""

    def __init__(self, parent, kit: Kit, options, variable: tk.StringVar, command: Optional[Callable] = None,
                 bg: Optional[str] = None):
        px = kit.px
        self.options = list(options)          # [(值, 顯示文字), ...]
        font = kit.fonts["caption"]
        self._inset, height, pad = px(3), px(32), px(14)
        self._widths = [font.measure(text) + pad * 2 for _value, text in self.options]
        width = sum(self._widths) + self._inset * 2
        super().__init__(parent, kit, bg, width=width, height=height, cursor="hand2", takefocus=1)
        self.variable, self.command = variable, command
        self.size = (width, height)
        self._hover = -1
        self._watch(variable, self._paint)
        for sequence, handler in (("<Motion>", self._move), ("<Leave>", self._leave),
                                  ("<ButtonRelease-1>", self._click),
                                  ("<KeyPress-Left>", lambda _e: self._step(-1)),
                                  ("<KeyPress-Right>", lambda _e: self._step(1))):
            self.bind(sequence, handler)
        self._paint()

    def _bounds(self):
        x = self._inset
        for width in self._widths:
            yield x, x + width
            x += width

    def _index_at(self, x: int) -> int:
        for index, (left, right) in enumerate(self._bounds()):
            if left <= x < right:
                return index
        return -1

    def _paint(self) -> None:
        p, kit, px = self.kit.p, self.kit, self.kit.px
        self.delete("all")
        width, height = self.size
        self.create_image(0, 0, anchor="nw", image=kit.round_rect(width, height, px(8), p.field, p.border))
        current = self.variable.get()
        for index, ((value, text), (left, right)) in enumerate(zip(self.options, self._bounds())):
            selected = value == current
            if selected:
                self.create_image(left, self._inset, anchor="nw", image=kit.round_rect(
                    right - left, height - self._inset * 2, px(6), p.card, p.border_strong))
            color = p.text if selected or index == self._hover else p.muted
            self.create_text((left + right) / 2, height / 2, text=text, fill=color,
                             font=kit.fonts["bold" if selected else "caption"])

    def _choose(self, index: int) -> None:
        if 0 <= index < len(self.options):
            value = self.options[index][0]
            if value != self.variable.get():
                self.variable.set(value)
                if self.command:
                    self.command()

    def _click(self, event) -> None:
        self.focus_set()
        self._choose(self._index_at(event.x))

    def _step(self, direction: int) -> None:
        values = [value for value, _text in self.options]
        current = values.index(self.variable.get()) if self.variable.get() in values else 0
        self._choose(max(0, min(len(values) - 1, current + direction)))

    def _move(self, event) -> None:
        index = self._index_at(event.x)
        if index != self._hover:
            self._hover = index
            self._paint()

    def _leave(self, _event) -> None:
        self._hover = -1
        self._paint()


# ---------------------------------------------------------------------------
class Dropdown(_CanvasWidget):
    """下拉選單:看起來像按鈕,點一下在下方跳出自己畫的選項清單(見 DropdownPopup)。綁定一個 StringVar。"""

    def __init__(self, parent, kit: Kit, options, variable: tk.StringVar, command: Optional[Callable] = None,
                 bg: Optional[str] = None):
        px = kit.px
        self.options = list(options)              # [(值, 顯示文字), ...]
        font = kit.fonts["caption"]
        self._pad, self._arrow = px(12), px(14)
        width = max(font.measure(text) for _value, text in self.options) + self._pad * 2 + self._arrow + px(6)
        height = px(30)
        super().__init__(parent, kit, bg, width=width, height=height, cursor="hand2", takefocus=1)
        self.variable, self.command = variable, command
        self.size = (width, height)
        self.popup: Optional["DropdownPopup"] = None
        self._closed_at = 0.0
        self._watch(variable, self._paint)
        for sequence, handler in (("<Enter>", self._enter), ("<Leave>", self._leave),
                                  ("<ButtonRelease-1>", self._open), ("<KeyPress-space>", self._open),
                                  ("<KeyPress-Return>", self._open), ("<KeyPress-Down>", self._open)):
            self.bind(sequence, handler)
        self._paint()

    def text(self) -> str:
        current = self.variable.get()
        return next((text for value, text in self.options if value == current), current)

    def _paint(self) -> None:
        p, kit, px = self.kit.p, self.kit, self.kit.px
        self.delete("all")
        width, height = self.size
        opened = self.popup is not None
        self.create_image(0, 0, anchor="nw", image=kit.round_rect(
            width, height, px(7), p.card_hover if (self.hover or opened) else p.card,
            p.accent if opened else p.border_strong))
        self.create_text(self._pad, height / 2, anchor="w", text=self.text(), fill=p.text, font=kit.fonts["caption"])
        self.create_image(width - self._pad + px(2), height / 2, anchor="e",
                          image=kit.icon("chevron", self._arrow, p.text if opened else p.muted))

    def _open(self, _event=None) -> None:
        if self.popup is not None or time.monotonic() - self._closed_at < 0.25:
            return      # 剛剛才因為點這裡而關掉(清單失去焦點),不要馬上又打開
        self.popup = DropdownPopup(self)
        self._paint()

    def _popup_closed(self) -> None:
        self.popup = None
        self._closed_at = time.monotonic()
        self._safe(self._paint)

    def choose(self, value: str) -> None:
        """選一個值(清單裡點選,或測試時直接呼叫)。"""
        if value != self.variable.get():
            self.variable.set(value)
            if self.command:
                self.command()

    def _enter(self, _event) -> None:
        self.hover = True
        self._paint()

    def _leave(self, _event) -> None:
        self.hover = False
        self._paint()


class DropdownPopup(tk.Toplevel):
    """下拉選單跳出來的清單:沒有標題列的小視窗,卡片底色、滑過有底色、選中的有強調色短線與打勾。

    超過 MAX_ROWS 項時可以用滾輪捲動。點選項或按 Enter 選擇;按 Esc 或點到別的地方就關閉。
    """

    MAX_ROWS = 8

    def __init__(self, owner: Dropdown):
        kit = owner.kit
        p, px = kit.p, kit.px
        super().__init__(owner, background=p.border_strong)
        self.owner, self.kit = owner, kit
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        font = kit.fonts["bold"]
        self.row_h, self.inset, self.check = px(32), px(5), px(14)
        text_w = max(font.measure(text) for _value, text in owner.options)
        self.width = max(owner.size[0], text_w + px(16) * 2 + self.check + px(10))
        self.height = min(len(owner.options), self.MAX_ROWS) * self.row_h + self.inset * 2
        self.total = len(owner.options) * self.row_h + self.inset * 2
        self.canvas = tk.Canvas(self, width=self.width, height=self.height, background=p.card,
                                highlightthickness=0, borderwidth=0, scrollregion=(0, 0, self.width, self.total),
                                yscrollincrement=1)
        self.canvas.pack(padx=1, pady=1)
        values = [value for value, _text in owner.options]
        current = owner.variable.get()
        self.hover = values.index(current) if current in values else 0
        self._place()
        self._paint()
        self._scroll_to(self.hover)

        for sequence, handler in (("<Motion>", self._move), ("<ButtonRelease-1>", self._click),
                                  ("<MouseWheel>", self._wheel), ("<Button-4>", self._wheel),
                                  ("<Button-5>", self._wheel),
                                  ("<KeyPress-Up>", lambda _e: self._step(-1)),
                                  ("<KeyPress-Down>", lambda _e: self._step(1)),
                                  ("<KeyPress-Return>", lambda _e: self._pick(self.hover)),
                                  ("<KeyPress-space>", lambda _e: self._pick(self.hover)),
                                  ("<KeyPress-Escape>", lambda _e: self.close()),
                                  ("<FocusOut>", lambda _e: self.close())):
            self.canvas.bind(sequence, handler)
        self.update_idletasks()
        try:
            from .. import system
            system.round_window_corners(self.winfo_id())
        except Exception:
            pass
        self.canvas.focus_force()

    def _place(self) -> None:
        """放在下拉選單正下方;下面放不下就放上面。"""
        owner, px = self.owner, self.kit.px
        x = owner.winfo_rootx()
        y = owner.winfo_rooty() + owner.size[1] + px(4)
        if y + self.height + 2 > owner.winfo_screenheight():
            y = owner.winfo_rooty() - self.height - 2 - px(4)
        x = max(0, min(x, owner.winfo_screenwidth() - self.width - 2))
        self.geometry(f"{self.width + 2}x{self.height + 2}+{x}+{y}")

    def _paint(self) -> None:
        kit, p, px = self.kit, self.kit.p, self.kit.px
        c = self.canvas
        c.delete("all")
        current = self.owner.variable.get()
        for index, (value, text) in enumerate(self.owner.options):
            top = self.inset + index * self.row_h
            middle = top + self.row_h / 2
            selected = value == current
            if index == self.hover or selected:
                kit.draw_box(c, self.inset, top + 1, self.width - self.inset, top + self.row_h - 1, px(6),
                             p.border if index == self.hover and not selected else p.accent_soft)
            if selected:
                c.create_image(self.inset + px(1), middle, anchor="w",
                               image=kit.round_rect(px(3), px(14), px(1.5), p.accent))
                c.create_image(self.width - self.inset - px(10), middle, anchor="e",
                               image=kit.icon("check", self.check, p.accent))
            c.create_text(self.inset + px(14), middle, anchor="w", text=text,
                          fill=p.accent if selected else p.text, font=kit.fonts["bold" if selected else "caption"])

    def _index_at(self, y: int) -> int:
        index = int((self.canvas.canvasy(y) - self.inset) // self.row_h)
        return index if 0 <= index < len(self.owner.options) else -1

    def _scroll_to(self, index: int) -> None:
        if self.total <= self.height:
            return
        top, bottom = self.canvas.canvasy(0), self.canvas.canvasy(self.height)
        row_top = self.inset + index * self.row_h
        if row_top < top:
            self.canvas.yview_moveto(max(0.0, (row_top - self.inset) / self.total))
        elif row_top + self.row_h > bottom:
            self.canvas.yview_moveto(max(0.0, (row_top + self.row_h + self.inset - self.height) / self.total))

    def _move(self, event) -> None:
        index = self._index_at(event.y)
        if index >= 0 and index != self.hover:
            self.hover = index
            self._paint()

    def _step(self, direction: int) -> None:
        self.hover = max(0, min(len(self.owner.options) - 1, self.hover + direction))
        self._paint()
        self._scroll_to(self.hover)

    def _wheel(self, event) -> str:
        if getattr(event, "num", None) in (4, 5):
            steps = -1 if event.num == 4 else 1
        else:
            steps = -1 if event.delta > 0 else 1
        if self.total > self.height:
            self.canvas.yview_scroll(steps * self.row_h, "units")
            self._move(event)
        return "break"     # 不要讓後面的設定頁跟著捲

    def _click(self, event) -> None:
        index = self._index_at(event.y)
        if index >= 0:
            self._pick(index)

    def _pick(self, index: int) -> None:
        value = self.owner.options[index][0]
        self.close()
        self.owner.choose(value)

    def close(self) -> None:
        try:
            if not self.winfo_exists():
                return
            self.destroy()
        except tk.TclError:
            return
        self.owner._popup_closed()

    def recolor(self, mapping) -> None:
        self._paint()


# ---------------------------------------------------------------------------
class Pill(_CanvasWidget):
    """小標籤(例如「尚未套用」)。沒有文字時不佔空間。"""

    def __init__(self, parent, kit: Kit, bg: Optional[str] = None):
        super().__init__(parent, kit, bg, width=1, height=kit.px(24))
        self.text = ""

    def recolor(self, mapping) -> None:
        if self.text:
            text, color, fill, dot = self._shown
            self.show(text, mapping.get(color.lower(), color), mapping.get(fill.lower(), fill), dot)

    def show(self, text: str, color: str, fill: str, dot: bool = True) -> None:
        kit = self.kit
        self.text = text
        self._shown = (text, color, fill, dot)
        self.delete("all")
        if not text:
            self.configure(width=1)
            return
        font = kit.fonts["caption"]
        height = kit.px(24)
        padx, dot_size, gap = kit.px(10), kit.px(6), kit.px(6)
        width = padx * 2 + font.measure(text) + (dot_size + gap if dot else 0)
        self.configure(width=width)
        self.create_image(0, 0, anchor="nw", image=kit.round_rect(width, height, height / 2, fill))
        x = padx
        if dot:
            self.create_image(x, height / 2, anchor="w", image=kit.circle(dot_size, color))
            x += dot_size + gap
        self.create_text(x, height / 2, anchor="w", text=text, font=font, fill=color)


# ---------------------------------------------------------------------------
class ThemeTile(_CanvasWidget):
    """主題縮圖:圓角小圖 + 名稱;選到的有一圈強調色外框。"""

    def __init__(self, parent, kit: Kit, image: Image.Image, text: str, command: Callable,
                 bg: Optional[str] = None):
        thumb_w, thumb_h = image.size
        ring, gap = kit.px(2), kit.px(2)
        self.margin = ring + gap
        width, height = thumb_w + self.margin * 2, thumb_h + self.margin * 2 + kit.px(24)
        super().__init__(parent, kit, bg, width=width, height=height, cursor="hand2", takefocus=1)
        self.selected = False
        self.command = command
        self._ring_size = (width, thumb_h + self.margin * 2)
        self._ring_line = ring
        self._radius = kit.px(8)
        self._thumb = to_photo(style.rounded(image, self._radius), kit.root)
        self._ring = self.create_image(0, 0, anchor="nw")
        self.create_image(self.margin, self.margin, anchor="nw", image=self._thumb)
        self._label = self.create_text(width / 2, thumb_h + self.margin * 2 + kit.px(11), text=text, anchor="center")
        for sequence, handler in (("<Enter>", self._enter), ("<Leave>", self._leave),
                                  ("<ButtonRelease-1>", self._click), ("<KeyPress-space>", self._click)):
            self.bind(sequence, handler)
        self._paint()

    def _paint(self) -> None:
        p, kit = self.kit.p, self.kit
        color = p.accent if self.selected else (p.border_strong if self.hover else None)
        width, height = self._ring_size
        ring = kit.round_rect(width, height, self._radius + self.margin, None, color, self._ring_line) if color else ""
        self.itemconfigure(self._ring, image=ring)
        self.itemconfigure(self._label, fill=p.accent if self.selected else (p.text if self.hover else p.muted),
                           font=kit.fonts["bold" if self.selected else "caption"])

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self._paint()

    def _click(self, _event=None) -> None:
        self.focus_set()
        self.command()

    def _enter(self, _event) -> None:
        self.hover = True
        self._paint()

    def _leave(self, _event) -> None:
        self.hover = False
        self._paint()


# ---------------------------------------------------------------------------
class ObjectTile(_CanvasWidget):
    """「小物件」的一格:image 是小物件的圖(滑過時出現刪除的 ×,點一下刪除);
    image=None 是「新增」那一格(+)。"""

    def __init__(self, parent, kit: Kit, image: Optional[Image.Image], command: Callable, size: int,
                 bg: Optional[str] = None):
        super().__init__(parent, kit, bg, width=size, height=size, cursor="hand2", takefocus=1)
        self.command, self.size, self.adding = command, size, image is None
        self._photo = None
        if image is not None:
            inner = size - kit.px(14)
            self._photo = to_photo(style.contain(image, inner, inner), kit.root)
        for sequence, handler in (("<Enter>", self._enter), ("<Leave>", self._leave),
                                  ("<ButtonRelease-1>", self._click), ("<KeyPress-space>", self._click)):
            self.bind(sequence, handler)
        self._paint()

    def _paint(self) -> None:
        p, kit, px = self.kit.p, self.kit, self.kit.px
        self.delete("all")
        size = self.size
        outline = (p.accent if self.adding else p.border_strong) if self.hover else p.border
        kit.draw_box(self, 0, 0, size, size, px(10), p.field, outline)
        if self.adding:
            self.create_image(size / 2, size / 2, image=kit.icon("plus", px(22), p.accent if self.hover else p.muted))
            return
        self.create_image(size / 2, size / 2, image=self._photo)
        if self.hover:
            badge = px(20)
            self.create_image(size - px(4), px(4), anchor="ne", image=kit.circle(badge, p.danger))
            self.create_image(size - px(4) - badge / 2, px(4) + badge / 2,
                              image=kit.icon("close", px(12), p.card))

    def _click(self, _event=None) -> None:
        self.command()

    def _enter(self, _event) -> None:
        self.hover = True
        self._paint()

    def _leave(self, _event) -> None:
        self.hover = False
        self._paint()


# ---------------------------------------------------------------------------
class ScreenTile(_CanvasWidget):
    """一個螢幕的選擇卡:依比例畫的螢幕形狀(直向就是直的)+ 編號、名稱、解析度,右上角打勾。"""

    def __init__(self, parent, kit: Kit, number: int, screen, variable: tk.BooleanVar,
                 command: Callable, width: int, enabled: bool = True, bg: Optional[str] = None):
        px = kit.px
        height = px(84)
        super().__init__(parent, kit, bg, width=width, height=height,
                         cursor="hand2" if enabled else "", takefocus=1 if enabled else 0)
        self.variable, self.command, self.enabled = variable, command, enabled
        self.size = (width, height)
        # 螢幕形狀:放進 52×44 的框裡,保持長寬比
        box_w, box_h = px(52), px(44)
        ratio = screen.width / max(1, screen.height)
        glyph_w, glyph_h = (box_w, max(px(18), int(box_w / ratio))) if ratio >= box_w / box_h \
            else (max(px(14), int(box_h * ratio)), box_h)
        self._glyph_size = (glyph_w, glyph_h)
        cx, cy = px(16) + box_w / 2, height / 2
        self._back = self.create_image(0, 0, anchor="nw")
        self._glyph = self.create_image(cx, cy, anchor="center")
        self._number = self.create_text(cx, cy, text=str(number), font=kit.fonts["bold"])
        x = px(16) + box_w + px(14)
        self._title = self.create_text(x, px(24), anchor="w", text=f"螢幕 {number}", font=kit.fonts["bold"])
        kind = ("主螢幕 · " if screen.primary else "") + ("直向" if screen.portrait else "橫向")
        self._kind = self.create_text(x, px(44), anchor="w", text=kind, font=kit.fonts["caption"])
        self._size = self.create_text(x, px(62), anchor="w", text=f"{screen.width} × {screen.height}",
                                      font=kit.fonts["caption"])
        self._check = self.create_image(width - px(12), px(12), anchor="ne")
        self._check_mark = self.create_image(width - px(12) - px(9), px(12) + px(9), anchor="center")
        self._watch(variable, self._paint)
        if enabled:
            for sequence, handler in (("<Enter>", self._enter), ("<Leave>", self._leave),
                                      ("<ButtonRelease-1>", self._click), ("<KeyPress-space>", self._click)):
                self.bind(sequence, handler)
        self._paint()

    def _paint(self) -> None:
        p, kit, px = self.kit.p, self.kit, self.kit.px
        on = bool(self.variable.get())
        lit = on and self.enabled
        width, height = self.size
        outline = p.accent if lit else (p.border_strong if self.hover else p.border)
        self.itemconfigure(self._back, image=kit.round_rect(width, height, px(10), p.accent_soft if lit else p.card,
                                                            outline, max(1, px(1))))
        glyph_w, glyph_h = self._glyph_size
        self.itemconfigure(self._glyph, image=kit.round_rect(
            glyph_w, glyph_h, px(4), p.accent if lit else p.track, None))
        self.itemconfigure(self._number, fill=p.on_accent if lit else p.muted)
        self.itemconfigure(self._title, fill=p.text if self.enabled else p.muted)
        self.itemconfigure(self._kind, fill=p.muted)
        self.itemconfigure(self._size, fill=p.muted)
        size = px(18)
        if on:
            self.itemconfigure(self._check, image=kit.circle(size, p.accent if self.enabled else p.subtle))
            self.itemconfigure(self._check_mark, image=kit.icon("check", px(13), p.on_accent if self.enabled else p.card))
        else:
            self.itemconfigure(self._check, image=kit.circle(size, None, p.border_strong, max(1, px(1.5))))
            self.itemconfigure(self._check_mark, image="")

    def _click(self, _event=None) -> None:
        self.focus_set()
        self.variable.set(not self.variable.get())
        self.command()

    def _enter(self, _event) -> None:
        self.hover = True
        self._paint()

    def _leave(self, _event) -> None:
        self.hover = False
        self._paint()


# ---------------------------------------------------------------------------
class NavItem(_CanvasWidget):
    """側邊導覽列的一項:圖示 + 文字;選到的有底色與左邊的強調色短線。"""

    def __init__(self, parent, kit: Kit, text: str, icon: str, command: Callable, bg: Optional[str] = None):
        super().__init__(parent, kit, bg, height=kit.px(40), width=kit.px(160), cursor="hand2", takefocus=1)
        self.text, self.icon_name, self.command = text, icon, command
        self.selected = False
        for sequence, handler in (("<Configure>", self._paint), ("<Enter>", self._enter), ("<Leave>", self._leave),
                                  ("<ButtonRelease-1>", self._click), ("<KeyPress-space>", self._click),
                                  ("<KeyPress-Return>", self._click)):
            self.bind(sequence, handler)

    def _paint(self, _event=None) -> None:
        p, kit, px = self.kit.p, self.kit, self.kit.px
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_reqheight()
        if width < 4:
            return
        if self.selected or self.hover:
            kit.draw_box(self, 0, 0, width, height, px(7), p.nav_selected if self.selected else p.nav_hover)
        if self.selected:
            self.create_image(px(1), height / 2, anchor="w",
                              image=kit.round_rect(px(3), px(18), px(1.5), p.accent))
        color = p.text if self.selected else p.muted
        self.create_image(px(14), height / 2, anchor="w", image=kit.icon(self.icon_name, px(18), color))
        self.create_text(px(44), height / 2, anchor="w", text=self.text, fill=color,
                         font=kit.fonts["bold" if self.selected else "body"])

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self._paint()

    def _click(self, _event=None) -> None:
        self.command()

    def _enter(self, _event) -> None:
        self.hover = True
        self._paint()

    def _leave(self, _event) -> None:
        self.hover = False
        self._paint()


# ---------------------------------------------------------------------------
class ScrollArea(tk.Frame):
    """可以上下捲動的區域(滑鼠滾輪,或拖右邊的細捲軸)。內容放在 area.inner。"""

    def __init__(self, parent, kit: Kit, width: int, bg: Optional[str] = None):
        bg = bg or bg_of(parent)
        super().__init__(parent, background=bg)
        self.kit = kit
        self.canvas = tk.Canvas(self, background=bg, highlightthickness=0, borderwidth=0, width=width,
                                yscrollincrement=kit.px(20))
        self.inner = tk.Frame(self.canvas, background=bg)
        self._window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.bar = tk.Canvas(self, background=bg, highlightthickness=0, borderwidth=0, width=kit.px(8))
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.bar.grid(row=0, column=1, sticky="ns", padx=(kit.px(4), 0))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas.configure(yscrollcommand=self._on_scroll)
        self._view = (0.0, 1.0)
        self._drag_from = None

        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.bar.bind("<Configure>", lambda _e: self._draw_bar())
        self.bar.bind("<ButtonPress-1>", self._bar_press)
        self.bar.bind("<B1-Motion>", self._bar_drag)
        # 滾輪事件掛在整個程式上,再看滑鼠是不是在這個區域裡
        # (Enter/Leave 在滑進子元件時也會觸發,不可靠)。
        # 用取代而不是附加:同一時間只有一個捲動區,不會重複綁定。
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_all(sequence, self._wheel)

    def _on_inner(self, _event=None) -> None:
        self.canvas.configure(scrollregion=(0, 0, self.inner.winfo_reqwidth(), self.inner.winfo_reqheight()))
        self._draw_bar()

    def recolor(self, mapping) -> None:
        self._draw_bar()

    def _on_canvas(self, event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)
        self._draw_bar()

    def _on_scroll(self, first, last) -> None:
        self._view = (float(first), float(last))
        self._draw_bar()

    def _scrollable(self) -> bool:
        return self.inner.winfo_reqheight() > self.canvas.winfo_height() + 1

    def _draw_bar(self) -> None:
        self.bar.delete("all")
        if not self._scrollable():
            return
        height = self.bar.winfo_height()
        first, last = self._view
        width = self.kit.px(4)
        x = self.bar.winfo_width() / 2
        top, bottom = first * height + width, max(first * height + width * 2, last * height - width)
        self.bar.create_line(x, top, x, bottom, width=width, capstyle="round", fill=self.kit.p.border_strong)

    def _bar_press(self, event) -> None:
        self._drag_from = (event.y, self._view[0])

    def _bar_drag(self, event) -> None:
        if self._drag_from and self._scrollable():
            start_y, start_first = self._drag_from
            self.canvas.yview_moveto(start_first + (event.y - start_y) / max(1, self.bar.winfo_height()))

    def _pointer_inside(self, event) -> bool:
        try:
            widget = self.winfo_containing(event.x_root, event.y_root)
        except (KeyError, tk.TclError):
            return False
        return widget is not None and not isinstance(widget, tk.Text) and str(widget).startswith(str(self))

    def _wheel(self, event) -> None:
        if not self.winfo_exists() or not self._scrollable() or not self._pointer_inside(event):
            return
        if getattr(event, "num", None) in (4, 5):          # X11
            steps = -3 if event.num == 4 else 3
        elif abs(event.delta) >= 120:                        # Windows:一格 120
            steps = int(-event.delta / 120 * 3)
        else:                                                # macOS:一格 1 左右
            steps = -event.delta
        self.canvas.yview_scroll(steps, "units")

    def to_top(self) -> None:
        self.canvas.yview_moveto(0)
