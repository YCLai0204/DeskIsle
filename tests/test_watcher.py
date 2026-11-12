"""監看器:防抖動、監看迴圈、移動後換種子、忙碌時暫停。

讀取圖示與套用桌布都換成假的,不會動到系統設定。

執行:python -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

from deskisle.config import Config

WINDOWS = sys.platform == "win32"


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
        from deskisle.engine.layout import DesktopIcon, DesktopLayout, IconDetectionError

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
            mock.patch.object(watcher.system, "user_is_busy", lambda: busy),
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
        from deskisle.engine.layout import DesktopIcon, DesktopLayout
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
        from deskisle.engine.layout import DesktopIcon, DesktopLayout

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
        from deskisle.engine.layout import DesktopIcon, DesktopLayout

        layout = DesktopLayout(320, 200, (DesktopIcon("a", 0, 0, 76, 70),))
        box = [Config(poll_interval=0.1, idle_interval=0.1, debounce=0.05)]
        w, applied, states = self._run_watcher(box, [layout], busy=True)
        self.assertTrue(self._wait_for(lambda: "paused" in states))
        self.assertEqual(applied, [])

        # 使用者關掉暫停功能 → 開始運作
        from dataclasses import replace
        box[0] = replace(box[0], pause_when_busy=False)
        self.assertTrue(self._wait_for(lambda: applied == ["beach"]), applied)


if __name__ == "__main__":
    unittest.main()
