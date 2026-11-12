"""地形與繪圖的測試。不需要 Windows,任何作業系統都能跑。

執行:python -m unittest discover -s tests -v
"""
import random
import unittest

import numpy as np

from deskisle import decor
from deskisle.render import render
from deskisle.terrain import fbm, shore_field
from deskisle.themes import THEMES, get_theme

W, H = 640, 360
PARAMS = dict(margin=46.0, blend=26.0, roughness=22.0, seed=7)


def random_rects(rng, count):
    rects = []
    for _ in range(count):
        left = rng.randrange(0, W - 76)
        top = rng.randrange(0, H - 85)
        rects.append((left, top, left + 76, top + rng.choice((70, 85))))
    return rects


class ShoreFieldTests(unittest.TestCase):
    def test_shape_and_dtype(self):
        field = shore_field(W, H, [(10, 10, 86, 80)], **PARAMS)
        self.assertEqual(field.shape, (H, W))
        self.assertEqual(field.dtype, np.float32)

    def test_odd_size_is_not_rounded(self):
        # 寬高不是 4 的倍數時,輸出仍要是原尺寸
        field = shore_field(641, 363, [(10, 10, 86, 80)], **PARAMS)
        self.assertEqual(field.shape, (363, 641))

    def test_icons_are_always_on_land(self):
        rng = random.Random(1)
        for trial in range(25):
            rects = random_rects(rng, rng.randrange(1, 30))
            # 故意把起伏調到遠超過留白,確認上限有生效
            field = shore_field(W, H, rects, margin=46.0, blend=26.0, roughness=500.0, seed=trial)
            for left, top, right, bottom in rects:
                self.assertLess(
                    float(field[top:bottom, left:right].max()), 0.0,
                    f"第 {trial} 次:圖示 {(left, top, right, bottom)} 有部分落在水裡",
                )

    def test_far_from_icons_is_water(self):
        field = shore_field(W, H, [(0, 0, 76, 70)], **PARAMS)
        self.assertGreater(float(field[H - 1, W - 1]), 100.0)

    def test_no_icons_is_all_water(self):
        field = shore_field(W, H, [], **PARAMS)
        self.assertGreater(float(field.min()), 0.0)

    def test_nearby_icons_merge_and_distant_icons_do_not(self):
        y0, y1 = 140, 210
        mid_row = (y0 + y1) // 2
        params = dict(margin=46.0, blend=26.0, roughness=0.0, seed=7)

        near = shore_field(W, H, [(100, y0, 176, y1), (236, y0, 312, y1)], **params)  # 間隔 60
        self.assertLess(float(near[mid_row, 176:236].max()), 0.0, "相近的圖示應該連成一片陸地")

        far = shore_field(W, H, [(40, y0, 116, y1), (440, y0, 516, y1)], **params)  # 間隔 324
        self.assertGreater(float(far[mid_row, 278]), 0.0, "相距很遠的圖示之間應該是水")

    def test_deterministic(self):
        rects = random_rects(random.Random(3), 12)
        a = shore_field(W, H, rects, **PARAMS)
        b = shore_field(W, H, rects, **PARAMS)
        self.assertTrue(np.array_equal(a, b))

    def test_moving_an_icon_only_changes_terrain_nearby(self):
        fixed = [(20, 20, 96, 90), (20, 120, 96, 190)]
        before = shore_field(W, H, fixed + [(520, 40, 596, 110)], **PARAMS)
        after = shore_field(W, H, fixed + [(520, 240, 596, 310)], **PARAMS)
        # 左側離被移動的圖示 300 像素以上:海岸線位置的變化應小於 1 像素
        self.assertLess(float(np.abs(before[:, :200] - after[:, :200]).max()), 1.0)
        # 被移動的圖示附近當然要變
        self.assertGreater(float(np.abs(before[:, 480:] - after[:, 480:]).max()), 50.0)


