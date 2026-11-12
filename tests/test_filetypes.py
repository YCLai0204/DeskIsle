"""依檔案類型的裝飾物:判斷檔案類型、在圖示旁邊擺放、監看時才讀名稱。

執行:python -m unittest discover -s tests -v
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from deskisle import filetypes
from deskisle.config import Config
from deskisle.engine import decor
from deskisle.engine.render import render
from deskisle.engine.terrain import shore_field
from deskisle.engine.themes import THEMES, get_theme

WINDOWS = sys.platform == "win32"
ICON = (200, 120, 276, 190)
FIELD_ARGS = dict(margin=46.0, blend=26.0, roughness=22.0, seed=7)


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.user = Path(self.tmp.name) / "user"
        self.public = Path(self.tmp.name) / "public"
        for folder in (self.user, self.public):
            folder.mkdir()
        (self.user / "專案").mkdir()
        for name in ("旅行.JPG", "報告.docx", "Chrome.lnk", "遊戲.exe", "歌.mp3", "壓縮檔.zip"):
            (self.user / name).write_bytes(b"")
        (self.public / "共用捷徑.url").write_bytes(b"")

    def test_names_with_or_without_extensions(self):
        names = ["專案", "旅行.JPG", "報告", "Chrome", "遊戲", "歌.mp3", "壓縮檔", "共用捷徑", "本機", ""]
        self.assertEqual(filetypes.classify(names, [self.user, self.public]),
                         ["folder", "image", "document", "shortcut", "app", "media", "other", "shortcut",
                          "other", "other"])

    def test_missing_folders_are_ignored(self):
        self.assertEqual(filetypes.classify(["報告"], [Path(self.tmp.name) / "沒有", self.user]), ["document"])

    def test_every_theme_has_a_companion_for_every_kind(self):
        for theme in THEMES.values():
            self.assertEqual({kind for kind, _rule in theme.companions}, set(filetypes.KINDS), theme.key)


class PlacementTests(unittest.TestCase):
    def setUp(self):
        self.theme = get_theme("beach")
        self.table = dict(self.theme.companions)

    def _field(self, rects):
        return shore_field(640, 360, rects, **FIELD_ARGS)

    def test_each_icon_gets_one_companion_in_its_zone_without_covering_icons(self):
        rects = [ICON, (420, 120, 496, 190)]
        field = self._field(rects)
        placed = decor.place_companions(field, rects, ["folder", "shortcut"], self.table, seed=3)
        self.assertEqual([p.rule.kind for p in placed], ["palm", "boat"])
        for p in placed:
            self.assertTrue(p.rule.lo <= field[p.y, p.x] < p.rule.hi)
            half = p.size / 2
            for left, top, right, bottom in rects:
                self.assertFalse(p.x + half > left and p.x - half < right and p.y + half > top and p.y - half < bottom)

    def test_other_files_get_nothing(self):
        field = self._field([ICON])
        self.assertEqual(decor.place_companions(field, [ICON], ["other"], self.table, seed=3), [])

    def test_moving_another_icon_does_not_move_this_companion(self):
        first = decor.place_companions(self._field([ICON, (500, 40, 576, 110)]), [ICON, (500, 40, 576, 110)],
                                       ["folder", "image"], self.table, seed=3)
        moved = decor.place_companions(self._field([ICON, (520, 250, 596, 320)]), [ICON, (520, 250, 596, 320)],
                                       ["folder", "image"], self.table, seed=3)
        self.assertEqual((first[0].x, first[0].y), (moved[0].x, moved[0].y))

    def test_render_draws_them_only_when_decorations_are_on(self):
        plain = render(640, 360, [ICON], self.theme, seed=3)
        tagged = render(640, 360, [ICON], self.theme, seed=3, tags=["folder"])
        self.assertNotEqual(plain.tobytes(), tagged.tobytes())
        self.assertEqual(render(640, 360, [ICON], self.theme, seed=3, decorations=0).tobytes(),
                         render(640, 360, [ICON], self.theme, seed=3, decorations=0, tags=["folder"]).tobytes())


@unittest.skipUnless(WINDOWS, "需要 Windows")
class WatcherNamesTests(unittest.TestCase):
    """平常輪詢不讀名稱,只有要重畫時才讀一次。"""

    def _run(self, config):
        from deskisle import watcher
        from deskisle.engine.layout import DesktopIcon, DesktopLayout
        calls = []

        def fake_read(names=True):
            calls.append(names)
            return DesktopLayout(640, 360, (DesktopIcon("報告" if names else "", *ICON),))

        applied = []
        with mock.patch.object(watcher, "read_layout", fake_read), \
                mock.patch.object(watcher, "apply_layout", lambda layout, cfg: applied.append(layout)), \
                mock.patch.object(watcher.system, "user_is_busy", lambda: False), \
                mock.patch.object(watcher.system, "desktop_is_foreground", lambda: True):
            w = watcher.Watcher(lambda: config)
            debouncer = watcher.LayoutDebouncer(0)
            for _ in range(3):
                w._tick(config, debouncer)
        return calls, applied

    def test_names_are_read_only_before_drawing(self):
        calls, applied = self._run(Config(file_decor=True))
        self.assertEqual(calls, [False, True, False, False])     # 第一次要畫 → 多讀一次名稱
        self.assertEqual([icon.name for icon in applied[0].icons], ["報告"])

    def test_names_are_never_read_when_turned_off(self):
        calls, _applied = self._run(Config(file_decor=False))
        self.assertEqual(calls, [False, False, False])


if __name__ == "__main__":
    unittest.main()
