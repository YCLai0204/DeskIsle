"""macOS 版的測試。用假的 osascript 執行,所以在 Windows 上也能跑。

真正的 Mac 行為(Finder 權限、NSWorkspace 設定桌布)只能在 Mac 上確認。

執行:python -m unittest discover -s tests -v
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from deskisle import autostart_mac, macos, wallpaper_mac
from deskisle.layout import IconDetectionError, Screen

# 主螢幕 1440×900(Retina),左邊一個直向 1080×1920 的螢幕,上緣對齊
SCREENS_OUTPUT = json.dumps([
    {"id": "1", "x": 0, "y": 0, "w": 1440, "h": 900, "scale": 2},
    {"id": "2", "x": -1080, "y": -1020, "w": 1080, "h": 1920, "scale": 1},
])


class ParseTests(unittest.TestCase):
    def test_screens_are_flipped_to_top_left_origin(self):
        screens, origin = macos.parse_screens(SCREENS_OUTPUT)
        self.assertEqual(origin, (-1080, 0))
        self.assertEqual(screens, (
            Screen("2", 0, 0, 1080, 1920, False, 1.0),
            Screen("1", 1080, 0, 1440, 900, True, 2.0),
        ))
        self.assertTrue(screens[0].portrait)

    def test_no_screens_is_an_error(self):
        with self.assertRaises(IconDetectionError):
            macos.parse_screens("[]")

    def test_icons_below_label(self):
        icons = macos.parse_icons("64\t12\tbottom\n100\t80\tnotes.txt\n200\t80\t有\t分隔的名字\n", (-1080, 0))
        self.assertEqual(icons[0].rect, (1135, 48, 1225, 146))     # 中心 (1180, 80),文字在下方
        self.assertEqual(icons[0].name, "notes.txt")
        self.assertEqual(icons[1].name, "有\t分隔的名字")

    def test_icons_with_label_on_the_right(self):
        icons = macos.parse_icons("48\t11\tright\n100\t100\ta\n", (0, 0))
        self.assertEqual(icons[0].rect, (76, 76, 234, 124))

    def test_empty_desktop(self):
        self.assertEqual(macos.parse_icons("64\t12\tbottom\n", (0, 0)), [])
        self.assertEqual(macos.parse_icons("", (0, 0)), [])


class ReadLayoutTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.stamp = ("a",)

        def fake_run(script, *args, javascript=False):
            self.calls.append("screens" if javascript else "icons")
            return SCREENS_OUTPUT if javascript else "64\t12\tbottom\n100\t80\tnotes.txt\n"

        for name, value in (("run_osascript", fake_run), ("_desktop_stamp", lambda: self.stamp),
                            ("icons_visible", lambda: True)):
            patcher = mock.patch.object(macos, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        macos._screen_cache.update(at=-1e9, value=None)
        macos._icon_cache.update(stamp=None, at=-1e9, screens=None, layout=None)

    def test_layout_is_in_points_with_retina_scale(self):
        layout = macos.read_layout()
        self.assertEqual((layout.width, layout.height), (2520, 1920))
        self.assertEqual(layout.rects, [(1135, 48, 1225, 146)])
        self.assertTrue(layout.can_choose_screens())
        self.assertEqual([s.scale for s in layout.screen_list()], [1.0, 2.0])

    def test_finder_is_asked_again_only_when_the_desktop_changes(self):
        first = macos.read_layout()
        self.assertIs(macos.read_layout(), first)
        self.assertEqual(self.calls.count("icons"), 1)
        self.stamp = ("b",)                              # 檔案或 .DS_Store 變了
        macos.read_layout()
        self.assertEqual(self.calls.count("icons"), 2)
        self.assertEqual(self.calls.count("screens"), 1)  # 螢幕清單有自己的快取


class RunOsascriptTests(unittest.TestCase):
    def test_permission_error_explains_what_to_do(self):
        done = mock.Mock(returncode=1, stdout="",
                         stderr="execution error: Not authorized to send Apple events to Finder. (-1743)")
        with mock.patch.object(macos.subprocess, "run", return_value=done):
            with self.assertRaises(IconDetectionError) as caught:
                macos.run_osascript("tell application \"Finder\" to beep")
        self.assertIn("自動化", str(caught.exception))

    def test_arguments_are_passed_after_the_script(self):
        done = mock.Mock(returncode=0, stdout="ok\n", stderr="")
        with mock.patch.object(macos.subprocess, "run", return_value=done) as run:
            self.assertEqual(macos.run_osascript("S", "a", "b", javascript=True), "ok")
        self.assertEqual(run.call_args[0][0], ["osascript", "-l", "JavaScript", "-e", "S", "a", "b"])


class MacWallpaperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.folder = root / "app"
        patcher = mock.patch.object(wallpaper_mac, "app_dir", lambda: self.folder)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.originals = {"1": str(root / "beach.heic"), "2": str(root / "tall.jpg")}
        for path in self.originals.values():
            Path(path).write_bytes(b"picture")
        self.system = dict(self.originals)
        self.sets = []

        def fake_run(script, *args, javascript=False):
            if script is wallpaper_mac.GET_JXA:
                return json.dumps(self.system)
            pairs = dict(zip(args[::2], args[1::2]))
            self.sets.append(pairs)
            for screen_id in self.system:
                if screen_id in pairs or "*" in pairs:
                    self.system[screen_id] = pairs.get(screen_id, pairs.get("*"))
            return ""

        patcher = mock.patch.object(wallpaper_mac, "run_osascript", fake_run)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.image = Image.new("RGB", (8, 8))

    def test_per_screen_apply_only_touches_chosen_screens_and_alternates(self):
        screen = Screen("2", 0, 0, 1080, 1920)
        first = wallpaper_mac.apply_per_screen([(screen, self.image)])
        self.assertEqual(self.system["1"], self.originals["1"])
        self.assertEqual(self.system["2"], str(first[0]))
        second = wallpaper_mac.apply_per_screen([(screen, self.image)])
        self.assertNotEqual(first, second)

    def test_backup_and_restore_every_screen(self):
        wallpaper_mac.apply_image(self.image)
        self.assertEqual(self.sets[-1].keys(), {"*"})
        backup = wallpaper_mac.load_backup()
        self.assertEqual(backup.per_screen, self.originals)
        self.assertEqual(set(backup.backups), {"1", "2"})

        wallpaper_mac.apply_image(self.image)                     # 第二次不會把自己的圖當成原圖
        self.assertEqual(wallpaper_mac.load_backup().per_screen, self.originals)

        Path(self.originals["2"]).unlink()                        # 原圖不見了 → 用備份
        restored = wallpaper_mac.restore()
        self.assertEqual(restored.path, self.originals["1"])
        self.assertEqual(self.system["1"], self.originals["1"])
        self.assertEqual(Path(self.system["2"]).parent, self.folder)
        self.assertIsNone(wallpaper_mac.load_backup())
        self.assertIsNone(wallpaper_mac.restore())


class MacAutostartTests(unittest.TestCase):
    def test_enable_disable_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "LaunchAgents" / "com.deskisle.app.plist"
            with mock.patch.object(autostart_mac, "plist_path", lambda: path):
                self.assertFalse(autostart_mac.is_enabled())
                autostart_mac.enable()
                self.assertTrue(autostart_mac.is_enabled())
                self.assertIn("--minimized", autostart_mac.arguments())
                autostart_mac.disable()
                self.assertFalse(autostart_mac.is_enabled())
                autostart_mac.disable()


@unittest.skipUnless(hasattr(__import__("socket"), "AF_UNIX") and os.name == "posix", "需要 Unix socket")
class SingleInstanceTests(unittest.TestCase):
    def test_second_instance_signals_the_first(self):
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(macos.tempfile, "gettempdir", lambda: folder):
                self.assertTrue(macos.acquire_single_instance())
                self.assertFalse(macos.acquire_single_instance())   # 已經有一個在執行
                handle = macos.create_signal()
                self.assertTrue(macos.send_signal())
                self.assertTrue(macos.wait_signal(handle))
                handle.close()


if __name__ == "__main__":
    unittest.main()
