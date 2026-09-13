import unittest
from unittest.mock import Mock, patch

from multiseat_arch import backend
from multiseat_arch.model import Config, Seat


class BackendTests(unittest.TestCase):
    def test_start_schedules_detached_helper(self):
        config = Config(
            seats=[
                Seat("seat-a", "card1-HDMI-A-1", "alice", ["/sys/devices/a"]),
                Seat("seat-b", "card1-eDP-1", "bob", ["/sys/devices/b"]),
            ]
        )
        with (
            patch.object(backend.os, "geteuid", return_value=0),
            patch.object(backend, "validate", return_value=[]),
            patch.object(backend, "_schedule_helper") as schedule,
        ):
            backend.start(config)
            schedule.assert_called_once_with(
                backend.ACTIVATE_UNIT,
                "_activate",
            )

    def test_start_does_not_schedule_invalid_config(self):
        config = Config()
        with (
            patch.object(backend.os, "geteuid", return_value=0),
            patch.object(
                backend,
                "validate",
                return_value=["São necessários pelo menos 2 seats."],
            ),
            patch.object(backend, "_schedule_helper") as schedule,
        ):
            with self.assertRaises(RuntimeError):
                backend.start(config)
            schedule.assert_not_called()

    def test_attach_inputs_detects_failed_assignment(self):
        config = Config(
            seats=[
                Seat("seat-a", "card1-HDMI-A-1", "alice", ["/sys/devices/a"])
            ]
        )
        completed = Mock()
        completed.stdout = ""
        with (
            patch.object(backend, "_run", return_value=completed),
            patch.object(backend, "_udev_seat", return_value="seat0"),
            patch.object(
                backend.time,
                "monotonic",
                side_effect=[0.0, 0.0, 10.0],
            ),
            patch.object(backend.time, "sleep"),
        ):
            with self.assertRaises(RuntimeError):
                backend.attach_inputs(config, timeout=1.0)

    def test_failed_activation_rolls_back(self):
        config = Config()
        with (
            patch.object(backend.os, "geteuid", return_value=0),
            patch.object(backend, "validate", return_value=[]),
            patch.object(
                backend,
                "doctor",
                return_value=[backend.Check(True, "ok")],
            ),
            patch.object(
                backend,
                "stop_transient_units",
                side_effect=RuntimeError("boom"),
            ),
            patch.object(backend, "_rollback_after_failed_start") as rollback,
        ):
            with self.assertRaises(RuntimeError):
                backend.activate_now(config)
            rollback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
