import unittest

from multiseat_arch.device_ui import (
    clean_device_name,
    group_devices,
    is_system_device,
    is_useful_input,
)
from multiseat_arch.model import InputDevice


def device(
    name: str,
    kind: str,
    key: str,
    *,
    group: str = "",
    bus: str = "usb",
    seat: str = "seat0",
) -> InputDevice:
    return InputDevice(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        event=f"/dev/input/{key}",
        syspath=f"/sys/devices/{key}",
        bus=bus,
        key=key,
        seat=seat,
        group_key=group,
    )


class DeviceUiTests(unittest.TestCase):
    def test_groups_composite_usb_interfaces_without_losing_keys(self):
        values = [
            device("BY Tech Gaming Keyboard", "keyboard", "input-a", group="group-1"),
            device(
                "BY Tech Gaming Keyboard Consumer Control",
                "mouse",
                "input-b",
                group="group-1",
            ),
            device(
                "BY Tech Gaming Keyboard System Control",
                "keyboard",
                "input-c",
                group="group-1",
            ),
        ]
        groups = group_devices(values)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].name, "BY Tech Gaming Keyboard")
        self.assertEqual(groups[0].kind, "keyboard")
        self.assertEqual(groups[0].keys, ["input-a", "input-b", "input-c"])

    def test_mouse_name_wins_for_mixed_hid_group(self):
        values = [
            device("USB Gaming Mouse", "mouse", "input-a", group="group-1"),
            device("USB Gaming Mouse Consumer Control", "keyboard", "input-b", group="group-1"),
        ]
        self.assertEqual(group_devices(values)[0].kind, "mouse")

    def test_can_disable_grouping(self):
        values = [
            device("Keyboard", "keyboard", "input-a", group="group-1"),
            device("Keyboard Consumer Control", "keyboard", "input-b", group="group-1"),
        ]
        self.assertEqual(len(group_devices(values, group_interfaces=False)), 2)

    def test_never_groups_internal_devices_by_shared_group_key(self):
        values = [
            device("AT Keyboard", "keyboard", "input-a", group="group-x", bus="i8042"),
            device("Touchpad", "touchpad", "input-b", group="group-x", bus="i2c"),
        ]
        self.assertEqual(len(group_devices(values)), 2)

    def test_system_buttons_and_internal_other_are_not_auto_assigned(self):
        power = device("Power Button", "other", "input-power", bus="platform")
        keyboard_flagged_power = device(
            "Power Button", "keyboard", "input-power-kbd", bus="platform"
        )
        wmi = device("Acer WMI hotkeys", "other", "input-wmi", bus="interno")
        jack = device("HDA Intel PCH Front Headphone", "other", "input-jack", bus="pci")
        keyboard = device("USB Keyboard", "keyboard", "input-keyboard")
        self.assertTrue(is_system_device(power))
        self.assertFalse(is_useful_input(power))
        self.assertTrue(is_system_device(keyboard_flagged_power))
        self.assertFalse(is_useful_input(keyboard_flagged_power))
        self.assertTrue(is_system_device(wmi))
        self.assertTrue(is_system_device(jack))
        self.assertTrue(is_useful_input(keyboard))

    def test_clean_name_removes_only_control_suffix(self):
        self.assertEqual(
            clean_device_name("Gaming Keyboard Consumer Control"),
            "Gaming Keyboard",
        )


if __name__ == "__main__":
    unittest.main()
