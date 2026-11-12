"""多螢幕:選擇要更新的螢幕、每個螢幕各自繪製與套用。

真正去改桌布的那一步(IDesktopWallpaper)都換成假的,不會動到系統設定。

執行:python -m unittest discover -s tests -v
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from PIL import Image

from deskisle.config import Config, load_config, save_config
from deskisle.layout import DesktopIcon, DesktopLayout, Screen, screen_rects

WINDOWS = sys.platform == "win32"

# 左邊一個橫向螢幕,右邊一個直向螢幕(比實際縮小,測試才快)
LEFT = Screen("monitor-left", 0, 40, 320, 180, primary=True)
RIGHT = Screen("monitor-right", 320, 0, 120, 220)
ICONS = (DesktopIcon("a", 10, 50, 86, 120), DesktopIcon("b", 330, 10, 406, 80),
         DesktopIcon("跨螢幕", 300, 100, 350, 150))
LAYOUT = DesktopLayout(440, 220, ICONS, screens=(LEFT, RIGHT))


class LayoutTests(unittest.TestCase):
    def test_single_screen_layout_is_its_own_screen(self):
        layout = DesktopLayout(320, 200, ())
        self.assertEqual(layout.screen_list(), (Screen("", 0, 0, 320, 200, True),))
        self.assertEqual(layout.monitors, 1)
        self.assertFalse(layout.can_choose_screens())

    def test_selection(self):
        self.assertTrue(LAYOUT.can_choose_screens())
        self.assertEqual(LAYOUT.selected_screens(()), [LEFT, RIGHT])               # 空 = 全部
        self.assertEqual(LAYOUT.selected_screens(("monitor-right",)), [RIGHT])
        self.assertEqual(LAYOUT.selected_screens(("unplugged",)), [LEFT, RIGHT])   # 選的都不在 → 全部

    def test_screens_without_ids_cannot_be_chosen(self):
        layout = DesktopLayout(440, 220, (), screens=(Screen("", 0, 0, 320, 220), Screen("", 320, 0, 120, 220)))
        self.assertFalse(layout.can_choose_screens())

    def test_portrait_and_description(self):
        self.assertTrue(RIGHT.portrait)
        self.assertFalse(LEFT.portrait)
        self.assertEqual(LEFT.describe(1), "螢幕 1(主螢幕) · 320×180 橫向")
        self.assertIn("直向", RIGHT.describe(2))

    def test_icon_rects_are_moved_into_each_screen(self):
        self.assertEqual(screen_rects(LAYOUT, LEFT), [(10, 10, 86, 80), (300, 60, 320, 110)])
        self.assertEqual(screen_rects(LAYOUT, RIGHT), [(10, 10, 86, 80), (0, 100, 30, 150)])
        self.assertEqual(screen_rects(LAYOUT, LEFT, 0.5), [(5, 5, 43, 40), (150, 30, 160, 55)])

    def test_signature_changes_when_screens_change(self):
        moved = DesktopLayout(440, 220, ICONS, screens=(LEFT, Screen("monitor-right", 320, 0, 220, 120)))
        self.assertNotEqual(LAYOUT.signature(), moved.signature())


class ScreenConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "config.json"

    def test_round_trip(self):
        save_config(Config(screens=("monitor-right",)), self.path)
        config, _ = load_config(self.path)
        self.assertEqual(config.screens, ("monitor-right",))

    def test_bad_values_are_rejected(self):
        for bad in ({"screens": "monitor-right"}, {"screens": [1, 2]}):
            self.path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(ValueError, msg=str(bad)):
                load_config(self.path)


@unittest.skipUnless(WINDOWS, "需要 Windows")
class RenderScreensTests(unittest.TestCase):
    def test_each_screen_is_drawn_at_its_own_size(self):
        from deskisle import watcher
        portrait = watcher.render_screen(LAYOUT, Config(decorations=0), 1)
        self.assertEqual(portrait.size, (120, 220))
        small = watcher.render_screen(LAYOUT, Config(decorations=0), 1, ratio=0.5)
        self.assertEqual(small.size, (60, 110))

    def test_whole_desktop_leaves_the_gap_black(self):
        from deskisle import watcher
        image = watcher.render_layout(LAYOUT, Config(decorations=0))
        self.assertEqual(image.size, (440, 220))
        self.assertEqual(image.getpixel((5, 5)), watcher.GAP_COLOR)    # 左螢幕上方沒有螢幕

    def test_only_the_chosen_screens_are_drawn_and_applied(self):
        from deskisle import watcher
        calls = []

        def fake_apply(images):
            calls.append([(screen.id, image.size) for screen, image in images])
            return [Path("fake.png")]

        with mock.patch.object(watcher.wallpaper, "apply_per_screen", fake_apply):
            watcher.apply_layout(LAYOUT, Config(decorations=0, screens=("monitor-right",)))
            watcher.apply_layout(LAYOUT, Config(decorations=0))
        self.assertEqual(calls, [
            [("monitor-right", (120, 220))],
            [("monitor-left", (320, 180)), ("monitor-right", (120, 220))],
        ])

    def test_retina_screens_are_drawn_in_physical_pixels(self):
        from deskisle import watcher
        retina = DesktopLayout(440, 220, ICONS, screens=(
            Screen("mac-1", 0, 40, 320, 180, True, scale=2.0), Screen("mac-2", 320, 0, 120, 220)))
        single = DesktopLayout(160, 100, (), screens=(Screen("mac-1", 0, 0, 160, 100, True, scale=2.0),))
        sizes = []
        with mock.patch.object(watcher.wallpaper, "apply_per_screen",
                               lambda images: sizes.extend(i.size for _s, i in images) or []), \
                mock.patch.object(watcher.wallpaper, "apply_image",
                                  lambda image, monitors=1: sizes.append(image.size) or Path("x.png")):
            watcher.apply_layout(retina, Config(decorations=0))
            watcher.apply_layout(single, Config(decorations=0))
        self.assertEqual(sizes, [(640, 360), (120, 220), (320, 200)])

    def test_without_ids_everything_is_one_spanned_image(self):
        from deskisle import watcher
        layout = DesktopLayout(440, 220, ICONS, screens=(
            Screen("", 0, 40, 320, 180, True), Screen("", 320, 0, 120, 220)))
        seen = []
        with mock.patch.object(watcher.wallpaper, "apply_image",
                               lambda image, monitors=1: seen.append((image.size, monitors)) or Path("x.png")):
            watcher.apply_layout(layout, Config(decorations=0, screens=("whatever",)))
        self.assertEqual(seen, [((440, 220), 2)])

    def test_preview_marks_skipped_screens(self):
        from deskisle import gui
        data = gui.render_preview(LAYOUT, Config(decorations=0, screens=("monitor-left",)), 220)
        image = Image.open(io.BytesIO(data)).convert("RGB")
        self.assertEqual(image.size, (220, 110))
        # 右邊的直向螢幕沒選 → 只有灰色與斜線兩種顏色
        colors = {image.getpixel((x, y)) for x in range(170, 215) for y in range(40, 100)}
        self.assertTrue(colors <= {gui.PREVIEW_SKIPPED, gui.PREVIEW_GAP}, colors)


@unittest.skipUnless(WINDOWS, "需要 Windows")
class ScreenCheckboxTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from deskisle import gui
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = mock.patch.dict(os.environ, {"LOCALAPPDATA": tmp.name})
        env.start()
        self.addCleanup(env.stop)
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        self.app = gui.App(root, headless=True)
        self.app._set_screens((LEFT, RIGHT))

    def test_unchecking_a_screen_selects_the_rest(self):
        app = self.app
        self.assertEqual(app.draft_config().screens, ())
        app._screen_vars["monitor-right"].set(False)
        app._screens_toggled()
        self.assertEqual(app.draft_config().screens, ("monitor-left",))
        app._screen_vars["monitor-right"].set(True)
        app._screens_toggled()
        self.assertEqual(app.draft_config().screens, ())     # 全選 = 全部

    def test_the_last_screen_cannot_be_unchecked(self):
        app = self.app
        app._screen_vars["monitor-right"].set(False)
        app._screens_toggled()
        app._screen_vars["monitor-left"].set(False)
        app._screens_toggled()
        self.assertTrue(app._screen_vars["monitor-left"].get())
        self.assertEqual(app.draft_config().screens, ("monitor-left",))

    def test_saved_choice_is_shown_and_unplugged_screens_are_kept(self):
        app = self.app
        app._load_controls(Config(screens=("monitor-right", "unplugged")))
        self.assertFalse(app._screen_vars["monitor-left"].get())
        self.assertTrue(app._screen_vars["monitor-right"].get())
        app._screen_vars["monitor-left"].set(True)
        app._screens_toggled()
        self.assertEqual(set(app.draft_config().screens), {"monitor-left", "monitor-right", "unplugged"})


class _FakeDesktop:
    def __init__(self):
        self.wallpapers = {"monitor-left": r"C:\pics\left.jpg", "monitor-right": r"C:\pics\right.jpg"}
        self.positions = []

    def monitor_ids(self):
        return list(self.wallpapers)

    def monitor_rect(self, monitor_id):
        return (0, 0, 10, 10)

    def get_wallpaper(self, monitor_id):
        return self.wallpapers[monitor_id]

    def set_wallpaper(self, monitor_id, path):
        self.wallpapers[monitor_id] = path

    def set_position(self, position):
        self.positions.append(position)


@unittest.skipUnless(WINDOWS, "需要 Windows")
class PerScreenWallpaperTests(unittest.TestCase):
    def setUp(self):
        from deskisle import wallpaper
        self.wp = wallpaper
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"LOCALAPPDATA": self.tmp.name})
        env.start()
        self.addCleanup(env.stop)

        self.desktop = _FakeDesktop()
        self.system = wallpaper.WallpaperState(r"C:\pics\left.jpg", "10", "0")
        self.set_calls = []

        @contextmanager
        def fake_open():
            yield self.desktop

        def fake_set(path, style, tile):
            self.set_calls.append(path)

        for target, name, replacement in (
            (wallpaper.screen_api, "open_desktop_wallpaper", fake_open),
            (wallpaper.screen_api, "monitor_rects", lambda: [((0, 0, 1, 1), True), ((1, 0, 2, 1), False)]),
            (wallpaper, "current", lambda: self.system),
            (wallpaper, "_set", fake_set),
        ):
            patcher = mock.patch.object(target, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_only_the_given_screen_changes_and_files_alternate(self):
        image = Image.new("RGB", (12, 20), (1, 2, 3))
        first = self.wp.apply_per_screen([(RIGHT, image)])
        self.assertEqual(self.desktop.wallpapers["monitor-left"], r"C:\pics\left.jpg")   # 沒選的不動
        self.assertEqual(self.desktop.wallpapers["monitor-right"], str(first[0]))
        self.assertTrue(first[0].is_file())
        self.assertEqual(self.desktop.positions, [self.wp.screen_api.DWPOS_FILL])

        second = self.wp.apply_per_screen([(RIGHT, image)])
        self.assertNotEqual(first, second)                 # 換檔名,Windows 才會重新載入
        left = self.wp.apply_per_screen([(LEFT, image)])
        self.assertNotEqual(left[0].name[:18], first[0].name[:18])   # 每個螢幕有自己的檔名

    def test_backup_remembers_each_screen_and_restore_puts_them_back(self):
        Path(self.tmp.name, "pics").mkdir()
        left_file, right_file = Path(self.tmp.name, "pics", "l.jpg"), Path(self.tmp.name, "pics", "r.jpg")
        for path in (left_file, right_file):
            Image.new("RGB", (4, 4)).save(path)
        self.desktop.wallpapers = {"monitor-left": str(left_file), "monitor-right": str(right_file)}
        self.system = self.wp.WallpaperState(str(left_file), "10", "0")

        image = Image.new("RGB", (12, 20))
        self.wp.apply_per_screen([(LEFT, image), (RIGHT, image)])
        self.assertEqual(self.wp.load_backup().per_monitor,
                         {"monitor-left": str(left_file), "monitor-right": str(right_file)})

        self.wp.restore()
        self.assertEqual(self.desktop.wallpapers, {"monitor-left": str(left_file), "monitor-right": str(right_file)})


if __name__ == "__main__":
    unittest.main()
