"""主題:一條色帶、幾個質感參數,加上一組裝飾物規則。

色帶控制點是 (離海岸線的距離, 顏色)。距離為負是陸地、為正是「水域」
(海、湖、熔岩、太空、沙漠……),單位是 100% 縮放下的像素。
要新增主題,照樣寫一個 Theme 加進 THEMES 即可。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, Tuple

from .decor import DecorRule as D

Color = Tuple[int, int, int]
FAR = 100000.0   # 「一路到最遠」


@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    description: str
    stops: Tuple[Tuple[float, Color], ...]  # 依距離由小到大
    foam: Color                 # 浪花(或裂紋、光暈)的顏色
    shore_foam: float = 0.9     # 緊貼海岸那一圈的濃度 0~1
    wave_strength: float = 0.55  # 外圈波紋的濃度 0~1
    wave_length: float = 26.0   # 波紋間距
    wave_fade: float = 75.0     # 波紋離岸多遠後淡出
    land_grain: float = 0.035   # 陸地細顆粒
    land_mottle: float = 0.045  # 陸地大塊色斑
    land_relief: float = 0.10   # 陸地起伏的光影
    water_grain: float = 0.008  # 水域細顆粒(同時消除漸層色階)
    water_shimmer: float = 0.035  # 水域明暗變化
    water_relief: float = 0.0   # 水域起伏的光影(沙丘、熔岩表面)
    deep_variation: float = 70.0  # 深水區取色位置的擾動(像素)
    tint: Tuple[Color, ...] = ()  # 水域的彩色雲霧(星雲);空 = 沒有
    tint_strength: float = 0.0
    sparkles: float = 0.0       # 水域的光點密度(每一萬像素幾顆)
    sparkle_colors: Tuple[Color, ...] = ((255, 255, 255),)
    decor: Tuple[D, ...] = ()   # 裝飾物規則,越前面越優先
    companions: Tuple[Tuple[str, D], ...] = ()   # 依檔案類型放在圖示旁邊的裝飾物(見 COMPANIONS)


_WET_ROCK = ((96, 100, 104), (134, 138, 140), (62, 66, 72))
_CORAL_ORANGE = ((244, 150, 84), (255, 208, 150))
_CORAL_PURPLE = ((176, 116, 214), (224, 186, 244))

BEACH = Theme(
    key="beach",
    label="沙灘",
    description="沙灘與海洋:椰子樹、貝殼、海星、珊瑚、魚群、小船",
    stops=(
        (-170, (233, 209, 152)),
        (-48, (228, 201, 142)),
        (-16, (210, 181, 124)),
        (-3, (184, 155, 104)),
        (2, (170, 224, 210)),
        (22, (96, 206, 202)),
        (70, (40, 168, 196)),
        (160, (22, 122, 172)),
        (320, (13, 84, 140)),
        (620, (9, 58, 108)),
    ),
    foam=(255, 255, 255),
    decor=(
        D("palm", -44, -13, 0.34, (40, 54)),
        D("starfish", -14, -3, 0.10, (12, 16)),
        D("shell", -26, -4, 0.14, (10, 14)),
        D("rock", -34, -4, 0.08, (14, 22)),
        D("rock", 4, 26, 0.05, (14, 26), _WET_ROCK),
        D("coral", 14, 100, 0.09, (22, 38), shadow=False, alpha=0.86),
        D("coral", 14, 100, 0.08, (22, 36), _CORAL_ORANGE, shadow=False, alpha=0.86),
        D("coral", 30, 120, 0.06, (20, 34), _CORAL_PURPLE, shadow=False, alpha=0.8),
        D("fish", 60, 420, 0.07, (30, 44), shadow=False, alpha=0.5),
        D("boat", 150, FAR, 0.014, (40, 52)),
    ),
)

MEADOW = Theme(
    key="meadow",
    label="草地",
    description="草地與湖泊:樹木、花叢、荷葉、魚群",
    stops=(
        (-170, (78, 132, 58)),
        (-48, (96, 150, 66)),
        (-16, (122, 166, 78)),
        (-3, (150, 140, 96)),
        (2, (132, 196, 196)),
        (22, (78, 164, 188)),
        (80, (48, 124, 170)),
        (200, (32, 92, 142)),
        (500, (22, 66, 110)),
    ),
    foam=(232, 246, 248),
    shore_foam=0.55,
    wave_strength=0.28,
    wave_length=30.0,
    wave_fade=55.0,
    land_grain=0.05,
    land_mottle=0.09,
    land_relief=0.16,
    decor=(
        D("tree", -46, -13, 0.30, (34, 50)),
        D("flowers", -42, -5, 0.26, (18, 26), shadow=False),
        D("rock", -30, -3, 0.07, (14, 22)),
        D("rock", 4, 30, 0.04, (14, 24), _WET_ROCK),
        D("lilypad", 8, 80, 0.22, (16, 28), shadow=False),
        D("fish", 60, 420, 0.06, (30, 42), ((18, 52, 84),), shadow=False, alpha=0.45),
        D("boat", 130, FAR, 0.010, (38, 48)),
    ),
)

_BASALT = ((70, 62, 62), (100, 90, 88), (30, 26, 28))
_CRUST = ((54, 40, 38), (88, 62, 50), (24, 16, 16))

VOLCANO = Theme(
    key="volcano",
    label="火山",
    description="玄武岩與熔岩:岩塊、發光裂縫、漂浮的岩殼",
    stops=(
        (-170, (36, 33, 36)),
        (-48, (46, 41, 42)),
        (-16, (66, 46, 40)),
        (-3, (126, 54, 28)),
        (2, (255, 232, 150)),
        (14, (255, 172, 44)),
        (50, (238, 98, 22)),
        (140, (178, 46, 18)),
        (320, (108, 26, 20)),
        (620, (62, 18, 20)),
    ),
    foam=(255, 240, 180),
    shore_foam=0.7,
    wave_strength=0.42,
    wave_length=34.0,
    wave_fade=130.0,
    land_grain=0.06,
    land_mottle=0.10,
    land_relief=0.22,
    water_shimmer=0.07,
    water_relief=0.05,
    deep_variation=110.0,
    decor=(
        D("crack", -42, -10, 0.16, (30, 46), shadow=False),
        D("rock", -44, -5, 0.24, (16, 32), _BASALT),
        D("rock", 22, FAR, 0.10, (16, 42), _CRUST, shadow=False),
    ),
)

_MOON_ROCK = ((132, 132, 142), (176, 176, 186), (84, 84, 96))
_ASTEROID = ((104, 96, 92), (150, 140, 132), (58, 54, 56))

COSMOS = Theme(
    key="cosmos",
    label="宇宙",
    description="月面與星空:隕石坑、星雲、行星、星系、小行星",
    stops=(
        (-170, (150, 150, 160)),
        (-48, (140, 140, 151)),
        (-16, (122, 123, 136)),
        (-3, (98, 100, 118)),
        (2, (150, 200, 255)),
        (10, (60, 92, 172)),
        (40, (26, 34, 90)),
        (120, (14, 16, 54)),
        (320, (8, 8, 32)),
        (620, (4, 4, 18)),
    ),
    foam=(190, 220, 255),
    shore_foam=0.65,
    wave_strength=0.11,
    wave_length=36.0,
    wave_fade=120.0,
    land_grain=0.05,
    land_mottle=0.08,
    land_relief=0.16,
    water_grain=0.006,
    water_shimmer=0.0,
    deep_variation=80.0,
    tint=((132, 44, 160), (30, 96, 170)),
    tint_strength=0.5,
    sparkles=9.0,
    sparkle_colors=((255, 255, 255), (190, 214, 255), (255, 236, 200)),
    decor=(
        D("crater", -46, -7, 0.42, (16, 38), shadow=False, spin=0.0),
        D("rock", -40, -4, 0.08, (12, 20), _MOON_ROCK),
        D("planet", 130, FAR, 0.006, (48, 86), shadow=False, spin=0.12),
        D("planet", 130, FAR, 0.004, (44, 76), ((92, 150, 214), (60, 110, 180), (200, 224, 246)),
          shadow=False, spin=0.12),
        D("planet", 130, FAR, 0.004, (40, 64), ((196, 92, 78), (150, 62, 60), (236, 190, 160)),
          shadow=False, spin=0.12),
        D("galaxy", 170, FAR, 0.005, (72, 112), shadow=False),
        D("galaxy", 170, FAR, 0.003, (64, 96), ((255, 236, 244), (236, 150, 220)), shadow=False),
        D("glint", 30, FAR, 0.035, (14, 26), shadow=False, spin=0.0),
        D("glint", 30, FAR, 0.025, (12, 22), ((180, 210, 255),), shadow=False, spin=0.0),
        D("glint", 30, FAR, 0.020, (12, 20), ((255, 226, 180),), shadow=False, spin=0.0),
        D("rock", 30, FAR, 0.035, (10, 24), _ASTEROID, shadow=False),
    ),
)

ARCTIC = Theme(
    key="arctic",
    label="極地",
    description="雪原與極海:雪松、岩石、浮冰",
    stops=(
        (-170, (214, 226, 238)),
        (-48, (206, 220, 234)),
        (-16, (190, 210, 228)),
        (-3, (160, 196, 220)),
        (2, (150, 214, 226)),
        (20, (74, 160, 186)),
        (70, (34, 110, 146)),
        (170, (20, 74, 110)),
        (340, (12, 50, 84)),
        (620, (8, 36, 64)),
    ),
    foam=(255, 255, 255),
    shore_foam=0.85,
    wave_strength=0.4,
    land_grain=0.018,
    land_mottle=0.03,
    land_relief=0.10,
    decor=(
        D("pine", -46, -13, 0.30, (30, 44)),
        D("rock", -34, -4, 0.09, (14, 24), ((120, 130, 144), (168, 178, 190), (78, 86, 100))),
        D("floe", 12, 60, 0.20, (18, 34), shadow=False),
        D("floe", 60, FAR, 0.11, (26, 60), shadow=False),
        D("fish", 70, 420, 0.03, (30, 42), ((10, 40, 64),), shadow=False, alpha=0.45),
    ),
)

_SANDSTONE = ((176, 128, 84), (208, 162, 112), (126, 86, 58))
_DRY_SHRUB = ((122, 106, 62), (152, 136, 80), (184, 168, 106))

DESERT = Theme(
    key="desert",
    label="沙漠綠洲",
    description="綠洲與沙丘:椰子樹、花叢、仙人掌、砂岩",
    stops=(
        (-170, (84, 138, 62)),
        (-48, (104, 152, 68)),
        (-16, (134, 160, 80)),
        (-3, (160, 150, 96)),
        (2, (206, 176, 120)),
        (24, (222, 188, 126)),
        (90, (226, 180, 112)),
        (220, (214, 162, 96)),
        (480, (200, 146, 86)),
        (700, (190, 136, 82)),
    ),
    foam=(246, 222, 172),
    shore_foam=0.0,
    wave_strength=0.34,
    wave_length=44.0,
    wave_fade=1200.0,
    land_grain=0.05,
    land_mottle=0.09,
    land_relief=0.16,
    water_grain=0.03,
    water_shimmer=0.05,
    water_relief=0.12,
    deep_variation=140.0,
    decor=(
        D("palm", -46, -13, 0.30, (38, 52)),
        D("flowers", -42, -5, 0.18, (18, 24), shadow=False),
        D("cactus", 12, FAR, 0.07, (20, 32)),
        D("rock", 8, FAR, 0.07, (14, 34), _SANDSTONE),
        D("tree", 16, FAR, 0.05, (16, 26), _DRY_SHRUB),
    ),
)

NIGHT = Theme(
    key="night",
    label="夜晚海灘",
    description="月光下的沙灘:發光的浪花、水母、深色的椰子樹",
    stops=(
        (-170, (92, 88, 100)),
        (-48, (84, 80, 94)),
        (-16, (68, 66, 84)),
        (-3, (50, 52, 74)),
        (2, (110, 236, 224)),
        (10, (36, 128, 150)),
        (40, (18, 62, 104)),
        (130, (10, 34, 72)),
        (320, (6, 20, 48)),
        (620, (4, 12, 32)),
    ),
    foam=(150, 255, 238),
    shore_foam=0.8,
    wave_strength=0.5,
    wave_fade=95.0,
    land_grain=0.04,
    water_shimmer=0.05,
    tint=((20, 70, 96), (16, 30, 96)),
    tint_strength=0.25,
    sparkles=2.5,
    sparkle_colors=((150, 255, 238), (210, 230, 255)),
    decor=(
        D("palm", -44, -13, 0.32, (40, 54), ((14, 50, 44), (30, 84, 64), (58, 46, 40))),
        D("rock", -34, -4, 0.09, (14, 22), ((70, 70, 84), (104, 104, 120), (40, 40, 54))),
        D("starfish", -14, -3, 0.08, (12, 16), ((150, 92, 110), (196, 140, 150))),
        D("orb", 26, 420, 0.09, (20, 36), shadow=False),
        D("orb", 26, 420, 0.04, (18, 30), ((190, 150, 255),), shadow=False),
        D("boat", 150, FAR, 0.012, (40, 52), ((44, 36, 40), (90, 78, 76), (150, 160, 190))),
    ),
)

# ---------------------------------------------------------------------------
# 依檔案類型放在圖示旁邊的裝飾物:檔案類型 → (裝飾物, 地帶下限, 地帶上限, 大小範圍)
# 地帶是離海岸線的距離(負 = 陸地);會在圖示四周找第一個落在這個地帶的空位。
# ---------------------------------------------------------------------------
COMPANIONS = {
    "beach": {"folder": ("palm", -46, -8, (38, 48)), "image": ("shell", -36, -2, (15, 19)),
              "document": ("starfish", -36, -2, (15, 19)), "shortcut": ("boat", 14, 110, (34, 42)),
              "app": ("coral", 10, 100, (26, 32)), "media": ("fish", 20, 150, (28, 34))},
    "meadow": {"folder": ("tree", -46, -8, (34, 44)), "image": ("flowers", -40, -2, (20, 26)),
               "document": ("rock", -36, -2, (15, 20)), "shortcut": ("boat", 14, 110, (32, 40)),
               "app": ("lilypad", 8, 100, (20, 26)), "media": ("fish", 20, 150, (26, 32))},
    "volcano": {"folder": ("crack", -46, -8, (30, 40)), "image": ("rock", -40, -2, (18, 24)),
                "document": ("rock", -40, -2, (13, 17)), "shortcut": ("rock", 22, 150, (20, 28)),
                "app": ("crack", -46, -8, (24, 30)), "media": ("rock", 22, 150, (14, 20))},
    "cosmos": {"folder": ("crater", -46, -6, (26, 34)), "image": ("planet", 30, 160, (28, 36)),
               "document": ("rock", -40, -2, (13, 18)), "shortcut": ("glint", 24, 160, (18, 24)),
               "app": ("galaxy", 40, 180, (40, 52)), "media": ("planet", 30, 160, (22, 28))},
    "arctic": {"folder": ("pine", -46, -8, (32, 42)), "image": ("floe", 12, 100, (22, 30)),
               "document": ("rock", -36, -2, (15, 20)), "shortcut": ("floe", 12, 100, (28, 36)),
               "app": ("pine", -46, -8, (26, 32)), "media": ("fish", 20, 150, (26, 32))},
    "desert": {"folder": ("palm", -46, -8, (38, 48)), "image": ("flowers", -40, -2, (18, 24)),
               "document": ("rock", -36, -2, (15, 20)), "shortcut": ("cactus", 12, 150, (22, 30)),
               "app": ("cactus", 12, 150, (18, 24)), "media": ("tree", 16, 150, (18, 24))},
    "night": {"folder": ("palm", -46, -8, (38, 48)), "image": ("starfish", -36, -2, (15, 19)),
              "document": ("rock", -36, -2, (15, 20)), "shortcut": ("boat", 14, 110, (34, 42)),
              "app": ("orb", 24, 150, (22, 30)), "media": ("orb", 24, 150, (18, 24))},
}

# 介面上顯示用的裝飾物名稱
DECOR_LABELS = {
    "palm": "椰子樹", "rock": "岩石", "starfish": "海星", "shell": "貝殼", "coral": "珊瑚", "fish": "魚",
    "boat": "小船", "tree": "樹", "flowers": "花叢", "lilypad": "荷葉", "crater": "隕石坑", "planet": "行星",
    "galaxy": "星系", "glint": "星光", "cactus": "仙人掌", "floe": "浮冰", "pine": "雪松", "crack": "發光裂縫",
    "orb": "水母",
}


def _with_companions(theme: Theme) -> Theme:
    """依 COMPANIONS 建立規則;配色、影子、旋轉沿用主題裡同一種裝飾物的設定,看起來才一致。"""
    rules = []
    for file_kind, (kind, lo, hi, size) in COMPANIONS.get(theme.key, {}).items():
        like = next((r for r in theme.decor if r.kind == kind), None)
        extra = dict(colors=like.colors, shadow=like.shadow, spin=like.spin, alpha=like.alpha) if like else {}
        rules.append((file_kind, D(kind, lo, hi, 1.0, size, **extra)))
    return replace(theme, companions=tuple(rules))


THEMES: Dict[str, Theme] = {
    t.key: _with_companions(t) for t in (BEACH, MEADOW, VOLCANO, COSMOS, ARCTIC, DESERT, NIGHT)
}
DEFAULT_THEME = BEACH.key


def get_theme(key: str) -> Theme:
    try:
        return THEMES[key]
    except KeyError:
        raise ValueError(f"沒有 '{key}' 這個主題,可用的主題:{', '.join(THEMES)}") from None
