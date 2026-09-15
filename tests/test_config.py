import json
import tempfile
import unittest
from pathlib import Path

from multiseat_arch import config
from multiseat_arch.model import Config, DeviceRule, Seat


class ConfigTests(unittest.TestCase):
    def test_roundtrip_v2(self):
        value = Config(
            seats=[
                Seat("seat-a", "card1-HDMI-A-1", "vitor", enabled=True),
                Seat("seat-b", "card1-eDP-1", "guest", enabled=False),
            ],
            devices=[
                DeviceRule(
                    "input-111111111111111111111111", "seat", "seat-a", "Mouse"
                ),
                DeviceRule(
                    "input-222222222222222222222222", "shared", "", "Keyboard"
                ),
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            config.save(value, path)
            self.assertEqual(config.load(path).to_dict(), value.to_dict())
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)

    def test_migrates_v1_to_v2(self):
        migrated = Config.from_dict(
            {
                "version": 1,
                "seats": [
                    {
                        "name": "seat-a",
                        "connector": "card1-HDMI-A-1",
                        "user": "vitor",
                        "inputs": ["/sys/devices/legacy"],
                    }
                ],
            }
        )
        self.assertEqual(migrated.version, 2)
        self.assertEqual(migrated.seats[0].inputs, ["/sys/devices/legacy"])

    def test_rejects_legacy_input_owned_by_two_seats(self):
        with self.assertRaisesRegex(ValueError, "Input legado usado por mais de um seat"):
            Config.from_dict(
                {
                    "version": 1,
                    "seats": [
                        {
                            "name": "seat-a",
                            "connector": "card1-HDMI-A-1",
                            "user": "alice",
                            "inputs": ["/sys/devices/shared-input"],
                        },
                        {
                            "name": "seat-b",
                            "connector": "card1-eDP-1",
                            "user": "bob",
                            "inputs": ["/sys/devices/shared-input"],
                        },
                    ],
                }
            )

    def test_rejects_unknown_top_level_fields(self):
        with self.assertRaises(ValueError):
            Config.from_dict({"version": 2, "seats": [], "exec": "oops"})

    def test_rejects_non_boolean_enabled(self):
        with self.assertRaises(ValueError):
            Config.from_dict(
                {
                    "version": 2,
                    "seats": [
                        {
                            "name": "seat-a",
                            "connector": "card1-HDMI-A-1",
                            "user": "vitor",
                            "enabled": "false",
                        }
                    ],
                }
            )

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

    def test_rejects_unknown_device_mode(self):
        with self.assertRaises(ValueError):
            Config.from_dict(
                {
                    "version": 2,
                    "seats": [],
                    "devices": [
                        {
                            "key": "input-111111111111111111111111",
                            "mode": "teleport",
                            "seat": "",
                            "name": "Mouse",
                        }
                    ],
                }
            )

    def test_rejects_unknown_device_fields(self):
        with self.assertRaises(ValueError):
            Config.from_dict(
                {
                    "version": 2,
                    "seats": [],
                    "devices": [
                        {
                            "key": "input-111111111111111111111111",
                            "mode": "shared",
                            "sudo": True,
                        }
                    ],
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
