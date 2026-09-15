import unittest
from contextlib import nullcontext
from unittest.mock import patch

from multiseat_arch import live
from multiseat_arch.model import Config, Seat


class LiveSyncTests(unittest.TestCase):
    def test_refuses_sync_when_multiseat_is_not_running(self):
        config = Config()
        with (
            patch.object(live, "runtime_status", return_value={"running": False, "seats": []}),
            patch.object(live, "sync_devices_now") as sync,
        ):
            with self.assertRaises(RuntimeError):
                live.sync_live(config)
            sync.assert_not_called()

    def test_refuses_sync_when_one_configured_seat_is_missing(self):
        config = Config(
            seats=[
                Seat("seat-a", "card1-HDMI-A-1", "alice"),
                Seat("seat-b", "card1-eDP-1", "bob"),
            ]
        )
        with (
            patch.object(
                live,
                "runtime_status",
                return_value={"running": True, "seats": ["seat-a"]},
            ),
            patch.object(live, "input_sync_lock", return_value=nullcontext()),
            patch.object(live, "sync_devices_now") as sync,
        ):
            with self.assertRaisesRegex(RuntimeError, "seat-b"):
                live.sync_live(config)
            sync.assert_not_called()

    def test_syncs_when_all_configured_seats_are_running(self):
        config = Config(
            seats=[
                Seat("seat-a", "card1-HDMI-A-1", "alice"),
                Seat("seat-b", "card1-eDP-1", "bob"),
            ]
        )
        with (
            patch.object(
                live,
                "runtime_status",
                return_value={"running": True, "seats": ["seat-a", "seat-b"]},
            ),
            patch.object(live, "input_sync_lock", return_value=nullcontext()),
            patch.object(live, "sync_devices_now") as sync,
        ):
            live.sync_live(config)
            sync.assert_called_once_with(config)


if __name__ == "__main__":
    unittest.main()
