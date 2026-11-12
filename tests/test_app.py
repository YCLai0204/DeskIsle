"""設定、防抖動、桌布備份/還原的測試。

桌布相關測試把「真正去改桌布」的那一步換成假的,所以不會動到系統設定。

執行:python -m unittest discover -s tests -v
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from deskisle.config import Config, load_config, save_config

WINDOWS = sys.platform == "win32"


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "config.json"

    def test_missing_file_gives_defaults(self):
        config, warnings = load_config(self.path)
        self.assertEqual(config, Config())
        self.assertEqual(warnings, [])

    def test_round_trip(self):
        save_config(Config(theme="volcano", seed=42, margin=60.0), self.path)
        config, _ = load_config(self.path)
        self.assertEqual((config.theme, config.seed, config.margin), ("volcano", 42, 60.0))

    def test_partial_file_keeps_other_defaults_and_warns_on_unknown_keys(self):
        self.path.write_text(json.dumps({"theme": "meadow", "nonsense": 1}), encoding="utf-8")
        config, warnings = load_config(self.path)
        self.assertEqual(config.theme, "meadow")
        self.assertEqual(config.seed, Config().seed)
        self.assertEqual(len(warnings), 1)
        self.assertIn("nonsense", warnings[0])

    def test_booleans_round_trip(self):
        save_config(Config(follow=True, pause_when_busy=False), self.path)
        config, _ = load_config(self.path)
        self.assertIs(config.follow, True)
        self.assertIs(config.pause_when_busy, False)

    def test_bad_values_are_rejected(self):
        for bad in ({"theme": "nope"}, {"margin": 0}, {"seed": "abc"}, {"poll_interval": 0},
                    {"follow": "yes"}, {"margin": True}, {"decorations": -1}, {"idle_interval": 0}):
            self.path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(ValueError, msg=str(bad)):
                load_config(self.path)

    def test_broken_json_is_rejected(self):
        self.path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_config(self.path)


@unittest.skipUnless(WINDOWS, "需要 Windows")
class DebouncerTests(unittest.TestCase):
    def setUp(self):
        from deskisle.watcher import LayoutDebouncer
        self.d = LayoutDebouncer(debounce=0.5)

    def test_first_layout_applies_immediately(self):
        self.assertTrue(self.d.should_apply("A", now=0.0))

    def test_unchanged_layout_is_not_reapplied(self):
        self.d.mark_applied("A")
        self.assertFalse(self.d.should_apply("A", now=10.0))

    def test_change_waits_until_stable(self):
        self.d.mark_applied("A")
        self.assertFalse(self.d.should_apply("B", now=1.0))    # 剛出現
        self.assertTrue(self.d.waiting)
        self.assertFalse(self.d.should_apply("B", now=1.3))    # 還不夠久
        self.assertTrue(self.d.should_apply("B", now=1.6))     # 穩定了

    def test_intermediate_states_restart_the_wait(self):
        self.d.mark_applied("A")
        self.assertFalse(self.d.should_apply("B", now=1.0))
        self.assertFalse(self.d.should_apply("C", now=1.4))    # 又變了 → 重新計時
        self.assertFalse(self.d.should_apply("C", now=1.8))
        self.assertTrue(self.d.should_apply("C", now=1.95))

    def test_returning_to_applied_layout_cancels_the_wait(self):
        self.d.mark_applied("A")
        self.assertFalse(self.d.should_apply("B", now=1.0))
        self.assertFalse(self.d.should_apply("A", now=1.2))
        self.assertFalse(self.d.waiting)


@unittest.skipUnless(WINDOWS, "需要 Windows")
class WatchLoopTests(unittest.TestCase):
    """用假的圖示排列跑完整的監看迴圈:讀取 → 防抖動 → 重畫 → 套用。"""

    def test_applies_once_per_stable_layout_and_survives_detection_errors(self):
        from deskisle import watcher
        from deskisle.icons import DesktopIcon, DesktopLayout, IconDetectionError

        a = DesktopLayout(320, 200, (DesktopIcon("a", 0, 0, 76, 70),))
        b = DesktopLayout(320, 200, (DesktopIcon("a", 200, 100, 276, 170),))
        script = [a, IconDetectionError("檔案總管重啟中"), a, a, b]

        def fake_read(names=True):
            item = script.pop(0) if script else b
            if isinstance(item, Exception):
                raise item
            return item

        applied, logs = [], []

        def fake_apply(image, monitors=1):
            applied.append(image.size)
            return Path("fake.png")

        config = Config(poll_interval=0.1, idle_interval=0.1, debounce=0.05, pause_when_busy=False)
        with mock.patch.object(watcher, "read_layout", fake_read), \
                mock.patch.object(watcher.wallpaper, "apply_image", fake_apply):
            updates = watcher.watch(config, log=logs.append, max_updates=2)

        self.assertEqual(updates, 2)
        self.assertEqual(applied, [(320, 200), (320, 200)])
        self.assertEqual(sum("暫時無法更新" in line for line in logs), 1)
        self.assertEqual(sum("已恢復監看" in line for line in logs), 1)
        self.assertEqual(sum("已更新桌布" in line for line in logs), 2)

    def _run_watcher(self, config_box, layouts, busy=False, updates=1, seconds=1.5):
        """在背景執行緒跑監看器,回傳 (監看器, 套用紀錄, 狀態紀錄)。"""
        from deskisle import watcher

        applied, states = [], []

        def fake_apply(image, monitors=1):
            applied.append(config_box[0].theme)
            return Path("fake.png")

        patches = [
            mock.patch.object(watcher, "read_layout", lambda names=True: layouts[0]),
            mock.patch.object(watcher.wallpaper, "apply_image", fake_apply),
            mock.patch.object(watcher.winapi, "user_is_busy", lambda: busy),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        w = watcher.Watcher(lambda: config_box[0], lambda s: states.append(s.state))
        w.start()
        self.addCleanup(w.stop)
        return w, applied, states

    def _wait_for(self, condition, seconds=3.0):
        import time
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if condition():
                return True
            time.sleep(0.02)
        return False

    def test_changing_the_look_redraws_and_refresh_skips_the_wait(self):
        from deskisle.icons import DesktopIcon, DesktopLayout
        from dataclasses import replace

        layout = DesktopLayout(320, 200, (DesktopIcon("a", 0, 0, 76, 70),))
        box = [Config(poll_interval=0.1, idle_interval=0.1, debounce=30.0, pause_when_busy=False)]
        w, applied, _ = self._run_watcher(box, [layout])
        self.assertTrue(self._wait_for(lambda: applied == ["beach"]))

        # 換主題後呼叫 refresh():即使防抖動時間很長也要立刻重畫
        box[0] = replace(box[0], theme="cosmos")
        w.refresh()
        self.assertTrue(self._wait_for(lambda: applied == ["beach", "cosmos"]), applied)

        w.stop()
        self.assertFalse(w.running)
        self.assertEqual(w.status.state, "stopped")

    def _run_reseed(self, reseed_on_move):
        """排列 a → a → b → b:回傳每次套用時用的種子與 on_reseed 收到的種子。"""
        from dataclasses import replace
        from deskisle import watcher
        from deskisle.icons import DesktopIcon, DesktopLayout

        a = DesktopLayout(320, 200, (DesktopIcon("a", 0, 0, 76, 70),))
        b = DesktopLayout(320, 200, (DesktopIcon("a", 200, 100, 276, 170),))
        script = [a, a, b, b, b, b]
        box = [Config(poll_interval=0.1, idle_interval=0.1, debounce=0.0, pause_when_busy=False,
                      reseed_on_move=reseed_on_move)]
        seeds, reported = [], []

        def on_reseed(seed):
            reported.append(seed)
            box[0] = replace(box[0], seed=seed)

        def fake_apply(layout, config):
            seeds.append(config.seed)
            return Path("fake.png")

        w = watcher.Watcher(lambda: box[0], None, on_reseed)

        def fake_read(names=True):
            if not script:
                w.stop(wait=False)   # 腳本讀完就結束
                return b
            return script.pop(0)

        with mock.patch.object(watcher, "read_layout", fake_read), \
                mock.patch.object(watcher, "apply_layout", fake_apply):
            w.run()
        return seeds, reported, script

    def test_moving_icons_picks_a_new_seed_once(self):
        seeds, reported, script = self._run_reseed(True)
        self.assertEqual(seeds[0], Config().seed)          # 第一次用設定裡的種子
        self.assertNotEqual(seeds[1], seeds[0])            # 圖示移動 → 換種子
        self.assertEqual(reported, [seeds[1]])
        # 換完種子後排列沒再變,就不該再重畫
        self.assertEqual(len(seeds), 2)
        self.assertEqual(script, [])

    def test_reseed_can_be_turned_off(self):
        seeds, reported, _ = self._run_reseed(False)
        self.assertEqual(seeds, [Config().seed, Config().seed])
        self.assertEqual(reported, [])

    def test_nothing_is_read_or_drawn_while_a_fullscreen_app_is_running(self):
        from deskisle.icons import DesktopIcon, DesktopLayout

        layout = DesktopLayout(320, 200, (DesktopIcon("a", 0, 0, 76, 70),))
        box = [Config(poll_interval=0.1, idle_interval=0.1, debounce=0.05)]
        w, applied, states = self._run_watcher(box, [layout], busy=True)
        self.assertTrue(self._wait_for(lambda: "paused" in states))
        self.assertEqual(applied, [])

        # 使用者關掉暫停功能 → 開始運作
        from dataclasses import replace
        box[0] = replace(box[0], pause_when_busy=False)
        self.assertTrue(self._wait_for(lambda: applied == ["beach"]), applied)


@unittest.skipUnless(WINDOWS, "需要 Windows")
class AutostartTests(unittest.TestCase):
    """用一個臨時的登錄機碼測試,不碰真正的開機啟動清單。"""

    def setUp(self):
        import winreg
        from deskisle import autostart
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
class GuiTests(unittest.TestCase):
    """建立介面但不顯示視窗(headless):不啟動監看、不建系統匣、不寫設定。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"LOCALAPPDATA": self.tmp.name})
        env.start()
        self.addCleanup(env.stop)

    def _make_app(self):
        import tkinter as tk
        from deskisle import gui
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        return gui.App(root, headless=True), root

    def _pages(self, app):
        return [app.notebook.tab(i, "text") for i in range(app.notebook.index("end"))]

    def test_source_build_has_the_test_page(self):
        app, _ = self._make_app()
        self.assertEqual(self._pages(app), ["外觀", "螢幕", "運作", "測試"])
        self.assertTrue(app.has_test_page)

    def test_packaged_build_has_no_test_page(self):
        from deskisle import gui
        with mock.patch.object(gui, "is_frozen", lambda: True):
            app, _ = self._make_app()
        self.assertEqual(self._pages(app), ["外觀", "螢幕", "運作"])
        self.assertFalse(app.has_test_page)

    def test_controls_round_trip_the_config(self):
        app, _ = self._make_app()
        self.assertEqual(app.draft_config(), Config())
        app.var_theme.set("宇宙(cosmos)")
        app.var_seed.set(123)
        app.var_margin.set(60.4)
        app.var_decor.set(1.52)
        app.var_poll.set(2.04)
        draft = app.draft_config()
        self.assertEqual((draft.theme, draft.seed, draft.margin, draft.decorations, draft.poll_interval),
                         ("cosmos", 123, 60.0, 1.5, 2.0))

    def test_behaviour_changes_do_not_apply_an_unapplied_look(self):
        app, _ = self._make_app()
        app.var_theme.set("火山(volcano)")     # 只是預覽,還沒按套用
        app.var_pause.set(False)
        app._behavior_changed()
        self.assertEqual(app.applied.theme, "beach")
        self.assertFalse(app.applied.pause_when_busy)

    def test_theme_chips_choose_the_theme_and_highlight_it(self):
        from deskisle import ui_style
        app, _ = self._make_app()
        self.assertEqual(len(app._theme_chips), len(app._theme_names))
        app._choose_theme("volcano")
        self.assertEqual(app.draft_config().theme, "volcano")
        self.assertEqual(str(app._theme_chips["volcano"].cget("highlightbackground")), ui_style.ACCENT)
        self.assertEqual(str(app._theme_chips["beach"].cget("highlightbackground")), ui_style.CARD)

    def test_reseed_from_watcher_updates_applied_config_and_seed_box(self):
        app, root = self._make_app()
        app._on_reseed(4321)
        self.assertEqual(app.applied.seed, 4321)      # 監看執行緒立刻讀得到
        root.update()
        self.assertEqual(app.var_seed.get(), 4321)    # 介面上的種子跟著換

    def test_reseed_does_not_overwrite_a_seed_the_user_is_editing(self):
        app, root = self._make_app()
        app.var_seed.set(55)                          # 使用者正在試別的種子,還沒套用
        app._on_reseed(4321)
        root.update()
        self.assertEqual(app.var_seed.get(), 55)
        self.assertEqual(app.applied.seed, 4321)

    def test_headless_app_writes_nothing(self):
        app, _ = self._make_app()
        app.var_follow.set(True)
        app._follow_toggled()
        app.apply_now()
        self.assertFalse(app.watcher.running)
        self.assertEqual(list(Path(self.tmp.name).rglob("*")), [])

    def test_preview_is_a_png_of_the_requested_width(self):
        import io
        from deskisle import gui
        from deskisle.icons import DesktopIcon, DesktopLayout
        layout = DesktopLayout(1920, 1080, (DesktopIcon("a", 0, 5, 76, 75),))
        data = gui.render_preview(layout, Config(theme="cosmos"), 320)
        image = Image.open(io.BytesIO(data))
        self.assertEqual(image.size, (320, 180))


@unittest.skipUnless(WINDOWS, "需要 Windows")
class WallpaperBackupTests(unittest.TestCase):
    """用假的「目前桌布」與假的「設定桌布」走完備份 → 套用 → 還原。"""

    def setUp(self):
        from deskisle import wallpaper
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
