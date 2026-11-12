"""設定介面:頁面、設定值往返、主題選擇、自繪元件、預覽。

介面以 headless 模式建立:不顯示、不啟動監看、不寫設定。

執行:python -m unittest discover -s tests -v
"""

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from deskisle.config import Config
from deskisle.engine.layout import DesktopIcon, DesktopLayout

WINDOWS = sys.platform == "win32"


@unittest.skipUnless(WINDOWS, "需要 Windows")
class GuiTests(unittest.TestCase):
    """建立介面但不顯示視窗(headless):不啟動監看、不建系統匣、不寫設定。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"LOCALAPPDATA": self.tmp.name, "DESKISLE_APPEARANCE": "light"})
        env.start()
        self.addCleanup(env.stop)

    def _make_app(self):
        import tkinter as tk
        from deskisle.ui import app as gui
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        return gui.App(root, headless=True), root

    def test_source_build_has_the_test_page(self):
        app, _ = self._make_app()
        self.assertEqual(app.page_names(), ["外觀", "螢幕", "運作", "測試"])
        self.assertTrue(app.has_test_page)

    def test_packaged_build_has_no_test_page(self):
        from deskisle.ui import app as gui
        with mock.patch.object(gui, "is_frozen", lambda: True):
            app, _ = self._make_app()
        self.assertEqual(app.page_names(), ["外觀", "螢幕", "運作"])
        self.assertFalse(app.has_test_page)

    def test_switching_pages_shows_one_page_and_selects_its_nav_item(self):
        app, root = self._make_app()
        app.show_page("運作")
        root.update_idletasks()
        self.assertEqual(app.current_page, "運作")
        self.assertEqual(app.page_title.cget("text"), "運作")
        self.assertEqual([name for name, page in app.pages.items() if page.winfo_manager()], ["運作"])
        self.assertEqual([name for name, item in app._nav.items() if item.selected], ["運作"])

    def test_appearance_follows_the_environment_override(self):
        from deskisle.ui import style
        app, _ = self._make_app()
        self.assertIs(app.kit.p, style.LIGHT)
        with mock.patch.dict(os.environ, {"DESKISLE_APPEARANCE": "dark"}):
            app, _ = self._make_app()
        self.assertIs(app.kit.p, style.DARK)

    def test_appearance_can_be_switched_from_the_window(self):
        from deskisle.ui import style
        with mock.patch.dict(os.environ, {"DESKISLE_APPEARANCE": ""}):
            app, root = self._make_app()
            app.show_page("運作")
            app.var_seed.set(321)                          # 還沒套用的外觀,重建後要留著
            target = "light" if app.kit.p.dark else "dark"
            app.var_appearance.set(target)
            app._appearance_changed()
            root.update()
            self.assertIs(app.kit.p, style.DARK if target == "dark" else style.LIGHT)
            self.assertEqual(app.applied.appearance, target)
            self.assertEqual(app.current_page, "運作")
            self.assertEqual(app.var_seed.get(), 321)
            self.assertEqual(app.applied.seed, Config().seed)
            self.assertEqual(app.page_names(), ["外觀", "螢幕", "運作", "測試"])

    def test_segmented_control_chooses_by_click_and_keyboard(self):
        import tkinter as tk
        from deskisle.ui import style
        from deskisle.ui.widgets import Kit, Segmented
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        var = tk.StringVar(value="a")
        changes = []
        control = Segmented(root, Kit(root, style.LIGHT), (("a", "甲"), ("b", "乙"), ("c", "丙")), var,
                            lambda: changes.append(var.get()))
        left, right = list(control._bounds())[2]
        control._click(mock.Mock(x=(left + right) // 2))
        control._step(-1)
        control._step(-1)
        control._step(-1)                                   # 已經是第一個,不會再變
        self.assertEqual(changes, ["c", "b", "a"])

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

    def test_theme_tiles_choose_the_theme_and_highlight_it(self):
        app, _ = self._make_app()
        self.assertEqual(len(app._theme_tiles), len(app._theme_names))
        app._theme_tiles["volcano"]._click()
        self.assertEqual(app.draft_config().theme, "volcano")
        self.assertEqual([key for key, tile in app._theme_tiles.items() if tile.selected], ["volcano"])
        self.assertEqual(app.pending_pill.text, "尚未套用")

    def test_toggle_flips_its_variable_and_both_follow_switches_agree(self):
        from deskisle.ui.widgets import Toggle
        app, _ = self._make_app()
        switches = [w for w in _descendants(app.root) if isinstance(w, Toggle) and w.variable is app.var_follow]
        self.assertEqual(len(switches), 2)            # 左下角一個,「運作」頁一個
        switches[0]._click()
        self.assertTrue(app.var_follow.get())
        self.assertTrue(app.applied.follow)
        self.assertEqual(app._state_text.cget("text"), "啟動中…")

    def test_slider_sets_its_variable_from_the_pointer(self):
        from deskisle.ui.widgets import Slider
        app, root = self._make_app()
        slider = next(w for w in _descendants(app.root) if isinstance(w, Slider) and w.variable is app.var_margin)
        root.update_idletasks()
        slider.configure(width=220)
        slider.update_idletasks()
        start, end = slider._ends()
        slider._set_from(end + 50)                    # 拖過頭 → 最大值
        self.assertEqual(app.draft_config().margin, 110)
        slider._set_from(start)
        self.assertEqual(app.draft_config().margin, 20)

    def test_disabled_button_does_nothing(self):
        import tkinter as tk
        from deskisle.ui.widgets import Button, Kit
        from deskisle.ui import style
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        clicks = []
        button = Button(root, Kit(root, style.LIGHT), "按我", lambda: clicks.append(1), kind="primary")
        button.invoke()
        button.set_enabled(False)
        button.invoke()
        self.assertEqual(clicks, [1])

    def test_choosing_a_mode_without_a_picture_asks_for_one(self):
        from deskisle.ui import app as gui
        app, _ = self._make_app()
        with mock.patch.object(gui.filedialog, "askopenfilename", return_value="") as ask:
            app.var_image_mode.set("water")
            app._image_mode_changed()
        ask.assert_called_once()
        self.assertEqual(app.var_image_mode.get(), "off")        # 取消 → 維持不使用

    def test_choosing_a_picture_copies_it_and_uses_it_as_land(self):
        from deskisle.ui import app as gui
        app, _ = self._make_app()
        source = Path(self.tmp.name) / "我的照片.png"
        Image.new("RGB", (64, 40), (200, 60, 30)).save(source)
        with mock.patch.object(gui.filedialog, "askopenfilename", return_value=str(source)):
            app._choose_image()
        draft = app.draft_config()
        self.assertEqual(draft.image_mode, "land")
        self.assertEqual(Path(draft.image).parent.name, "images")
        self.assertTrue(Path(draft.image).exists())
        self.assertEqual(app.image_caption.cget("text"), "64 × 40")
        self.assertEqual(app.pending_pill.text, "尚未套用")
        app._remove_image()
        self.assertEqual((app.draft_config().image, app.draft_config().image_mode), ("", "off"))

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
        from deskisle.ui.preview import render_preview
        layout = DesktopLayout(1920, 1080, (DesktopIcon("a", 0, 5, 76, 75),))
        data = render_preview(layout, Config(theme="cosmos"), 320)
        image = Image.open(io.BytesIO(data))
        self.assertEqual(image.size, (320, 180))

    def test_preview_fits_inside_its_box(self):
        from deskisle.ui.preview import fit_width
        wide = DesktopLayout(1920, 1080, ())
        tall = DesktopLayout(1080, 1920, ())
        self.assertEqual(fit_width(wide, 480, 400), 480)      # 寬度先用完
        self.assertEqual(fit_width(tall, 480, 400), 225)      # 高度先用完


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


if __name__ == "__main__":
    unittest.main()
