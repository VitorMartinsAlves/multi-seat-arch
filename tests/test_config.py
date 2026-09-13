import tempfile
import unittest
from pathlib import Path
from multiseat_arch.model import Config, Seat
from multiseat_arch import config

class ConfigTests(unittest.TestCase):
    def test_roundtrip(self):
        c = Config(seats=[Seat("seat-a", "card1-HDMI-A-1", "vitor", ["/sys/devices/a"])])
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.json"
            config.save(c, p)
            self.assertEqual(config.load(p).to_dict(), c.to_dict())

if __name__ == "__main__":
    unittest.main()
