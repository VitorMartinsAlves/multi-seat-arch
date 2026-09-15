import unittest

from multiseat_arch.discovery import (
    _kind_from_props,
    connector_lease_name,
    parse_libinput,
    parse_udev_properties,
    stable_device_key,
)


SAMPLE = """Device:           AT Translated Set 2 keyboard
Kernel:           /dev/input/event3

Device:           ELAN0504:01 04F3:312A Touchpad
Kernel:           /dev/input/event6
"""


class DiscoveryTests(unittest.TestCase):
    def test_parse_libinput(self):
        self.assertEqual(
            parse_libinput(SAMPLE),
            [
                ("AT Translated Set 2 keyboard", "/dev/input/event3"),
                ("ELAN0504:01 04F3:312A Touchpad", "/dev/input/event6"),
            ],
        )

    def test_parse_udev_properties(self):
        self.assertEqual(
            parse_udev_properties(
                "ID_INPUT=1\nID_INPUT_TOUCHPAD=1\nID_BUS=i2c\n"
            ),
            {
                "ID_INPUT": "1",
                "ID_INPUT_TOUCHPAD": "1",
                "ID_BUS": "i2c",
            },
        )

    def test_stable_key_survives_event_and_usb_port_change_with_real_serial(self):
        props_a = {
            "ID_INPUT": "1",
            "ID_INPUT_KEYBOARD": "1",
            "ID_PATH": "pci-0000:00:14.0-usb-0:4.2:1.0",
            "ID_SERIAL": "BY_Tech_Keyboard_ABC",
            "ID_SERIAL_SHORT": "ABC",
        }
        props_b = dict(props_a)
        props_b["ID_PATH"] = "pci-0000:00:14.0-usb-0:7.1:1.0"
        key_a = stable_device_key(
            "Gaming Keyboard", "keyboard",
            "/sys/devices/pci/usb/4-2/4-2:1.0/input/input3/event3", props_a,
        )
        key_b = stable_device_key(
            "Gaming Keyboard", "keyboard",
            "/sys/devices/pci/usb/7-1/7-1:1.0/input/input99/event99", props_b,
        )
        self.assertEqual(key_a, key_b)
        self.assertRegex(key_a, r"^input-[a-f0-9]{24}$")

    def test_synthesized_serial_without_short_stays_bound_to_port(self):
        common = {
            "ID_INPUT": "1",
            "ID_INPUT_MOUSE": "1",
            "ID_SERIAL": "Cheap_USB_Mouse",
        }
        key_a = stable_device_key(
            "Cheap USB Mouse", "mouse", "/sys/devices/a/input/input1/event1",
            {**common, "ID_PATH": "usb-port-a"},
        )
        key_b = stable_device_key(
            "Cheap USB Mouse", "mouse", "/sys/devices/b/input/input1/event1",
            {**common, "ID_PATH": "usb-port-b"},
        )
        self.assertNotEqual(key_a, key_b)

    def test_composite_device_interfaces_do_not_collide(self):
        common = {
            "ID_SERIAL": "Gaming_Device_ABC",
            "ID_SERIAL_SHORT": "ABC",
            "ID_INPUT_KEYBOARD": "1",
        }
        first = stable_device_key(
            "Gaming Keyboard", "keyboard", "/sys/devices/a",
            {**common, "ID_USB_INTERFACE_NUM": "00"},
        )
        second = stable_device_key(
            "Gaming Keyboard", "keyboard", "/sys/devices/b",
            {**common, "ID_USB_INTERFACE_NUM": "01"},
        )
        self.assertNotEqual(first, second)

    def test_devices_without_serial_remain_bound_to_physical_path(self):
        key_a = stable_device_key(
            "Cheap USB Mouse", "mouse", "/sys/devices/a/input/input1/event1",
            {"ID_PATH": "usb-port-a"},
        )
        key_b = stable_device_key(
            "Cheap USB Mouse", "mouse", "/sys/devices/b/input/input1/event1",
            {"ID_PATH": "usb-port-b"},
        )
        self.assertNotEqual(key_a, key_b)

    def test_gamepad_detection(self):
        self.assertEqual(
            _kind_from_props("Xbox Wireless Controller", {"ID_INPUT_JOYSTICK": "1"}),
            "gamepad",
        )

    def test_connector_validation(self):
        self.assertEqual(connector_lease_name("card1-HDMI-A-1"), "card1-HDMI-A-1")
        self.assertEqual(connector_lease_name("card0-eDP-1"), "card0-eDP-1")
        with self.assertRaises(ValueError):
            connector_lease_name("HDMI-A-1")
        with self.assertRaises(ValueError):
            connector_lease_name("card1-HDMI A 1")


if __name__ == "__main__":
    unittest.main()