class NoiseTests(unittest.TestCase):
    def test_range_and_determinism(self):
        a = fbm(300, 200, seed=5, cell=40)
        self.assertEqual(a.shape, (200, 300))
        self.assertGreaterEqual(float(a.min()), -1.0)
        self.assertLessEqual(float(a.max()), 1.0)
        self.assertGreater(float(a.std()), 0.1, "雜訊不該是一片平坦")
        self.assertTrue(np.array_equal(a, fbm(300, 200, seed=5, cell=40)))
        self.assertFalse(np.array_equal(a, fbm(300, 200, seed=6, cell=40)))


class RenderTests(unittest.TestCase):
    RECTS = [(0, 5, 76, 75), (0, 105, 76, 190), (76, 5, 152, 75)]

    def test_every_theme_renders(self):
        for key, theme in THEMES.items():
            image = render(W, H, self.RECTS, theme, **PARAMS)
            self.assertEqual(image.size, (W, H), key)
            self.assertEqual(image.mode, "RGB", key)

    def test_beach_is_sand_under_icons_and_blue_far_away(self):
        pixels = np.asarray(render(W, H, self.RECTS, get_theme("beach"), **PARAMS)).astype(int)
        r, g, b = pixels[40, 40]            # 第一個圖示正中央
        self.assertTrue(r > g > b, f"圖示底下應該是沙色,實際 {(r, g, b)}")
        r, g, b = pixels[H - 10, W - 10]    # 右下角,遠離所有圖示
        self.assertTrue(b > g > r, f"遠處應該是海水藍,實際 {(r, g, b)}")

    def test_deterministic(self):
        theme = get_theme("beach")
        a = np.asarray(render(W, H, self.RECTS, theme, **PARAMS))
        b = np.asarray(render(W, H, self.RECTS, theme, **PARAMS))
        self.assertTrue(np.array_equal(a, b))

    def test_seed_changes_the_shoreline(self):
        theme = get_theme("beach")
        a = np.asarray(render(W, H, self.RECTS, theme, margin=46.0, blend=26.0, roughness=22.0, seed=1))
        b = np.asarray(render(W, H, self.RECTS, theme, margin=46.0, blend=26.0, roughness=22.0, seed=2))
        self.assertFalse(np.array_equal(a, b))

    def test_ui_scale_keeps_icons_on_land(self):
        # 150% 縮放:圖示矩形變大,留白等參數也跟著放大
        rects = [(0, 8, 114, 113), (114, 8, 228, 113)]
        pixels = np.asarray(render(W, H, rects, get_theme("beach"), scale=1.5, **PARAMS)).astype(int)
        r, g, b = pixels[60, 114]
        self.assertTrue(r > g > b)

    def test_debug_draws_icon_outlines(self):
        theme = get_theme("beach")
        plain = np.asarray(render(W, H, self.RECTS, theme, **PARAMS))
        debug = np.asarray(render(W, H, self.RECTS, theme, debug=True, **PARAMS))
        self.assertEqual(tuple(debug[5, 30]), (255, 0, 80))       # 第一個圖示的上緣
        self.assertTrue(np.array_equal(plain[200:, 300:], debug[200:, 300:]))

    def test_unknown_theme_is_rejected(self):
        with self.assertRaises(ValueError):
            get_theme("nope")

    def test_there_is_a_space_theme(self):
        self.assertIn("cosmos", THEMES)
        pixels = np.asarray(render(W, H, self.RECTS, get_theme("cosmos"), **PARAMS)).astype(int)
        self.assertLess(int(pixels[H - 10, W - 10].sum()), 200, "遠處應該是幾乎全黑的太空")

    def test_decorations_can_be_turned_off(self):
        theme = get_theme("beach")
        with_decor = np.asarray(render(W, H, self.RECTS, theme, **PARAMS))
        without = np.asarray(render(W, H, self.RECTS, theme, decorations=0, **PARAMS))
        self.assertFalse(np.array_equal(with_decor, without))
        again = np.asarray(render(W, H, self.RECTS, theme, decorations=0, **PARAMS))
        self.assertTrue(np.array_equal(without, again))


