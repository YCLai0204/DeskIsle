"""設定檔:預設值、讀寫、檢查。

執行:python -m unittest discover -s tests -v
"""

import json
import tempfile
import unittest
from pathlib import Path

from deskisle.config import Config, load_config, save_config


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


if __name__ == "__main__":
    unittest.main()
