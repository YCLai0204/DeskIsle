"""使用者的圖片:匯入、裁切、當陸地/當海、取色。任何作業系統都能跑。

執行:python -m unittest discover -s tests -v
"""
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from deskisle.config import Config
from deskisle.engine import photo
from deskisle.engine.render import render
from deskisle.engine.themes import get_theme

MAGENTA = (250, 0, 250)
RECT = [(140, 90, 180, 130)]           # 一個圖示在中間;陸地在它周圍,畫面邊緣是海


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        photo.clear_cache()

    def test_import_makes_an_rgb_copy_named_by_content(self):
        source = self.root / "透明.png"
        Image.new("RGBA", (40, 20), (255, 0, 0, 0)).save(source)
        first = photo.import_image(source, self.root / "images")
        second = photo.import_image(source, self.root / "images")
        self.assertEqual(first, second)                          # 同一張圖只存一份
        source.unlink()                                          # 原檔不見也沒關係
        image = photo.load(str(first))
        self.assertEqual((image.mode, image.size), ("RGB", (40, 20)))
        self.assertGreater(min(image.getpixel((5, 5))), 240)     # 透明的地方墊白色

    def test_only_the_newest_images_are_kept(self):
        folder = self.root / "images"
        for i in range(photo.KEEP_IMAGES + 2):
            source = self.root / f"{i}.png"
            Image.new("RGB", (8, 8), (i * 20, 0, 0)).save(source)
            photo.import_image(source, folder)
        self.assertEqual(len(list(folder.glob("custom_*.jpg"))), photo.KEEP_IMAGES)

    def test_broken_or_missing_files(self):
        broken = self.root / "壞掉.jpg"
        broken.write_bytes(b"not an image")
        with self.assertRaises(ValueError):
            photo.import_image(broken, self.root / "images")
        self.assertIsNone(photo.load(str(broken)))
        self.assertIsNone(photo.load(str(self.root / "沒有這個檔案.jpg")))
        self.assertIsNone(photo.load(""))


class CoverTests(unittest.TestCase):
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


class CompositeTests(unittest.TestCase):
    def _render(self, mode):
        layer = np.full((220, 320, 3), MAGENTA, dtype=np.float32)
        return render(320, 220, RECT, get_theme("beach"), seed=3, decorations=0,
                      photo=layer, photo_mode=mode)

    @staticmethod
    def _close(color, target, tolerance=40):
        return all(abs(a - b) <= tolerance for a, b in zip(color, target))

    def test_land_mode_puts_the_picture_on_the_islands(self):
        image = self._render("land")
        self.assertTrue(self._close(image.getpixel((160, 110)), MAGENTA))   # 圖示底下(陸地中央)
        self.assertFalse(self._close(image.getpixel((5, 5)), MAGENTA))      # 遠處的海

    def test_water_mode_puts_the_picture_in_the_sea(self):
        image = self._render("water")
        self.assertTrue(self._close(image.getpixel((5, 5)), MAGENTA, 70))
        self.assertFalse(self._close(image.getpixel((160, 110)), MAGENTA))

    def test_without_a_mode_the_picture_is_ignored(self):
        plain = render(320, 220, RECT, get_theme("beach"), seed=3, decorations=0)
        self.assertEqual(self._render("").tobytes(), plain.tobytes())


class RecolorTests(unittest.TestCase):
    def test_theme_takes_the_picture_colours_but_keeps_its_light_and_dark(self):
        image = Image.new("RGB", (60, 60), (30, 10, 90))         # 深紫
        image.paste((240, 200, 60), (0, 0, 60, 30))              # 上半部是亮黃
        beach = get_theme("beach")
        colored = photo.recolor(beach, image)
        self.assertEqual([d for d, _c in colored.stops], [d for d, _c in beach.stops])

        def lum(c):
            return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
        original = [lum(c) for _d, c in beach.stops]
        new = [lum(c) for _d, c in colored.stops]
        darkest, brightest = original.index(min(original)), original.index(max(original))
        self.assertLess(new[darkest], new[brightest])            # 明暗結構不變
        dark, bright = colored.stops[darkest][1], colored.stops[brightest][1]
        self.assertGreater(dark[2], dark[0])                     # 最暗的位置是紫色系(藍 > 紅)
        self.assertGreater(bright[0], bright[2])                 # 最亮的位置是黃色系(紅 > 藍)
        self.assertEqual(colored.decor, beach.decor)

    def test_solid_picture_still_gives_a_range_of_shades(self):
        colors = photo.palette(Image.new("RGB", (20, 20), (90, 140, 90)))
        self.assertGreater(0.299 * colors[-1][0] - 0.299 * colors[0][0], 20)

    def test_config_accepts_only_known_modes(self):
        Config(image_mode="water").validate()
        with self.assertRaises(ValueError):
            Config(image_mode="sky").validate()


if __name__ == "__main__":
    unittest.main()
