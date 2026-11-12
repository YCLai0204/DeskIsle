"""「圖片」頁:海洋與陸地的照片/取色、小物件、舊設定檔的轉換。任何作業系統都能跑。

執行:python -m unittest discover -s tests -v
"""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from deskisle.config import Config, load_config
from deskisle.engine import decor, photo
from deskisle.engine.render import render
from deskisle.engine.terrain import shore_field
from deskisle.engine.themes import get_theme

MAGENTA = (250, 0, 250)
GREEN = (0, 220, 60)
RECT = [(140, 90, 180, 130)]           # 一個圖示在中間;陸地在它周圍,畫面邊緣是海
LAND_POINT, SEA_POINT = (160, 110), (5, 5)


def _close(color, target, tolerance=40):
    return all(abs(a - b) <= tolerance for a, b in zip(color, target))


def _layer(color):
    return np.full((220, 320, 3), color, dtype=np.float32)


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        photo.clear_cache()

    def test_background_import_makes_an_rgb_copy_named_by_content(self):
        source = self.root / "透明.png"
        Image.new("RGBA", (40, 20), (255, 0, 0, 0)).save(source)
        first = photo.import_image(source, self.root / "images")
        self.assertEqual(first, photo.import_image(source, self.root / "images"))   # 同一張圖只存一份
        source.unlink()                                                              # 原檔不見也沒關係
        image = photo.load(str(first))
        self.assertEqual((image.mode, image.size), ("RGB", (40, 20)))
        self.assertGreater(min(image.getpixel((5, 5))), 240)                        # 透明的地方墊白色

    def test_object_import_keeps_transparency_and_trims_empty_edges(self):
        source = self.root / "星球.png"
        image = Image.new("RGBA", (100, 80), (0, 0, 0, 0))
        image.paste((200, 100, 50, 255), (30, 20, 60, 50))
        image.save(source)
        target = photo.import_object(source, self.root / "objects")
        self.assertEqual(target.suffix, ".png")
        loaded = photo.load_object(str(target))
        self.assertEqual((loaded.mode, loaded.size), ("RGBA", (30, 30)))

    def test_fully_transparent_or_broken_files_are_rejected(self):
        empty = self.root / "空.png"
        Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(empty)
        broken = self.root / "壞掉.jpg"
        broken.write_bytes(b"not an image")
        with self.assertRaises(ValueError):
            photo.import_object(empty, self.root / "objects")
        with self.assertRaises(ValueError):
            photo.import_image(broken, self.root / "images")
        self.assertIsNone(photo.load(str(broken)))
        self.assertIsNone(photo.load(""))

    def test_only_the_newest_images_are_kept(self):
        folder = self.root / "images"
        for i in range(photo.KEEP_IMAGES + 2):
            source = self.root / f"{i}.png"
            Image.new("RGB", (8, 8), (i * 20, 0, 0)).save(source)
            photo.import_image(source, folder)
        self.assertEqual(len(list(folder.glob("custom_*.jpg"))), photo.KEEP_IMAGES)


class ShapeTests(unittest.TestCase):
    def test_cover_fills_and_crops_the_middle(self):
        image = Image.new("RGB", (300, 100), (255, 0, 0))
        image.paste((0, 0, 255), (100, 0, 200, 100))             # 中間三分之一是藍色
        layer = photo.cover(image, 50, 50)
        self.assertEqual(layer.shape, (50, 50, 3))
        self.assertEqual(tuple(layer[25, 25].astype(int)), (0, 0, 255))

    def test_cover_never_fails_on_rounding(self):
        # 3840×2400 縮到預覽大小時,浮點誤差曾讓裁切框變成負數而出錯
        image = Image.new("RGB", (3840, 2400))
        for width in range(100, 700, 13):
            for height in (56, 135, 281, 401):
                self.assertEqual(photo.cover(image, width, height).shape, (height, width, 3))

    def test_circle_shape_cuts_a_round_square(self):
        image = Image.new("RGBA", (80, 40), (10, 20, 30, 255))
        round_ = photo.shape_object(image, "circle")
        self.assertEqual(round_.size, (40, 40))
        self.assertEqual(round_.getpixel((0, 0))[3], 0)            # 角落透明
        self.assertEqual(round_.getpixel((20, 20))[3], 255)        # 中間不透明
        self.assertIs(photo.shape_object(image, "original"), image)


