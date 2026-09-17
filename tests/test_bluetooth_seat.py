import unittest

from multiseat_arch.bluetooth_seat import (
    _bluetooth_address_from_output,
    _wireplumber_fragment,
)


class BluetoothSeatTests(unittest.TestCase):
    def test_extracts_address_from_bluez_sink(self):
        self.assertEqual(
            _bluetooth_address_from_output("bluez_output.1C_1A_DF_AC_12_93.1"),
            "1C_1A_DF_AC_12_93",
        )
        self.assertEqual(
            _bluetooth_address_from_output("bluez_input.aa:bb:cc:dd:ee:ff.0"),
            "AA_BB_CC_DD_EE_FF",
        )

    def test_non_bluetooth_output_has_no_address(self):
        self.assertEqual(
            _bluetooth_address_from_output("alsa_output.pci-0000_00_1f.3.analog-stereo"),
            "",
        )

    def test_each_seat_blocks_only_devices_owned_by_other_seats(self):
        owners = {
            "11_22_33_44_55_66": "seat-a",
            "AA_BB_CC_DD_EE_FF": "seat-b",
            "10_20_30_40_50_60": "seat-c",
        }
        seat_a = _wireplumber_fragment("seat-a", owners)
        self.assertNotIn("bluez_card.11_22_33_44_55_66", seat_a)
        self.assertIn("bluez_card.AA_BB_CC_DD_EE_FF", seat_a)
        self.assertIn("bluez_card.10_20_30_40_50_60", seat_a)
        self.assertIn("monitor.bluez = required", seat_a)
        self.assertIn("monitor.bluez.seat-monitoring = disabled", seat_a)

        seat_b = _wireplumber_fragment("seat-b", owners)
        self.assertIn("bluez_card.11_22_33_44_55_66", seat_b)
        self.assertNotIn("bluez_card.AA_BB_CC_DD_EE_FF", seat_b)
        self.assertIn("bluez_card.10_20_30_40_50_60", seat_b)

    def test_empty_owner_map_keeps_bluez_available(self):
        fragment = _wireplumber_fragment("seat-a", {})
        self.assertIn("monitor.bluez = required", fragment)
        self.assertNotIn("device.disabled", fragment)


if __name__ == "__main__":
    unittest.main()
