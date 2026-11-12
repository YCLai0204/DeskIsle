"""桌面排列的資料結構:畫面尺寸、螢幕、圖示。不碰任何作業系統 API。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Tuple

Rect = Tuple[int, int, int, int]


@dataclass(frozen=True)
class Screen:
    """一個螢幕;座標是圖片座標(以虛擬桌面左上角為原點的實體像素)。"""
    id: str           # 系統給的螢幕代碼;空字串 = 無法各自設定桌布
    left: int
    top: int
    width: int
    height: int
    primary: bool = False

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def portrait(self) -> bool:
        """直向螢幕。"""
        return self.height > self.width

    def describe(self, number: int) -> str:
        """給使用者看的名稱,例如「螢幕 2(主螢幕)· 1080×1920 直向」。"""
        name = f"螢幕 {number}" + ("(主螢幕)" if self.primary else "")
        return f"{name} · {self.width}×{self.height} {'直向' if self.portrait else '橫向'}"


@dataclass(frozen=True)
class DesktopIcon:
    """一個桌面圖示;座標是圖片座標。"""
    name: str
    left: int
    top: int
    right: int
    bottom: int

    @property
    def rect(self) -> Rect:
        return (self.left, self.top, self.right, self.bottom)


@dataclass(frozen=True)
class DesktopLayout:
    width: int
    height: int
    icons: Tuple[DesktopIcon, ...]
    icons_visible: bool = True
    screens: Tuple[Screen, ...] = ()   # 空 = 整張圖就是一個螢幕

    @property
    def rects(self) -> List[Rect]:
        return [icon.rect for icon in self.icons]

    @property
    def monitors(self) -> int:
        return len(self.screen_list())

    def screen_list(self) -> Tuple[Screen, ...]:
        return self.screens or (Screen("", 0, 0, self.width, self.height, True),)

    def selected_screens(self, ids: Iterable[str]) -> List[Screen]:
        """設定裡選的螢幕。沒有選、或選的螢幕都不在了 → 全部。"""
        wanted = set(ids)
        chosen = [s for s in self.screen_list() if s.id and s.id in wanted]
        return chosen or list(self.screen_list())

    def can_choose_screens(self) -> bool:
        """能不能各自設定每個螢幕的桌布(有多個螢幕,而且系統給了每個螢幕代碼)。"""
        screens = self.screen_list()
        return len(screens) > 1 and all(s.id for s in screens)

    def signature(self) -> tuple:
        """排列的特徵值:只要會影響畫面的東西有變,這個值就會變。"""
        return (self.width, self.height, self.screen_list(), tuple(sorted(i.rect for i in self.icons)))


def screen_rects(layout: DesktopLayout, screen: Screen, ratio: float = 1.0) -> List[Rect]:
    """落在這個螢幕裡的圖示矩形,換成以螢幕左上角為原點、再乘上 ratio 的座標。"""
    rects = []
    for left, top, right, bottom in layout.rects:
        left, top = max(left, screen.left) - screen.left, max(top, screen.top) - screen.top
        right, bottom = min(right, screen.right) - screen.left, min(bottom, screen.bottom) - screen.top
        if right - left < 2 or bottom - top < 2:
            continue
        l, t = int(left * ratio), int(top * ratio)
        rects.append((l, t, max(int(right * ratio), l + 1), max(int(bottom * ratio), t + 1)))
    return rects

