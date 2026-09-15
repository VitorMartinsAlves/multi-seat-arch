import importlib.util
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

if importlib.util.find_spec("evdev") is None:
    raise unittest.SkipTest("python-evdev não está instalado")

from multiseat_arch import input_proxy


class InputProxyTests(unittest.TestCase):
    def test_clone_preserves_properties_and_hardware_identity(self):
        device = Mock()
        device.name = "ELAN Touchpad"
        device.info = SimpleNamespace(bustype=3, vendor=0x04F3, product=0x312A, version=1)
        device.input_props.return_value = [0, 5]

        fake_ui = object()
        with patch.object(input_proxy.UInput, "from_device", return_value=fake_ui) as create:
            self.assertIs(input_proxy._clone(device, "seat-b"), fake_ui)

        create.assert_called_once_with(
            device,
            name="MSA Shared ELAN Touchpad [seat-b]",
            phys="multi-seat-arch/seat-b",
            input_props=[0, 5],
            bustype=3,
            vendor=0x04F3,
            product=0x312A,
            version=1,
        )

    def test_event_syspath_returns_seat_eligible_input_parent(self):
        proc = SimpleNamespace(
            stdout=(
                "/devices/pci0000:00/0000:00:14.0/usb1/1-4/1-4.2/"
                "1-4.2:1.0/input/input6/event6\n"
            ),
            returncode=0,
        )
        with patch.object(input_proxy, "_run", return_value=proc):
            path = input_proxy._event_syspath("/dev/input/event6")
        self.assertEqual(
            path,
            "/sys/devices/pci0000:00/0000:00:14.0/usb1/1-4/1-4.2/"
            "1-4.2:1.0/input/input6",
        )


if __name__ == "__main__":
    unittest.main()