class DecorationTests(unittest.TestCase):
    BIG_W, BIG_H = 1280, 720

    def _field(self, rects, seed=7):
        return shore_field(self.BIG_W, self.BIG_H, rects, margin=46.0, blend=26.0, roughness=22.0, seed=seed)

    def _rects(self, seed, count=30):
        rng = random.Random(seed)
        out = []
        for _ in range(count):
            left = rng.randrange(0, self.BIG_W - 76)
            top = rng.randrange(0, self.BIG_H - 85)
            out.append((left, top, left + 76, top + 85))
        return out

    def test_every_theme_has_land_and_water_decorations(self):
        for key, theme in THEMES.items():
            self.assertTrue(any(rule.hi <= 0 for rule in theme.decor), f"{key} 沒有陸地裝飾物")
            self.assertTrue(any(rule.lo >= 0 for rule in theme.decor), f"{key} 沒有水域裝飾物")
            for rule in theme.decor:
                self.assertIn(rule.kind, decor.SPRITES, f"{key} 用了不存在的裝飾物 {rule.kind}")
                self.assertLess(rule.lo, rule.hi)

    def test_every_sprite_draws_something_at_the_requested_size(self):
        for kind in decor.SPRITES:
            for variant in range(decor.VARIANTS):
                image = decor.sprite(kind, 40, variant)
                self.assertEqual((image.size, image.mode), ((40, 40), "RGBA"), kind)
                self.assertGreater(np.asarray(image)[..., 3].max(), 100, f"{kind} 是空白的")

    def test_decorations_never_cover_icons_or_each_other(self):
        for key, theme in THEMES.items():
            for trial in range(4):
                rects = self._rects(trial)
                placements = decor.place(self._field(rects), rects, theme.decor, seed=7, density=2.0)
                self.assertGreater(len(placements), 5, key)
                for p in placements:
                    half = p.size / 2
                    for left, top, right, bottom in rects:
                        overlap = (p.x + half > left and p.x - half < right
                                   and p.y + half > top and p.y - half < bottom)
                        self.assertFalse(overlap, f"{key}:{p.rule.kind} 蓋到圖示 {(left, top, right, bottom)}")
                for i, a in enumerate(placements):
                    for b in placements[i + 1:]:
                        gap = ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5
                        self.assertGreaterEqual(gap, (a.size + b.size) * 0.4 - 1e-6, f"{key}:裝飾物重疊")

    def test_decorations_stay_in_their_zone(self):
        rects = self._rects(1)
        field = self._field(rects)
        for theme in THEMES.values():
            for p in decor.place(field, rects, theme.decor, seed=7):
                self.assertTrue(p.rule.lo <= float(field[p.y, p.x]) < p.rule.hi)

    def test_placement_is_deterministic_and_density_zero_means_none(self):
        rects = self._rects(2)
        field = self._field(rects)
        rules = get_theme("beach").decor
        self.assertEqual(decor.place(field, rects, rules, seed=7), decor.place(field, rects, rules, seed=7))
        self.assertNotEqual(decor.place(field, rects, rules, seed=7), decor.place(field, rects, rules, seed=8))
        self.assertEqual(decor.place(field, rects, rules, seed=7, density=0), [])

    def test_moving_an_icon_keeps_far_away_decorations(self):
        fixed = [(20, 20, 96, 105), (20, 140, 96, 225), (120, 20, 196, 105)]
        rules = get_theme("beach").decor
        a_rects = fixed + [(1100, 60, 1176, 145)]
        b_rects = fixed + [(1100, 560, 1176, 645)]
        a = decor.place(self._field(a_rects), a_rects, rules, seed=7)
        b = decor.place(self._field(b_rects), b_rects, rules, seed=7)
        near_fixed = lambda ps: [(p.rule.kind, p.x, p.y, p.size) for p in ps if p.x < 450]
        self.assertGreater(len(near_fixed(a)), 2)
        self.assertEqual(near_fixed(a), near_fixed(b))


if __name__ == "__main__":
    unittest.main()
