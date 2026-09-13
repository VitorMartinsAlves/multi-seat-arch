import json
import tempfile
import unittest
from pathlib import Path

from multiseat_arch import config
from multiseat_arch.model import Config, Seat


class ConfigTests(unittest.TestCase):
    def test_roundtrip(self):
        value = Config(
            seats=[
                Seat(
                    "seat-a",
                    "card1-HDMI-A-1",
                    "vitor",
                    ["/sys/devices/a"],
                )
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            config.save(value, path)
            self.assertEqual(config.load(path).to_dict(), value.to_dict())
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)

    def test_rejects_unknown_seat_fields(self):
        with self.assertRaises(ValueError):
            Config.from_dict(
                {
                    "seats": [
                        {
                            "name": "seat-a",
                            "connector": "card1-HDMI-A-1",
                            "user": "vitor",
                            "inputs": [],
                            "command": "rm -rf /",
                        }
                    ]
                }
            )

    def test_rejects_non_object_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps([]), encoding="utf-8")
            with self.assertRaises(ValueError):
                config.load(path)


if __name__ == "__main__":
    unittest.main()