class CompositeTests(unittest.TestCase):
    def _render(self, **layers):
        return render(320, 220, RECT, get_theme("beach"), seed=3, decorations=0, **layers)

    def test_land_photo_goes_on_the_islands(self):
        image = self._render(land_photo=_layer(MAGENTA))
        self.assertTrue(_close(image.getpixel(LAND_POINT), MAGENTA))
        self.assertFalse(_close(image.getpixel(SEA_POINT), MAGENTA))

    def test_water_photo_goes_in_the_sea(self):
        image = self._render(water_photo=_layer(MAGENTA))
        self.assertTrue(_close(image.getpixel(SEA_POINT), MAGENTA, 70))
        self.assertFalse(_close(image.getpixel(LAND_POINT), MAGENTA))

    def test_land_and_sea_can_be_used_together(self):
        image = self._render(land_photo=_layer(GREEN), water_photo=_layer(MAGENTA))
        self.assertTrue(_close(image.getpixel(LAND_POINT), GREEN))
        self.assertTrue(_close(image.getpixel(SEA_POINT), MAGENTA, 70))

    def test_without_photos_nothing_changes(self):
        plain = render(320, 220, RECT, get_theme("beach"), seed=3, decorations=0)
        self.assertEqual(self._render().tobytes(), plain.tobytes())


class RecolorTests(unittest.TestCase):
    def setUp(self):
        self.beach = get_theme("beach")
        self.purple = Image.new("RGB", (60, 60), (30, 10, 90))
        self.purple.paste((180, 140, 240), (0, 0, 60, 30))
        self.yellow = Image.new("RGB", (60, 60), (240, 200, 60))
        self.yellow.paste((120, 90, 20), (0, 0, 60, 30))

    def test_land_and_water_are_recoloured_separately(self):
        both = photo.recolor(self.beach, land=self.yellow, water=self.purple)
        self.assertEqual([d for d, _c in both.stops], [d for d, _c in self.beach.stops])
        for distance, color in both.stops:
            if distance <= 0:
                self.assertGreater(color[0], color[2], distance)    # 陸地:黃色系(紅 > 藍)
            else:
                self.assertGreater(color[2], color[0], distance)    # 海:紫色系(藍 > 紅)

    def test_only_land_keeps_the_original_sea(self):
        land_only = photo.recolor(self.beach, land=self.yellow)
        self.assertEqual([c for d, c in land_only.stops if d > 0], [c for d, c in self.beach.stops if d > 0])
        self.assertEqual(land_only.foam, self.beach.foam)
        water_only = photo.recolor(self.beach, water=self.purple)
        self.assertEqual([c for d, c in water_only.stops if d <= 0], [c for d, c in self.beach.stops if d <= 0])
        self.assertNotEqual(water_only.foam, self.beach.foam)       # 浪花跟著海換色
        self.assertEqual(water_only.decor, self.beach.decor)

    def test_light_and_dark_structure_is_kept(self):
        recoloured = photo.recolor(self.beach, land=self.purple, water=self.purple)

        def lum(c):
            return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
        original = [lum(c) for _d, c in self.beach.stops]
        new = [lum(c) for _d, c in recoloured.stops]
        self.assertLess(new[original.index(min(original))], new[original.index(max(original))])

    def test_solid_picture_still_gives_a_range_of_shades(self):
        colors = photo.palette(Image.new("RGB", (20, 20), (90, 140, 90)))
        self.assertGreater(0.299 * colors[-1][0] - 0.299 * colors[0][0], 20)


