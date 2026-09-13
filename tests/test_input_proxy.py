import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

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


if __name__ == "__main__":
    unittest.main()
