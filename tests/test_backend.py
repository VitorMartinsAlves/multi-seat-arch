import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from multiseat_arch import backend
from multiseat_arch.model import Config, DeviceRule, InputDevice, Seat


class BackendTests(unittest.TestCase):
    def _config(self):
        return Config(
            seats=[
                Seat("seat-a", "card1-HDMI-A-1", "alice"),
                Seat("seat-b", "card1-eDP-1", "bob"),
            ],
            devices=[
                DeviceRule("input-111111111111111111111111", "seat", "seat-a", "Mouse"),
                DeviceRule("input-222222222222222222222222", "shared", "", "Keyboard"),
                DeviceRule("input-333333333333333333333333", "disabled", "", "Gamepad"),
            ],
        )

    def test_runtime_seat_name_matches_connector(self):
        self.assertEqual(
            backend.runtime_seat_name(Seat("seat-a", "card1-HDMI-A-1", "alice")),
            "seat-card1-HDMI-A-1",
        )

    def test_start_schedules_detached_helper(self):
        config = self._config()
        with (
            patch.object(backend.os, "geteuid", return_value=0),
            patch.object(backend, "validate", return_value=[]),
            patch.object(backend, "_schedule_helper") as schedule,
        ):
            backend.start(config)
            schedule.assert_called_once_with(backend.ACTIVATE_UNIT, "_activate")

    def test_start_does_not_schedule_invalid_config(self):
        with (
            patch.object(backend.os, "geteuid", return_value=0),
            patch.object(backend, "validate", return_value=["bad"]),
            patch.object(backend, "_schedule_helper") as schedule,
        ):
            with self.assertRaises(RuntimeError):
                backend.start(Config())
            schedule.assert_not_called()

    def test_write_runtime_rules_contains_physical_and_virtual_routes(self):
        config = self._config()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "73.rules"
            with (
                patch.object(backend, "RUNTIME_UDEV_RULES", target),
                patch.object(backend, "_run", return_value=Mock(stdout="", returncode=0)),
            ):
                backend._write_runtime_udev_rules(
                    config,
                    [("seat-card1-HDMI-A-1", "/sys/devices/pci/input/input6")],
                )
            text = target.read_text()
            self.assertIn('ATTR{phys}=="multi-seat-arch/seat-card1-HDMI-A-1"', text)
            self.assertIn('DEVPATH=="/devices/pci/input/input6"', text)
            self.assertIn('ENV{ID_SEAT}="seat-card1-HDMI-A-1"', text)

    def test_wait_assignments_uses_udev_id_seat(self):
        assignment = ("seat-card1-HDMI-A-1", "/sys/devices/input/input6")
        with patch.object(backend, "_udev_seat", return_value="seat-card1-HDMI-A-1"):
            backend._wait_assignments([assignment], timeout=1.0)

    def test_wait_assignments_detects_wrong_seat(self):
        with (
            patch.object(backend, "_udev_seat", return_value="seat0"),
            patch.object(backend.time, "monotonic", side_effect=[0.0, 0.0, 10.0]),
            patch.object(backend.time, "sleep"),
        ):
            with self.assertRaises(RuntimeError):
                backend._wait_assignments(
                    [("seat-card1-HDMI-A-1", "/sys/devices/input/input6")], timeout=1.0
                )

    def test_sync_routes_dedicated_input_via_runtime_udev_and_proxies_others(self):
        config = self._config()
        devices = [
            InputDevice("Mouse", "mouse", "/dev/input/event1", "/sys/devices/mouse/input/input6", "usb", "input-111111111111111111111111"),
            InputDevice("Keyboard", "keyboard", "/dev/input/event2", "/sys/devices/kbd/input/input7", "usb", "input-222222222222222222222222"),
            InputDevice("Gamepad", "gamepad", "/dev/input/event3", "/sys/devices/pad/input/input8", "usb", "input-333333333333333333333333"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(backend, "READY_DIR", Path(directory)),
                patch.object(backend.os, "geteuid", return_value=0),
                patch.object(backend, "validate", return_value=[]),
                patch.object(backend, "discover_inputs", return_value=devices),
                patch.object(backend, "_stop_units"),
                patch.object(backend, "flush_inputs"),
                patch.object(backend, "_write_runtime_udev_rules") as write_rules,
                patch.object(backend, "_wait_assignments") as wait_assignments,
                patch.object(backend, "_start_proxy") as proxy,
            ):
                backend.sync_devices_now(config)

            direct = [("seat-card1-HDMI-A-1", "/sys/devices/mouse/input/input6")]
            write_rules.assert_called_once_with(config, direct)
            wait_assignments.assert_called_once_with(direct)
            self.assertEqual(proxy.call_count, 2)

    def test_failed_activation_persists_error_and_rolls_back(self):
        config = self._config()
        with (
            patch.object(backend.os, "geteuid", return_value=0),
            patch.object(backend, "validate", return_value=[]),
            patch.object(backend, "doctor", return_value=[backend.Check(True, "ok")]),
            patch.object(backend, "stop_transient_units", side_effect=RuntimeError("boom")),
            patch.object(backend, "_persist_activation_error") as persist,
            patch.object(backend, "_rollback_after_failed_start") as rollback,
        ):
            with self.assertRaises(RuntimeError):
                backend.activate_now(config)
            persist.assert_called_once()
            rollback.assert_called_once()

    def test_disabled_seat_is_not_active(self):
        config = Config(
            seats=[
                Seat("seat-a", "card1-HDMI-A-1", "alice", enabled=True),
                Seat("seat-b", "card1-eDP-1", "bob", enabled=False),
            ]
        )
        self.assertEqual([s.name for s in backend.active_seats(config)], ["seat-a"])


if __name__ == "__main__":
    unittest.main()
