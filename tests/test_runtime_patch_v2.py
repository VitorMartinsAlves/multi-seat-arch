import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from multiseat_arch import backend
from multiseat_arch.model import Config, Seat


class RuntimePatchV2Tests(unittest.TestCase):
    def test_runtime_rules_tag_event_nodes_not_only_input_parent(self):
        config = Config(seats=[Seat("seat-a", "card1-HDMI-A-1", "alice")])
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
            self.assertIn('KERNEL=="event*"', text)
            self.assertIn('KERNELS=="input6"', text)
            self.assertIn('DEVPATH=="/devices/pci/input/input6/event*"', text)
            self.assertIn('ATTRS{phys}=="multi-seat-arch/seat-card1-HDMI-A-1"', text)

    def test_wait_assignments_validates_event_child(self):
        assignment = ("seat-card1-HDMI-A-1", "/sys/devices/input/input6")
        with (
            patch("multiseat_arch.runtime_patch_v2.Path.glob", return_value=[Path("/sys/devices/input/input6/event6")]),
            patch.object(backend, "_udev_seat", return_value="seat-card1-HDMI-A-1") as seat,
        ):
            backend._wait_assignments([assignment], timeout=1.0)
        seat.assert_called_with("/sys/devices/input/input6/event6")


if __name__ == "__main__":
    unittest.main()