class ObjectTests(unittest.TestCase):
    def setUp(self):
        self.sprite = Image.new("RGBA", (40, 40), (255, 0, 255, 255))
        self.field = shore_field(640, 360, RECT, margin=46.0, blend=26.0, roughness=22.0, seed=7)

    def _place(self, zone, amount=3.0, size=40, rects=RECT, field=None):
        return decor.place_objects(self.field if field is None else field, rects, ["a", "b"], zone=zone,
                                   amount=amount, size=size, seed=1)

    def test_objects_stay_in_their_zone_and_off_the_icons(self):
        for zone, check in (("water", lambda s: s >= 30), ("land", lambda s: s < 2)):
            placed = self._place(zone)
            self.assertGreater(len(placed), 0, zone)
            for p in placed:
                self.assertTrue(check(self.field[p.y, p.x]), zone)
                left, top, right, bottom = RECT[0]
                half = p.size / 2
                self.assertFalse(p.x + half > left and p.x - half < right and p.y + half > top
                                 and p.y - half < bottom)

    def test_land_objects_fit_into_a_narrow_strip_around_crowded_icons(self):
        # 一整排緊靠的圖示:陸地只剩外圍一圈窄窄的空地(使用者桌面常見的樣子)
        rects = [(20 + 76 * c, 20 + 90 * r, 96 + 76 * c, 100 + 90 * r) for c in range(2) for r in range(3)]
        field = shore_field(640, 360, rects, margin=46.0, blend=26.0, roughness=22.0, seed=7)
        placed = self._place("land", amount=3.0, size=64, rects=rects, field=field)
        self.assertGreater(len(placed), 0)
        self.assertTrue(all(field[p.y, p.x] < 2 for p in placed))

    def test_amount_sets_how_many(self):
        few, many = self._place("water", amount=1.0), self._place("water", amount=3.0)
        self.assertLess(len(few), len(many))
        self.assertEqual(self._place("water", amount=0), [])
        plain = render(640, 360, RECT, get_theme("beach"), seed=3, decorations=0)
        none = render(640, 360, RECT, get_theme("beach"), seed=3, decorations=0, objects=[self.sprite],
                      objects_amount=0)
        self.assertEqual(plain.tobytes(), none.tobytes())

    def test_objects_are_drawn_even_without_decorations(self):
        image = render(640, 360, RECT, get_theme("beach"), seed=3, decorations=0, objects=[self.sprite],
                       objects_amount=3.0, objects_size=40)
        pixels = np.asarray(image).reshape(-1, 3)
        self.assertTrue(np.any((pixels[:, 0] > 240) & (pixels[:, 1] < 20) & (pixels[:, 2] > 240)))


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "config.json"

    def test_only_known_values_are_accepted(self):
        Config(water_mode="photo", land_mode="colors", objects=("a.png",), objects_zone="both").validate()
        for bad in (dict(water_mode="sky"), dict(land_mode="land"), dict(objects_zone="air"),
                    dict(objects_shape="star"), dict(objects_size=0), dict(objects_amount=-1)):
            with self.assertRaises(ValueError, msg=str(bad)):
                Config(**bad).validate()

    def test_old_single_image_settings_are_converted(self):
        for mode, expected in (("water", dict(water_mode="photo", land_mode="off")),
                               ("land", dict(water_mode="off", land_mode="photo")),
                               ("colors", dict(water_mode="colors", land_mode="colors"))):
            self.path.write_text(json.dumps({"image": "C:/pic.jpg", "image_mode": mode}), encoding="utf-8")
            config, warnings = load_config(self.path)
            self.assertEqual(warnings, [])
            self.assertEqual({k: getattr(config, k) for k in expected}, expected, mode)
            if expected["water_mode"] != "off":
                self.assertEqual(config.water_image, "C:/pic.jpg")
        self.path.write_text(json.dumps({"image": "", "image_mode": "off"}), encoding="utf-8")
        self.assertEqual(load_config(self.path)[0], Config())


if __name__ == "__main__":
    unittest.main()
