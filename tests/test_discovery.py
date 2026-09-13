import unittest
from multiseat_arch.discovery import parse_libinput, connector_lease_name

SAMPLE = '''Device:           AT Translated Set 2 keyboard
Kernel:           /dev/input/event3

Device:           ELAN0504:01 04F3:312A Touchpad
Kernel:           /dev/input/event6
'''

class DiscoveryTests(unittest.TestCase):
    def test_parse_libinput(self):
        self.assertEqual(parse_libinput(SAMPLE), [
            ("AT Translated Set 2 keyboard", "/dev/input/event3"),
            ("ELAN0504:01 04F3:312A Touchpad", "/dev/input/event6"),
        ])

    def test_connector_validation(self):
        self.assertEqual(connector_lease_name("card1-HDMI-A-1"), "card1-HDMI-A-1")
        with self.assertRaises(ValueError):
            connector_lease_name("HDMI-A-1")

if __name__ == "__main__":
    unittest.main()
