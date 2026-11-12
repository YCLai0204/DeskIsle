"""設定介面:分頁、設定值往返、主題選擇、預覽。

介面以 headless 模式建立:不顯示、不啟動監看、不寫設定。

執行:python -m unittest discover -s tests -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from deskisle.config import Config

WINDOWS = sys.platform == "win32"


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
        from deskisle.ui import app as gui
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
        from deskisle.ui import app as gui
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
        from deskisle.ui import style as ui_style
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
        from deskisle.ui import app as gui
        from deskisle.engine.layout import DesktopIcon, DesktopLayout
        layout = DesktopLayout(1920, 1080, (DesktopIcon("a", 0, 5, 76, 75),))
        data = gui.render_preview(layout, Config(theme="cosmos"), 320)
        image = Image.open(io.BytesIO(data))
        self.assertEqual(image.size, (320, 180))


if __name__ == "__main__":
    unittest.main()
