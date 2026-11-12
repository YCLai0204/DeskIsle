"""設定介面的自繪元件:卡片、按鈕、開關、滑桿、標籤、主題縮圖、螢幕選擇、導覽項目、捲動區。

全部畫在 tk.Canvas 上;圓角、圓點用 style.py 以 Pillow 畫的反鋸齒圖片,
所以在淺色、深色、高 DPI 下都乾淨,而且不需要額外套件。
每個元件都可以用鍵盤操作(Tab 移動,空白鍵/Enter 按下,左右鍵調整滑桿)。
"""
from __future__ import annotations

import base64
import io
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
        p, px = kit.p, kit.px
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
        self._colors = {
            "primary": {"normal": (p.accent, None, p.on_accent), "hover": (p.accent_hover, None, p.on_accent),
                        "pressed": (p.accent_press, None, p.on_accent), "disabled": (p.track, None, p.subtle)},
            "secondary": {"normal": (p.card, p.border_strong, p.text), "hover": (p.card_hover, p.border_strong, p.text),
                          "pressed": (p.bg, p.border, p.muted), "disabled": (p.card, p.border, p.subtle)},
            "ghost": {"normal": (None, None, p.muted), "hover": (p.nav_hover, None, p.text),
                      "pressed": (p.nav_selected, None, p.text), "disabled": (None, None, p.subtle)},
            "danger": {"normal": (None, None, p.muted), "hover": (p.nav_hover, None, p.danger),
                       "pressed": (p.nav_selected, None, p.danger), "disabled": (None, None, p.subtle)},
        }[kind]
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
class Pill(_CanvasWidget):
    """小標籤(例如「尚未套用」)。沒有文字時不佔空間。"""

    def __init__(self, parent, kit: Kit, bg: Optional[str] = None):
        super().__init__(parent, kit, bg, width=1, height=kit.px(24))
        self.text = ""

    def show(self, text: str, color: str, fill: str, dot: bool = True) -> None:
        kit = self.kit
        self.text = text
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
        # (Enter/Leave 在滑進子元件時也會觸發,不可靠)
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_all(sequence, self._wheel, add="+")

    def _on_inner(self, _event) -> None:
        self.canvas.configure(scrollregion=(0, 0, self.inner.winfo_reqwidth(), self.inner.winfo_reqheight()))
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
