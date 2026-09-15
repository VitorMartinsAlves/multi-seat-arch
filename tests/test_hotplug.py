import unittest
from unittest.mock import patch

from multiseat_arch import hotplug
from multiseat_arch.model import Config, Seat


class HotplugSafetyTests(unittest.TestCase):
    def test_requires_every_enabled_seat_to_be_running(self):
        config = Config(
            seats=[
                Seat("seat-a", "card1-HDMI-A-1", "alice", enabled=True),
                Seat("seat-b", "card1-eDP-1", "bob", enabled=True),
            ]
        )
        with patch.object(
            hotplug,
            "runtime_status",
            return_value={"running": True, "seats": ["seat-a"]},
        ):
            self.assertFalse(hotplug._all_configured_seats_running(config))

    def test_ignores_disabled_seats(self):
        config = Config(
            seats=[
                Seat("seat-a", "card1-HDMI-A-1", "alice", enabled=True),
                Seat("seat-b", "card1-eDP-1", "bob", enabled=False),
            ]
        )
        with patch.object(
            hotplug,
            "runtime_status",
            return_value={"running": True, "seats": ["seat-a"]},
        ):
            self.assertTrue(hotplug._all_configured_seats_running(config))


if __name__ == "__main__":
    unittest.main()
