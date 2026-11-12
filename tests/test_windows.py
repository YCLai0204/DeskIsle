"""Windows 系統功能:開機啟動、桌布備份/還原。

開機啟動用臨時的登錄機碼;「真正去改桌布」的那一步換成假的,不會動到系統設定。

執行:python -m unittest discover -s tests -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

WINDOWS = sys.platform == "win32"


@unittest.skipUnless(WINDOWS, "需要 Windows")
class AutostartTests(unittest.TestCase):
    """用一個臨時的登錄機碼測試,不碰真正的開機啟動清單。"""

    def setUp(self):
        import winreg
        from deskisle.system.windows import autostart
        self.autostart = autostart
        self.key = r"Software\DeskIsleSelfTest"
        patcher = mock.patch.object(autostart, "RUN_KEY", self.key)
        patcher.start()
        self.addCleanup(patcher.stop)

        def remove():
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, self.key)
            except OSError:
                pass
        remove()
        self.addCleanup(remove)

    def test_enable_disable_round_trip(self):
        a = self.autostart
        self.assertFalse(a.is_enabled())
        a.enable()
        self.assertTrue(a.is_enabled())
        self.assertIn("--minimized", a.command())
        a.disable()
        self.assertFalse(a.is_enabled())
        a.disable()   # 重複停用不該出錯

    def test_entry_for_a_different_program_does_not_count(self):
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.key) as key:
            winreg.SetValueEx(key, self.autostart.VALUE_NAME, 0, winreg.REG_SZ, r'"C:\old\DeskIsle.exe"')
        self.assertFalse(self.autostart.is_enabled())


@unittest.skipUnless(WINDOWS, "需要 Windows")
class WallpaperBackupTests(unittest.TestCase):
    """用假的「目前桌布」與假的「設定桌布」走完備份 → 套用 → 還原。"""

    def setUp(self):
        from deskisle.system.windows import wallpaper
        self.wp = wallpaper
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)

        env = mock.patch.dict(os.environ, {"LOCALAPPDATA": str(root / "appdata")})
        env.start()
        self.addCleanup(env.stop)

        self.original = root / "spotlight.jpg"
        Image.new("RGB", (8, 8), (1, 2, 3)).save(self.original)

        # 假的系統狀態
        self.system = wallpaper.WallpaperState(str(self.original), "10", "0", kind=3)
        self.set_calls = []

        def fake_set(path, style, tile):
            self.set_calls.append((path, style, tile))
            self.system = wallpaper.WallpaperState(path, style, tile, kind=0)

        for name, replacement in (("current", lambda: self.system), ("_set", fake_set)):
            patcher = mock.patch.object(wallpaper, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.image = Image.new("RGB", (16, 16), (10, 120, 200))

    def test_apply_backs_up_then_restore_puts_it_back(self):
        target = self.wp.apply_image(self.image)
        self.assertTrue(target.is_file())
        self.assertEqual(self.set_calls[-1], (str(target), "10", "0"))

        backup = self.wp.load_backup()
        self.assertEqual(backup.path, str(self.original))
        self.assertEqual(backup.kind, 3)
        self.assertTrue((target.parent / backup.backup).is_file())

        restored = self.wp.restore()
        self.assertEqual(restored.path, str(self.original))
        self.assertEqual(self.set_calls[-1], (str(self.original), "10", "0"))
        self.assertIsNone(self.wp.load_backup(), "還原後備份紀錄應清除")
        self.assertIsNone(self.wp.restore(), "沒有備份時再還原應回傳 None")

    def test_repeated_apply_keeps_the_first_backup_and_alternates_files(self):
        first = self.wp.apply_image(self.image)
        second = self.wp.apply_image(self.image)
        third = self.wp.apply_image(self.image)
        self.assertNotEqual(first, second)
        self.assertEqual(first, third)
        # 備份仍是最初那張,而不是我們自己產生的圖
        self.assertEqual(self.wp.load_backup().path, str(self.original))

    def test_multiple_monitors_use_span_style(self):
        self.wp.apply_image(self.image, monitors=2)
        self.assertEqual(self.set_calls[-1][1], self.wp.STYLE_SPAN)

    def test_restore_falls_back_to_the_copy_when_original_file_is_gone(self):
        target = self.wp.apply_image(self.image)
        self.original.unlink()   # 模擬 Windows 清掉焦點桌布的快取
        self.wp.restore()
        restored_path = Path(self.set_calls[-1][0])
        self.assertEqual(restored_path.parent, target.parent)
        self.assertTrue(restored_path.name.startswith("original"))
        self.assertTrue(restored_path.is_file())

    def test_solid_colour_background_round_trips(self):
        self.system = self.wp.WallpaperState("", "10", "0", kind=1)
        self.wp.apply_image(self.image)
        self.wp.restore()
        self.assertEqual(self.set_calls[-1][0], "")

    def test_our_own_wallpaper_is_never_recorded_as_the_original(self):
        self.wp.apply_image(self.image)
        self.wp.state_path().unlink()    # 模擬備份紀錄遺失
        self.wp.apply_image(self.image)
        self.assertIsNone(self.wp.load_backup())


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
